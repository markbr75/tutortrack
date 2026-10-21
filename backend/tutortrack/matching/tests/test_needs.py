"""Gap G5c (FR-19-1): matching on exam boards, SEN experience and a gender preference."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.matching import engine
from tutortrack.matching.models import MatchQuery
from tutortrack.matching.tests.test_matching import make_job, make_tutor, search
from tutortrack.people import services as people
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def maths(org):
    from tutortrack.catalogue.tests.factories import LevelFactory, ServiceFactory, SubjectFactory

    with tenant_context(org):
        subject = SubjectFactory(organisation=org, name="Maths")
        level = LevelFactory(organisation=org, subject=subject, name="GCSE")
        service = ServiceFactory(organisation=org, subject=subject, level=level)
    return subject, level, service


def needs_job(org, maths, **student_fields):
    job = make_job(org, maths, online=True)
    with tenant_context(org):
        student = job.students.get().student
        people.update_student(student, **student_fields)
    return job


def by_tutor(matches):
    return {m.tutor.pk: m for m in matches}


def test_searches_without_needs_score_as_before(org, maths):
    subject, level, _service = maths
    make_tutor(org, subject, level=level, exam_boards=["AQA"], sen_tags=["Dyslexia"])
    job = make_job(org, maths, online=True)
    (match,) = search(org, job)
    assert set(match.breakdown) == set(engine.FACTORS)


def test_exam_board_and_sen_experience_rank_tutors(org, maths):
    """FR-19-1: the students' exam board and SEN needs come from the job and count."""
    subject, level, _service = maths
    with tenant_context(org):
        subject.exam_boards = ["AQA", "Edexcel"]
        subject.save()
    fit = make_tutor(org, subject, level=level, exam_boards=["aqa"], sen_tags=["Dyslexia", "ADHD"])
    partial = make_tutor(org, subject, level=level, exam_boards=["OCR"], sen_tags=["dyslexia"])
    unknown = make_tutor(org, subject, level=level)
    job = needs_job(
        org, maths, exam_boards=["AQA", "CCEA"], sen_tags=["dyslexia", "adhd", "dyslexia"]
    )
    with tenant_context(org):
        criteria = engine.criteria_for_job(job)
    assert criteria.exam_boards == ["AQA"]  # CCEA isn't a board for this subject
    assert criteria.sen_tags == ["dyslexia", "adhd"]
    rows = by_tutor(search(org, job))
    assert rows[fit.pk].breakdown["exam_board"]["score"] == 1.0
    assert rows[fit.pk].breakdown["sen"]["score"] == 1.0
    assert rows[partial.pk].breakdown["exam_board"]["score"] == 0.0
    assert rows[partial.pk].breakdown["sen"]["value"] == "1/2"
    assert rows[unknown.pk].breakdown["sen"]["known"] is False
    assert rows[fit.pk].score > rows[unknown.pk].score > rows[partial.pk].score


def test_gender_preference_filters_only_when_turned_on(org, maths):
    subject, level, _service = maths
    female = make_tutor(org, subject, level=level, gender="female")
    male = make_tutor(org, subject, level=level, gender="male")
    job = needs_job(org, maths, tutor_gender_preference="female")
    assert set(by_tutor(search(org, job))) == {female.pk, male.pk}  # off by default
    with tenant_context(org):
        settings_service.update_settings("matching", {"matching.gender_preference": True})
    assert set(by_tutor(search(org, job))) == {female.pk}


def test_api_needs_override_and_sensitive_values_hidden(org, maths):
    from tutortrack.identity import services as identity

    subject, level, _service = maths
    make_tutor(org, subject, level=level, sen_tags=["Autism"], exam_boards=["OCR"])
    job = needs_job(org, maths, sen_tags=["Autism"], tutor_gender_preference="male")
    coordinator = MembershipFactory(organisation=org, role="coordinator")
    body = (
        client_for(org, coordinator.user)
        .post(
            "/api/v1/matching/search",
            {"job": str(job.pk), "exam_boards": ["OCR"]},
            format="json",
        )
        .json()
    )
    assert body["needs"] == {
        "exam_boards": ["OCR"],
        "sen_tags": ["Autism"],
        "gender": "male",
        "gender_preference_enabled": False,
    }
    assert body["results"][0]["breakdown"]["exam_board"]["score"] == 1.0
    with tenant_context(org):
        stored = MatchQuery.objects.get().criteria
    assert stored["sen_tag_count"] == 1  # sensitive: count only
    assert "sen_tags" not in stored
    assert stored["gender_preference"] is True
    restricted = MembershipFactory(organisation=org, role="coordinator")
    with tenant_context(org):
        role = identity.create_custom_role(
            name="Matcher",
            clone_from="coordinator",
            grants={"people.student.view_sensitive": "none"},
        )
        identity.set_custom_roles(restricted, [role])
    hidden = (
        client_for(org, restricted.user)
        .post("/api/v1/matching/search", {"job": str(job.pk)}, format="json")
        .json()["needs"]
    )
    assert (hidden["sen_tags"], hidden["gender"]) == ([], "")


def test_people_fields_are_cleaned_and_permission_guarded(org):
    from tutortrack.identity import services as identity
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory

    with tenant_context(org):
        tutor = TutorProfileFactory(organisation=org)
        student = StudentFactory(organisation=org, client=ClientFactory(organisation=org))
    admin = MembershipFactory(organisation=org, role="admin")
    api = client_for(org, admin.user)
    response = api.patch(
        f"/api/v1/tutors/{tutor.pk}",
        {"gender": "female", "sen_tags": [" Dyslexia ", "dyslexia", ""], "exam_boards": ["AQA"]},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert (response.json()["gender"], response.json()["sen_tags"]) == ("female", ["Dyslexia"])
    response = api.patch(
        f"/api/v1/students/{student.pk}",
        {"sen_tags": ["ADHD"], "tutor_gender_preference": "female"},
        format="json",
    )
    assert response.json()["sen_tags"] == ["ADHD"]
    limited = MembershipFactory(organisation=org, role="coordinator")
    with tenant_context(org):
        role = identity.create_custom_role(
            name="No sensitive",
            clone_from="coordinator",
            grants={"people.student.view_sensitive": "none", "people.tutor.view_sensitive": "none"},
        )
        identity.set_custom_roles(limited, [role])
    other = client_for(org, limited.user)
    assert "gender" not in other.get(f"/api/v1/tutors/{tutor.pk}").json()
    student_body = other.get(f"/api/v1/students/{student.pk}").json()
    assert "sen_tags" not in student_body
    assert "tutor_gender_preference" not in student_body
