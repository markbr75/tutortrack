"""Gap batch G4 for the tutor app: create and move lessons with conflict feedback
(FR-16-2), the previous report on the lesson page (FR-16-3) and a student's full lesson
history (FR-16-4)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.delivery.models import LessonReport
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.jobs import services as jobs
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

from .test_tutor import lesson, setup  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db
LONDON = ZoneInfo("Europe/London")


def at(days: int, hour: int = 10) -> datetime:
    day = now().astimezone(LONDON).date() + timedelta(days=days)
    return datetime.combine(day, time(hour), tzinfo=LONDON)


def toggle(org, key, value):
    with tenant_context(org):
        settings_service.update_settings("tutor_access", {f"tutor_access.{key}": value})


def test_me_says_what_the_tutor_may_plan(org, setup):  # noqa: F811
    me = setup["api"].get("/api/v1/tutor/me").json()
    assert (me["can_create_lessons"], me["can_reschedule"]) == (False, True)
    toggle(org, "create_lessons", True)
    toggle(org, "reschedule_lessons", False)
    me = setup["api"].get("/api/v1/tutor/me").json()
    assert (me["can_create_lessons"], me["can_reschedule"]) == (True, False)


def test_tutor_books_a_lesson_on_their_job(org, setup):  # noqa: F811
    s = setup
    jobs_out = s["api"].get("/api/v1/tutor/jobs").json()
    assert [j["id"] for j in jobs_out] == [str(s["job"].pk)]
    assert jobs_out[0]["students"][0]["name"] == s["student"].full_name
    body = {"job": str(s["job"].pk), "start": at(3).isoformat(), "end": at(3, 11).isoformat()}
    refused = s["api"].post("/api/v1/tutor/lessons", body, format="json")
    assert refused.status_code == 403  # the organisation hasn't allowed it
    toggle(org, "create_lessons", True)
    created = s["api"].post("/api/v1/tutor/lessons", body, format="json")
    assert created.status_code == 201, created.json()
    with tenant_context(org):
        made = Lesson.objects.get(pk=created.json()["lesson"]["id"])
        assert made.created_via == "tutor"
        assert [t.tutor_id for t in made.tutors.all()] == [s["tutor"].pk]
    other_client = ClientFactory(organisation=org)
    with tenant_context(org):
        other_job = jobs.create_job(
            client=other_client,
            service=s["service"],
            students=[{"student": StudentFactory(organisation=org, client=other_client)}],
            tutors=[{"tutor": s["other"]}],
            status="active",
        )
    theirs = s["api"].post(
        "/api/v1/tutor/lessons", {**body, "job": str(other_job.pk)}, format="json"
    )
    assert theirs.status_code == 404


def test_conflicts_are_shown_before_and_stop_the_booking(org, setup):  # noqa: F811
    s = setup
    toggle(org, "create_lessons", True)
    lesson_start = at(5)
    with tenant_context(org):
        from tutortrack.scheduling import services as scheduling

        scheduling.create_lesson(
            start=lesson_start,
            end=lesson_start + timedelta(hours=1),
            service=s["service"],
            job=s["job"],
            tutors=[{"tutor": s["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        )
    clash = {"job": str(s["job"].pk), "start": at(5).isoformat(), "end": at(5, 11).isoformat()}
    check = s["api"].post("/api/v1/tutor/lessons/check", clash, format="json")
    assert check.status_code == 200
    assert any(c["severity"] == "hard" for c in check.json())
    free = {**clash, "start": at(6).isoformat(), "end": at(6, 11).isoformat()}
    assert not [
        c
        for c in s["api"].post("/api/v1/tutor/lessons/check", free, format="json").json()
        if c["severity"] == "hard"
    ]
    refused = s["api"].post("/api/v1/tutor/lessons", clash, format="json")
    assert refused.status_code == 422
    assert refused.json()["conflicts"]


def test_tutor_moves_their_lesson_or_is_told_to_ask(org, setup):  # noqa: F811
    s = setup
    mine = lesson(org, s, hours=72)
    start = mine.start + timedelta(days=1)
    body = {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "reason": "Exam clash",
    }
    check = s["api"].post(
        "/api/v1/tutor/lessons/check", {**body, "lesson": str(mine.pk)}, format="json"
    )
    assert check.status_code == 200
    moved = s["api"].post(f"/api/v1/tutor/lessons/{mine.pk}/move", body, format="json")
    assert moved.status_code == 200, moved.json()
    with tenant_context(org):
        mine.refresh_from_db()
        assert mine.start == start
    theirs = lesson(org, s, hours=96, tutor=s["other"])
    assert (
        s["api"].post(f"/api/v1/tutor/lessons/{theirs.pk}/move", body, format="json").status_code
        == 404
    )
    toggle(org, "reschedule_lessons", False)
    refused = s["api"].post(f"/api/v1/tutor/lessons/{mine.pk}/move", body, format="json")
    assert refused.status_code == 403
    # ... so the app sends a request through the existing reschedule-request API.
    asked = s["api"].post(
        f"/api/v1/lessons/{mine.pk}/reschedule-requests",
        {"options": [{"start": body["start"], "end": body["end"]}], "reason": "Exam"},
        format="json",
    )
    assert asked.status_code in {201, 422}, asked.json()


def _written_report(org, s, lesson_obj, text):
    with tenant_context(org):
        delivery.complete_lesson(lesson_obj)
        report = delivery.open_report(lesson_obj, s["tutor"])
        key = next(
            f["key"]
            for f in report.template_version.fields
            if f.get("type") == "text" or f.get("type") == "textarea"
        )
        LessonReport.objects.filter(pk=report.pk).update(
            status="submitted", answers={key: text}, submitted_at=now()
        )
        return report


def test_lesson_page_shows_the_previous_report(org, setup):  # noqa: F811
    s = setup
    earlier = lesson(org, s, hours=-72)
    _written_report(org, s, earlier, "Fractions are secure; next: ratio.")
    upcoming = lesson(org, s, hours=24)
    out = s["api"].get(f"/api/v1/tutor/lessons/{upcoming.pk}/previous-report").json()
    assert out["report"]["lesson_id"] == str(earlier.pk)
    assert "Fractions are secure" in str(out["report"]["answers"])
    first = s["api"].get(f"/api/v1/tutor/lessons/{earlier.pk}/previous-report").json()
    assert first["report"] is None
    theirs = lesson(org, s, hours=30, tutor=s["other"])
    assert s["api"].get(f"/api/v1/tutor/lessons/{theirs.pk}/previous-report").status_code == 404


def test_student_lesson_history(org, setup):  # noqa: F811
    s = setup
    done = lesson(org, s, hours=-48)
    _written_report(org, s, done, "Good session")
    lesson(org, s, hours=48)
    lesson(org, s, hours=-24, tutor=s["other"])  # another tutor's: not shown
    out = s["api"].get(f"/api/v1/tutor/students/{s['student'].pk}/lessons").json()
    assert len(out["lessons"]) == 2
    assert out["lessons"][-1]["report_status"] == "submitted"
    assert out["attendance_percent"] == 100
    stranger = StudentFactory(organisation=org, client=ClientFactory(organisation=org))
    assert s["api"].get(f"/api/v1/tutor/students/{stranger.pk}/lessons").status_code == 404


class TestTutorJobsIsolation(TenantIsolationTestMixin):
    """The same person tutors for two organisations: each only shows its own jobs."""

    list_url = "/api/v1/tutor/jobs"

    def _tutor(self, organisation):
        if not hasattr(self, "_user"):
            self._user = UserFactory()
            self._tutors = {}
        if organisation.pk not in self._tutors:
            membership = MembershipFactory(organisation=organisation, user=self._user, role="tutor")
            self._tutors[organisation.pk] = TutorProfileFactory(
                organisation=organisation, status="active", membership=membership
            )
        return self._tutors[organisation.pk]

    def make_object(self, organisation):
        tutor = self._tutor(organisation)
        client = ClientFactory(organisation=organisation)
        student = StudentFactory(organisation=organisation, client=client)
        with tenant_context(organisation):
            job = jobs.create_job(
                client=client,
                service=ServiceFactory(organisation=organisation),
                students=[{"student": student}],
                tutors=[{"tutor": tutor}],
                status="active",
            )
        job.first_student = student
        return job

    def acting_user(self, organisation):
        self._tutor(organisation)
        return self._user

    def detail_url(self, obj):
        return f"/api/v1/tutor/students/{obj.first_student.pk}/lessons"

    def test_lesson_endpoints_of_another_organisation_are_404(self, org, other_org):
        self.make_object(org)
        theirs = self.make_object(other_org)
        with tenant_context(other_org):
            start = at(2)
            from tutortrack.scheduling import services as scheduling

            other_lesson = scheduling.create_lesson(
                start=start,
                end=start + timedelta(hours=1),
                job=theirs,
                timezone="Europe/London",
                override_conflicts=True,
            ).lesson
        api = client_for(org, self._user)
        assert (
            api.get(f"/api/v1/tutor/lessons/{other_lesson.pk}/previous-report").status_code == 404
        )
        body = {"start": at(3).isoformat(), "end": at(3, 11).isoformat()}
        assert (
            api.post(
                f"/api/v1/tutor/lessons/{other_lesson.pk}/move", body, format="json"
            ).status_code
            == 404
        )
