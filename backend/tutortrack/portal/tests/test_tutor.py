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
    return tutor_setup(org)


def tutor_setup(org, user=None):
    membership = MembershipFactory(
        organisation=org, role="tutor", **({"user": user} if user else {})
    )
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
            "student": student, "service": service, "job": job,
            "user": membership.user}  # fmt: skip


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


def test_unmarked_lessons_counts_earlier_days_for_this_tutor_only(org, other_org, setup):
    """Follow-up to "The Register": the Today pill counts every lesson still to mark (ended,
    still planned) in the last 60 days, not only today's."""
    from tutortrack.portal.tutor import UNMARKED_LOOKBACK_DAYS

    s = setup
    lesson(org, s, hours=-3)  # ended today (or late last night), still planned
    lesson(org, s, hours=-24 * 5)  # five days ago, still planned
    marked = lesson(org, s, hours=-24 * 2)
    with tenant_context(org):
        delivery.complete_lesson(marked)
    lesson(org, s, hours=-24 * (UNMARKED_LOOKBACK_DAYS + 2))  # past the bound
    lesson(org, s, hours=-24 * 3, tutor=s["other"])  # someone else's
    lesson(org, s, hours=2)  # not over yet
    # The same person tutors for another organisation: those lessons never count here.
    elsewhere = tutor_setup(other_org, user=s["user"])
    lesson(other_org, elsewhere, hours=-24)

    today = s["api"].get("/api/v1/tutor/today").json()
    assert today["unmarked_lessons"] == 2
    assert (
        client_for(other_org, s["user"]).get("/api/v1/tutor/today").json()["unmarked_lessons"] == 1
    )
