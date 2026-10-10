"""Shared setup for E22 calendar/meeting tests: a tutor who signs in, a family, a service."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import oauth
from tutortrack.integrations import services as integrations
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import services as scheduling

LONDON = ZoneInfo("Europe/London")


@pytest.fixture
def people(org) -> dict[str, Any]:
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor = TutorProfileFactory(
            organisation=org, status="active", membership=membership, first_name="Nia",
            last_name="Adeyemi",
        )  # fmt: skip
        client = ClientFactory(organisation=org)
        student = StudentFactory(
            organisation=org, client=client, first_name="Arjun", last_name="Patel"
        )
        service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {
        "membership": membership,
        "user": membership.user,
        "tutor": tutor,
        "client": client,
        "student": student,
        "service": service,
    }


def slot(days: int = 3, hour: int = 16) -> datetime:
    day = (now() + timedelta(days=days)).astimezone(LONDON).date()
    return datetime.combine(day, time(hour), tzinfo=LONDON)


def make_lesson(org, people, start: datetime | None = None, minutes: int = 60, **fields):
    start = start or slot()
    with tenant_context(org), transaction.atomic():
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=people["service"],
            attendees=[{"student": people["student"]}],
            tutors=[{"tutor": people["tutor"]}],
            timezone="Europe/London",
            **fields,
        ).lesson


def connect(org, user, provider: str = "google", who: str = "nia"):
    with tenant_context(org):
        if provider == "caldav":
            return integrations.connect_with_credentials(
                user, provider="caldav", level="user", username=f"{who}@icloud.com",
                password="app-pass",
            )  # fmt: skip
        token, _state = oauth.make_state(
            organisation_id=org.pk, user_id=user.pk, provider=provider, level="user",
            next_path="/",
        )  # fmt: skip
        return integrations.complete_oauth(user, code=f"fake-{provider}-{who}", state=token)


def settle(org) -> None:
    """Mark pending events dispatched (tests that don't run Temporal)."""
    with tenant_context(org):
        OutboxEvent.objects.filter(dispatched_at__isnull=True).update(dispatched_at=now())


def today() -> date:
    return now().astimezone(LONDON).date()
