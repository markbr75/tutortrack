"""E15-T09 (FR-15-5): families book a makeup lesson with a makeup credit in the portal."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.delivery.models import MakeupCredit
from tutortrack.portal.tests.test_portal import make_household
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.tests.test_phase2 import (  # noqa: F401  (the world fixture)
    enable_booking,
    first_slot,
    iso,
    world,
)

pytestmark = pytest.mark.django_db


def missed_lesson_credit(org, world):  # noqa: F811
    start = now().replace(second=0, microsecond=0) - timedelta(days=2)
    with tenant_context(org):
        lesson = scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=world["service"],
            attendees=[{"student": world["student"]}],
            tutors=[{"tutor": world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson
        attendee = lesson.attendees.get(student=world["student"])
        return delivery.issue_makeup_credit(lesson, attendee, days=30)


def test_a_makeup_lesson_is_free_and_uses_the_credit(org, world):  # noqa: F811
    enable_booking(org)
    credit = missed_lesson_credit(org, world)
    family_api = world["family"]["api"]
    assert family_api.get("/api/v1/portal/me").json()["features"]["makeups"] is True
    credits = family_api.get("/api/v1/portal/makeup-credits").json()
    assert [c["id"] for c in credits] == [str(credit.pk)]
    slot = first_slot(org, world)
    held = family_api.post(
        "/api/v1/portal/booking/holds",
        {
            "service": str(world["service"].pk),
            "start": iso(slot.start),
            "student": str(world["student"].pk),
            "makeup_credit": str(credit.pk),
        },
        format="json",
    )
    assert held.status_code == 201, held.json()
    assert held.json()["quote"]["amount"] == {"amount": "0.00", "currency": "GBP"}
    booked = family_api.post(f"/api/v1/portal/booking/holds/{held.json()['id']}/submit").json()
    assert booked["booking"]["status"] == "confirmed"
    assert booked["pay_url"] == ""
    with tenant_context(org):
        credit.refresh_from_db()
        assert str(credit.consumed_by_lesson_id) == booked["booking"]["lesson"]
    assert family_api.get("/api/v1/portal/makeup-credits").json() == []


def test_credits_of_other_households_and_used_credits_are_refused(org, world):  # noqa: F811
    enable_booking(org)
    credit = missed_lesson_credit(org, world)
    slot = first_slot(org, world)
    other = make_household(org, "The Smiths")
    assert other["api"].get("/api/v1/portal/makeup-credits").json() == []
    stolen = other["api"].post(
        "/api/v1/portal/booking/holds",
        {
            "service": str(world["service"].pk),
            "start": iso(slot.start),
            "student": str(other["students"][0].pk),
            "makeup_credit": str(credit.pk),
        },
        format="json",
    )
    assert stolen.status_code == 404
    with tenant_context(org):
        MakeupCredit.objects.filter(pk=credit.pk).update(voided_at=now())
    used = world["family"]["api"].post(
        "/api/v1/portal/booking/holds",
        {
            "service": str(world["service"].pk),
            "start": iso(slot.start),
            "student": str(world["student"].pk),
            "makeup_credit": str(credit.pk),
        },
        format="json",
    )
    assert used.status_code == 422
