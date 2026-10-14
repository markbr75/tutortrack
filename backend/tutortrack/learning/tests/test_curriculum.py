"""E21-T03 curricula: built-in specs, CSV import, editing, topic tagging from lesson
reports (E09), mastery and the coverage heatmap (FR-21-3)."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.delivery import services as delivery
from tutortrack.learning import curricula, services
from tutortrack.learning.models import Curriculum, CurriculumNode, LessonTopic, TopicMastery

from .conftest import at, events_of, lesson_for

pytestmark = pytest.mark.django_db

URL = "/api/v1/learning/curricula"


def gcse(org, world=None):
    with tenant_context(org):
        curriculum = services.install_builtin("gcse-maths")
        if world is not None:
            curriculum.subject = world["subject"]
            curriculum.save()
        return curriculum


def topic(org, name):
    with tenant_context(org):
        return CurriculumNode.objects.get(name=name, kind="topic")


def test_builtin_specs_install_once(org, world):
    listed = world["admin_api"].get(f"{URL}/builtins").json()
    assert {b["key"] for b in listed} == {"gcse-maths", "ks2-english", "sat-math"}
    response = world["admin_api"].post(f"{URL}/install", {"key": "gcse-maths"}, format="json")
    assert response.status_code == 201, response.content
    spec = curricula.BUILTINS["gcse-maths"]
    assert response.json()["topic_count"] == sum(len(t) for _u, t in spec.units)
    tree = world["admin_api"].get(f"{URL}/{response.json()['id']}/tree").json()
    assert tree[0]["name"] == "Number"
    assert tree[0]["topics"][2] | {"id": None} == {
        "id": None,
        "name": "Fractions",
        "code": "U1.3",
        "position": 3,
    }
    again = world["admin_api"].post(f"{URL}/install", {"key": "gcse-maths"}, format="json")
    assert again.status_code == 409
    unknown = world["admin_api"].post(f"{URL}/install", {"key": "nope"}, format="json")
    assert unknown.status_code == 422
    assert [b["installed"] for b in world["admin_api"].get(f"{URL}/builtins").json()].count(
        True
    ) == 1


def test_csv_import_adds_only_what_is_new(org, world):
    created = world["admin_api"].post(URL, {"name": "11+ Maths"}, format="json").json()
    url = f"{URL}/{created['id']}/import"
    content = "unit,topic,code\nNumber,Fractions,N1\nNumber,Percentages,N2\nShape,Area,\n"
    first = world["admin_api"].post(url, {"content": content}, format="json")
    assert first.json() == {"units": 2, "topics": 3, "skipped": 0}
    again = world["admin_api"].post(url, {"content": content + "Shape,Volume,S2\n"}, format="json")
    assert again.json() == {"units": 0, "topics": 1, "skipped": 3}
    bad = world["admin_api"].post(url, {"content": "name,thing\na,b\n"}, format="json")
    assert bad.status_code == 422
    dupes = world["admin_api"].post(
        url, {"content": "unit,topic,code\nA,x,Z1\nA,y,Z1\n"}, format="json"
    )
    assert dupes.status_code == 422


def test_topics_sit_in_units_and_codes_are_unique(org, world):
    curriculum = gcse(org)
    with tenant_context(org):
        unit = curriculum.nodes.get(code="U1")
        with pytest.raises(BusinessRuleViolation):
            services.save_node(None, curriculum=curriculum, kind="topic", name="Loose")
        with pytest.raises(BusinessRuleViolation):
            services.save_node(None, curriculum=curriculum, parent=unit, name="Dup", code="U1.1")
        node = services.save_node(None, curriculum=curriculum, parent=unit, name="Rounding")
        assert node.position == unit.children.count()
    assert (
        world["tutor_api"]
        .post(
            "/api/v1/learning/curriculum-nodes",
            {"curriculum": str(curriculum.pk), "parent": str(unit.pk), "name": "x"},
            format="json",
        )
        .status_code
        == 403
    )  # tutors don't edit curricula


def test_tagging_a_lesson_moves_mastery_on(org, world):
    gcse(org, world)
    fractions = topic(org, "Fractions")
    lesson = lesson_for(org, world, at(-1), [world["student"]])
    response = world["tutor_api"].post(
        "/api/v1/learning/lesson-topics",
        {"lesson": str(lesson.pk), "nodes": [str(fractions.pk)]},
        format="json",
    )
    assert response.status_code == 201, response.content
    with tenant_context(org):
        mastery = TopicMastery.objects.get(student=world["student"], node=fractions)
        assert (mastery.level, mastery.covered_count) == ("learning", 1)
    assert events_of(org, "topic_mastery.changed")[0]["data"]["level"] == "learning"
    not_theirs = world["other_api"].post(
        "/api/v1/learning/lesson-topics",
        {"lesson": str(lesson.pk), "nodes": [str(fractions.pk)]},
        format="json",
    )
    assert not_theirs.status_code == 403
    row = response.json()[0]["id"]
    assert world["tutor_api"].delete(f"/api/v1/learning/lesson-topics/{row}").status_code == 204
    with tenant_context(org):
        assert TopicMastery.objects.get(pk=mastery.pk).covered_count == 0


def test_report_topics_tag_the_lesson(org, world):
    gcse(org, world)
    with tenant_context(org):
        delivery.create_template(
            name="With topics",
            is_default=True,
            fields=[
                {"key": "covered", "label": "Covered", "type": "rich_text", "required": True},
                {"key": "topics", "label": "Topics", "type": "topics"},
            ],
        )
    lesson = lesson_for(org, world, at(-1), [world["student"]])
    with tenant_context(org):
        report = delivery.open_report(lesson, world["tutor"])
        delivery.submit_report(
            report,
            answers={"covered": "x", "topics": ["fractions", "U1.5", "Something else"]},
        )
    dispatch_batch()  # lesson_report.submitted → learning tags the lesson
    with tenant_context(org):
        names = set(LessonTopic.objects.filter(lesson=lesson).values_list("node__name", flat=True))
        assert names == {"Fractions", "Percentages"}
        assert LessonTopic.objects.filter(report=report).count() == 2


def test_suggestions_put_the_lesson_subject_first(org, world):
    gcse(org, world)
    with tenant_context(org):
        services.install_builtin("ks2-english")
    lesson = lesson_for(org, world, at(1), [world["student"]])
    rows = (
        world["tutor_api"]
        .get("/api/v1/learning/topics", {"lesson": str(lesson.pk), "q": "a"})
        .json()
    )
    assert rows[0]["curriculum"] == "GCSE Mathematics"
    assert (
        world["tutor_api"].get("/api/v1/learning/topics", {"q": "Inference"}).json()[0]["unit"]
        == "Reading"
    )


def test_mastery_is_set_by_tutors_for_their_students(org, world):
    gcse(org)
    node = topic(org, "Surds")
    url = "/api/v1/learning/mastery"
    ok = world["tutor_api"].post(
        url,
        {"student": str(world["student"].pk), "node": str(node.pk), "level": "secure"},
        format="json",
    )
    assert ok.status_code == 200, ok.content
    assert ok.json()["level"] == "secure"
    denied = world["tutor_api"].post(
        url,
        {"student": str(world["stranger"].pk), "node": str(node.pk), "level": "secure"},
        format="json",
    )
    assert denied.status_code == 403
    with tenant_context(org):
        unit = CurriculumNode.objects.get(code="U1")
        with pytest.raises(BusinessRuleViolation):
            services.set_mastery(world["student"], unit, "secure")
    listed = world["tutor_api"].get(url, {"student": str(world["student"].pk)}).json()["results"]
    assert [m["node_name"] for m in listed] == ["Surds"]


def test_coverage_heatmap(org, world):
    gcse(org, world)
    lesson_one = lesson_for(org, world, at(-8), [world["student"]])
    lesson_two = lesson_for(org, world, at(-1), [world["student"]])
    fractions, surds = topic(org, "Fractions"), topic(org, "Surds")
    with tenant_context(org):
        services.tag_lesson(lesson_one, [fractions])
        services.tag_lesson(lesson_two, [fractions])
        services.set_mastery(world["student"], surds, "mastered")
    url = f"/api/v1/learning/students/{world['student'].pk}/coverage"
    body = world["tutor_api"].get(url).json()
    assert len(body) == 1
    number = body[0]["units"][0]
    by_name = {t["name"]: t for t in number["topics"]}
    assert (by_name["Fractions"]["lessons"], by_name["Fractions"]["level"]) == (2, "learning")
    assert (by_name["Surds"]["lessons"], by_name["Surds"]["level"]) == (0, "mastered")
    assert body[0]["covered"] == 1
    assert body[0]["summary"]["mastered"] == 1
    assert world["other_api"].get(url).status_code == 404  # not Sam's student
    portal = (
        world["family"]["api"].get(f"/api/v1/portal/learning/coverage/{world['student'].pk}").json()
    )
    assert portal[0]["covered"] == 1
    assert (
        world["others"]["api"]
        .get(f"/api/v1/portal/learning/coverage/{world['student'].pk}")
        .status_code
        == 404
    )


def test_nodes_used_in_lessons_cannot_be_deleted(org, world):
    gcse(org)
    fractions = topic(org, "Fractions")
    lesson = lesson_for(org, world, at(-1), [world["student"]])
    with tenant_context(org):
        services.tag_lesson(lesson, [fractions])
        with pytest.raises(Conflict):
            services.delete_node(fractions)
        spare = CurriculumNode.objects.get(name="Surds")
        services.delete_node(spare)
        assert not CurriculumNode.objects.filter(name="Surds").exists()
        assert Curriculum.objects.count() == 1
