"""E21-T02 homework: assign (from a lesson, report, class, job or standalone), submit
through the portal, review with grades and feedback, resubmission, reminders and
overdue (the workflow steps), completion stats (FR-21-2)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import StoredFile
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.learning import selectors, services
from tutortrack.learning.models import GradeScale, Homework, HomeworkAssignment

from .conftest import at, events_of, lesson_for, set_learning

pytestmark = pytest.mark.django_db

URL = "/api/v1/learning/homework"
PORTAL = "/api/v1/portal/learning/homework"


def assign(org, world, *, students=None, due=None, **kw):
    with tenant_context(org):
        return services.assign_homework(
            title=kw.pop("title", "Fractions worksheet"),
            due_at=due or at(3, 18),
            students=students if students is not None else [world["student"]],
            set_by=world["tutor"],
            **kw,
        )


def assignment_of(org, homework, student):
    with tenant_context(org):
        return HomeworkAssignment.objects.get(homework=homework, student=student)


def test_tutor_sets_homework_for_their_student(org, world):
    response = world["tutor_api"].post(
        URL,
        {
            "title": "Fractions worksheet",
            "instructions": "Q1-10",
            "due_at": at(3, 18).isoformat(),
            "students": [str(world["student"].pk)],
            "submission_type": "text",
            "expected_minutes": 30,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["set_by"] == str(world["tutor"].pk)
    assert body["counts"]["total"] == 1
    assigned = events_of(org, "homework.assigned")
    assert [e["data"]["student_id"] for e in assigned] == [str(world["student"].pk)]
    assert assigned[0]["data"]["round"] == 1
    stranger = world["tutor_api"].post(
        URL,
        {"title": "x", "due_at": at(3).isoformat(), "students": [str(world["stranger"].pk)]},
        format="json",
    )
    assert stranger.status_code == 403
    past = world["admin_api"].post(
        URL,
        {"title": "x", "due_at": at(-1).isoformat(), "students": [str(world["student"].pk)]},
        format="json",
    )
    assert past.status_code == 422


def test_homework_for_a_job_or_lesson_goes_to_its_students(org, world):
    lesson = lesson_for(org, world, at(1), [world["student"], world["sibling"]])
    by_lesson = assign(org, world, students=[], lesson=lesson)
    by_job = assign(org, world, students=[], job=world["job"])
    with tenant_context(org):
        assert by_lesson.assignments.count() == 2
        assert list(by_job.assignments.values_list("student_id", flat=True)) == [
            world["student"].pk
        ]


def test_family_hands_in_and_tutor_hears_about_it(org, world):
    homework = assign(org, world)
    assignment = assignment_of(org, homework, world["student"])
    family = world["family"]["api"]
    listed = family.get(PORTAL, {"open": "true"}).json()
    assert [h["title"] for h in listed] == ["Fractions worksheet"]
    assert listed[0]["can_submit"] is True
    empty = family.post(f"{PORTAL}/{assignment.pk}/submit", {"body": ""}, format="json")
    assert empty.status_code == 422
    done = family.post(f"{PORTAL}/{assignment.pk}/submit", {"body": "1/2, 3/4"}, format="json")
    assert done.status_code == 201, done.content
    assert done.json()["status"] == "submitted"
    assert done.json()["submissions"][0]["body"] == "1/2, 3/4"
    assert events_of(org, "homework.submitted")[0]["data"]["is_late"] is False
    dispatch_batch()
    with tenant_context(org):
        assert Message.objects.filter(type_key="homework_submitted").exists()
        assert Message.objects.filter(type_key="homework_assigned").exists()
    again = family.post(f"{PORTAL}/{assignment.pk}/submit", {"body": "again"}, format="json")
    assert again.status_code == 409
    other = world["others"]["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"body": "x"}, format="json"
    )
    assert other.status_code == 404


def test_file_and_link_submissions(org, world):
    homework = assign(org, world, submission_type="file")
    assignment = assignment_of(org, homework, world["student"])
    family = world["family"]
    with tenant_context(org):
        mine = StoredFile.objects.create(
            filename="work.pdf",
            content_type="application/pdf",
            size_bytes=10,
            storage_key=f"org/{org.pk}/hw/work.pdf",
            status="uploaded",
            scan_status="clean",
            uploaded_by=family["user"],
        )
        theirs = StoredFile.objects.create(
            filename="x.pdf",
            content_type="application/pdf",
            size_bytes=10,
            storage_key=f"org/{org.pk}/hw/x.pdf",
            status="uploaded",
            scan_status="clean",
            uploaded_by=world["admin"],
        )
    no_file = family["api"].post(f"{PORTAL}/{assignment.pk}/submit", {}, format="json")
    assert no_file.status_code == 422
    sneaky = family["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"files": [str(theirs.pk)]}, format="json"
    )
    assert sneaky.status_code == 403
    ok = family["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"files": [str(mine.pk)]}, format="json"
    )
    assert ok.status_code == 201, ok.content
    assert ok.json()["submissions"][0]["files"][0]["filename"] == "work.pdf"
    # The tutor can open the submitted file (access rule on the submission).
    opened = world["tutor_api"].get(f"/api/v1/files/{mine.pk}")
    assert opened.status_code == 200


def test_late_work_is_marked_late_or_refused(org, world):
    homework = assign(org, world)
    assignment = assignment_of(org, homework, world["student"])
    with tenant_context(org):
        HomeworkAssignment.objects.filter(pk=assignment.pk).update(
            due_at=now() - timedelta(hours=1)
        )
    set_learning(org, late_submissions=False)
    refused = world["family"]["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"body": "x"}, format="json"
    )
    assert refused.status_code == 409
    set_learning(org, late_submissions=True)
    late = world["family"]["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"body": "x"}, format="json"
    )
    assert late.json()["is_late"] is True


def test_review_grades_on_the_homework_scale(org, world):
    with tenant_context(org):
        services.ensure_default_scales()
        letters = GradeScale.objects.get(kind="letter")
    homework = assign(org, world, grade_scale=letters)
    assignment = assignment_of(org, homework, world["student"])
    with tenant_context(org):
        services.submit_homework(assignment, body="done")
    url = f"/api/v1/learning/homework-assignments/{assignment.pk}/review"
    bad = world["tutor_api"].post(url, {"outcome": "complete", "grade": "Z"}, format="json")
    assert bad.status_code == 422
    good = world["tutor_api"].post(
        url, {"outcome": "complete", "grade": "A", "feedback": "Lovely"}, format="json"
    )
    assert good.status_code == 200, good.content
    assert (good.json()["status"], good.json()["grade"]) == ("completed", "A")
    graded = events_of(org, "homework.graded")
    assert graded[0]["data"]["grade"] == "A"
    portal = world["family"]["api"].get(f"{PORTAL}/{assignment.pk}").json()
    assert (portal["grade"], portal["feedback"]) == ("A", "Lovely")
    others = world["other_api"].post(url, {"outcome": "complete"}, format="json")
    assert others.status_code == 404  # not their student


def test_percentage_grades_record_the_score(org, world):
    homework = assign(org, world)  # default scale: percentage
    assignment = assignment_of(org, homework, world["student"])
    with tenant_context(org):
        services.submit_homework(assignment, body="done")
        done = services.review_homework(assignment, outcome="complete", grade="72.5")
        assert (done.grade, str(done.score_percent)) == ("72.5%", "72.50")
        with pytest.raises(Exception, match="0 to 100"):
            other = assign(org, world, students=[world["sibling"]])
            row = HomeworkAssignment.objects.get(homework=other)
            services.review_homework(row, outcome="complete", grade="120")


def test_returned_work_starts_a_new_round(org, world):
    homework = assign(org, world)
    assignment = assignment_of(org, homework, world["student"])
    with tenant_context(org):
        services.submit_homework(assignment, body="first try")
    new_due = at(5, 18)
    response = world["tutor_api"].post(
        f"/api/v1/learning/homework-assignments/{assignment.pk}/review",
        {"outcome": "resubmit", "feedback": "Show working", "due_at": new_due.isoformat()},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert (response.json()["status"], response.json()["round"]) == ("returned", 2)
    returned = events_of(org, "homework.returned")[0]["data"]
    assert returned["round"] == 2
    second = world["family"]["api"].post(
        f"{PORTAL}/{assignment.pk}/submit", {"body": "second try"}, format="json"
    )
    assert [s["attempt"] for s in second.json()["submissions"]] == [1, 2]


def test_stats_show_completion(org, world):
    first = assign(org, world, title="One")
    second = assign(org, world, title="Two")
    third = assign(org, world, title="Three")
    with tenant_context(org):
        HomeworkAssignment.objects.filter(homework__in=[first, second]).update(
            due_at=now() - timedelta(days=1)
        )
        services.submit_homework(assignment_of(org, first, world["student"]), body="x")
        services.excuse_homework(assignment_of(org, third, world["student"]))
    stats = (
        world["admin_api"]
        .get("/api/v1/learning/homework-assignments/stats", {"student": str(world["student"].pk)})
        .json()
    )
    assert stats["total"] == 2  # the excused one doesn't count
    assert (stats["due"], stats["overdue"], stats["late"]) == (2, 1, 1)
    assert stats["completion_rate"] == "50.0"


def test_reminder_and_overdue_steps_happen_once(org, world):
    set_learning(org, homework_reminder_hours=24)
    homework = assign(org, world, due=now() + timedelta(days=3))
    assignment = assignment_of(org, homework, world["student"])
    with tenant_context(org):
        state = services.assignment_state(assignment.pk)
        assert state["open"]
        assert state["remind"]
        assert services.send_homework_reminder(assignment.pk) is True
        assert services.send_homework_reminder(assignment.pk) is False
        assert services.assignment_state(assignment.pk)["remind"] is False
        assert Message.objects.filter(type_key="homework_reminder").exists()
        assert services.mark_homework_overdue(assignment.pk) == "overdue"
        assert services.mark_homework_overdue(assignment.pk) == "overdue"
    assert len(events_of(org, "homework.overdue")) == 1
    late_set = assign(org, world, title="Due soon", due=now() + timedelta(hours=2))
    with tenant_context(org):
        row = HomeworkAssignment.objects.get(homework=late_set)
        assert services.assignment_state(row.pk)["remind"] is False  # set inside the window


def test_cancelling_closes_open_assignments(org, world):
    homework = assign(org, world, students=[world["student"], world["sibling"]])
    with tenant_context(org):
        services.submit_homework(assignment_of(org, homework, world["sibling"]), body="x")
        services.review_homework(
            assignment_of(org, homework, world["sibling"]), outcome="complete", grade="50"
        )
    response = world["admin_api"].post(f"{URL}/{homework.pk}/cancel")
    assert response.json()["status"] == "cancelled"
    with tenant_context(org):
        statuses = dict(homework.assignments.values_list("student_id", "status"))
    assert statuses[world["student"].pk] == "cancelled"
    assert statuses[world["sibling"].pk] == "completed"
    assert events_of(org, "homework.cancelled")[0]["data"]["assignments"] == 1


def test_changing_the_due_date_moves_open_assignments(org, world):
    homework = assign(org, world)
    later = at(6, 18)
    response = world["tutor_api"].patch(
        f"{URL}/{homework.pk}", {"due_at": later.isoformat()}, format="json"
    )
    assert response.status_code == 200, response.content
    assert assignment_of(org, homework, world["student"]).due_at == later


def test_homework_written_in_a_lesson_report_is_set(org, world):
    lesson = lesson_for(org, world, at(-1), [world["student"]])
    with tenant_context(org):
        report = delivery.open_report(lesson, world["tutor"])
        delivery.submit_report(
            report, answers={"covered": "Fractions", "homework": "Exercise 4B, all questions"}
        )
    dispatch_batch()  # lesson_report.submitted → learning
    with tenant_context(org):
        homework = Homework.objects.get(lesson_report=report)
        assert homework.instructions == "Exercise 4B, all questions"
        assert homework.set_by == world["tutor"]
        assert list(homework.assignments.values_list("student_id", flat=True)) == [
            world["student"].pk
        ]
        assert services.homework_from_report(report.pk) is None  # once per report


def test_tutor_sees_only_their_students_homework(org, world):
    mine = assign(org, world)
    with tenant_context(org):
        theirs = services.assign_homework(title="Other", due_at=at(3), students=[world["stranger"]])
    ids = {h["id"] for h in world["tutor_api"].get(URL).json()["results"]}
    assert ids == {str(mine.pk)}
    assert world["tutor_api"].get(f"{URL}/{theirs.pk}").status_code == 404
    with tenant_context(org):
        assert selectors.homework(world["admin"]).count() == 2
