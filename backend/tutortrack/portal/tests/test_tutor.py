"""E16: tutor portal endpoints (today, students, earnings), and tutors reach their own
lessons through the existing APIs only."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import services as scheduling

pytestmark = pytest.mark.django_db


def snap(moment):
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


@pytest.fixture
def setup(org):
    membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", membership=membership
    )
    other = TutorProfileFactory(organisation=org, status="active")
    client = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=client, first_name="Arjun")
    service = ServiceFactory(organisation=org, name="Maths 1:1")  # £40/h charge, £25/h pay
    with tenant_context(org):
        job = jobs.create_job(
            client=client, service=service, students=[{"student": student}],
            tutors=[{"tutor": tutor}], status="active",
        )  # fmt: skip
    return {"api": client_for(org, membership.user), "tutor": tutor, "other": other,
            "student": student, "service": service, "job": job}  # fmt: skip


def lesson(org, s, *, hours, tutor=None):
    start = snap(now() + timedelta(hours=hours))
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=s["service"], job=s["job"],
            attendees=[{"student": s["student"]}], tutors=[{"tutor": tutor or s["tutor"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


def test_today_students_and_earnings(org, setup):
    s = setup
    done = lesson(org, s, hours=-3)
    with tenant_context(org):
        delivery.complete_lesson(done)
    lesson(org, s, hours=48)
    lesson(org, s, hours=-5, tutor=s["other"])  # someone else's
    me = s["api"].get("/api/v1/tutor/me").json()
    assert (me["id"], me["can_see_pay"]) == (str(s["tutor"].pk), True)
    today = s["api"].get("/api/v1/tutor/today").json()
    assert today["reports_due"] == 1
    assert today["earnings_this_month"]["amount"] in {"25.00", "0.00"}  # 0 just after the 1st
    students = s["api"].get("/api/v1/tutor/students").json()
    assert [st["name"] for st in students] == [s["student"].full_name]
    assert students[0]["next_lesson"] is not None
    start = (now() - timedelta(days=2)).date()
    earnings = s["api"].get(f"/api/v1/tutor/earnings?from={start}").json()
    assert [row["lesson"] for row in earnings["lessons"]] == [str(done.pk)]
    assert earnings["total"] == {"amount": "25.00", "currency": "GBP"}


def test_tutors_only_reach_their_own_lessons(org, setup):
    s = setup
    theirs = lesson(org, s, hours=-5, tutor=s["other"])
    assert s["api"].get(f"/api/v1/lessons/{theirs.pk}").status_code == 404
    assert s["api"].post(f"/api/v1/lessons/{theirs.pk}/complete").status_code == 404
    mine = lesson(org, s, hours=-3)
    assert s["api"].post(f"/api/v1/lessons/{mine.pk}/complete").json()["status"] == "completed"


def test_staff_without_a_tutor_profile_are_refused(org):
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    assert admin.get("/api/v1/tutor/today").status_code == 403
    family = client_for(org, MembershipFactory(organisation=org, role="client").user)
    assert family.get("/api/v1/tutor/today").status_code == 403
