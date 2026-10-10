"""Shared data for the reporting tests: a family, two tutors and a month of lessons."""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

import pytest
from django.db import transaction

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)


def snap(moment: Any) -> Any:
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


def make_lesson(
    org: Any,
    world: dict[str, Any],
    *,
    tutor: Any,
    hours_from_now: float,
    student: int = 0,
    minutes: int = 60,
) -> Any:
    from tutortrack.scheduling import services as scheduling

    start = snap(now() + timedelta(hours=hours_from_now))
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=world["service"],
            attendees=[{"student": world["students"][student]}],
            tutors=[{"tutor": tutor}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson


def complete(org: Any, lesson: Any) -> None:
    from tutortrack.billing import services as billing
    from tutortrack.delivery import services as delivery
    from tutortrack.payroll import services as payroll

    with tenant_context(org):
        delivery.complete_lesson(lesson)
        billing.sync_lesson_charges(lesson.pk)
        payroll.sync_lesson_pay(lesson.pk)


@pytest.fixture
def world(org: Any) -> dict[str, Any]:
    """Two completed lessons (Nia, Sam), one cancelled (Nia), one planned next week (Sam),
    a £30 cash payment and Nia's availability (Mon-Fri 15:00-20:00)."""
    from tutortrack.delivery import services as delivery
    from tutortrack.payments import services as payments
    from tutortrack.scheduling import services as scheduling

    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
    with tenant_context(org):
        client.billing_contact = contact
        client.save()
    students = [
        StudentFactory(
            organisation=org, client=client, first_name=n, last_name="Patel", status="active"
        )
        for n in ("Arjun", "Maya")
    ]
    nia_member = MembershipFactory(organisation=org, role="tutor")
    nia = TutorProfileFactory(
        organisation=org,
        status="active",
        first_name="Nia",
        last_name="Okafor",
        membership=nia_member,
    )
    sam = TutorProfileFactory(organisation=org, status="active", first_name="Sam", last_name="Lee")
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    world = {
        "client": client,
        "students": students,
        "nia": nia,
        "sam": sam,
        "service": service,
        "nia_user": nia_member.user,
    }
    done_nia = make_lesson(org, world, tutor=nia, hours_from_now=-3)
    done_sam = make_lesson(org, world, tutor=sam, hours_from_now=-5, student=1, minutes=90)
    cancelled = make_lesson(org, world, tutor=nia, hours_from_now=-26)
    planned = make_lesson(org, world, tutor=sam, hours_from_now=24 * 7)
    complete(org, done_nia)
    complete(org, done_sam)
    with tenant_context(org), transaction.atomic():
        delivery.cancel_lesson(cancelled, cancelled_by="admin", reason="Closure", notify=False)
        payments.record_manual_payment(client=client, amount=Money("30.00", "GBP"), method="cash")
        scheduling.set_availability(
            nia,
            windows=[
                {"weekday": d, "start_time": time(15), "end_time": time(20)} for d in range(5)
            ],
            effective_from=now().date() - timedelta(days=60),
            timezone="Europe/London",
        )
    world.update(done_nia=done_nia, done_sam=done_sam, cancelled=cancelled, planned=planned)
    from tutortrack.reporting import facts

    with tenant_context(org):
        facts.rebuild()
    return world


@pytest.fixture
def finance(org: Any) -> Any:
    return client_for(org, MembershipFactory(organisation=org, role="finance").user)


def window(org: Any) -> dict[str, str]:
    """A custom period covering the fixture's lessons."""
    from tutortrack.reporting.periods import org_today

    with tenant_context(org):
        today = org_today()
    return {
        "period": "custom",
        "from": (today - timedelta(days=10)).isoformat(),
        "to": (today + timedelta(days=10)).isoformat(),
    }
