"""Shared fixtures for E21: an organisation with an admin, two tutors and two families;
tutor Nia teaches Arjun (a job and lessons), tutor Sam teaches nobody yet."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tutortrack.catalogue.tests.factories import ServiceFactory, SubjectFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.portal.tests.test_portal import make_household
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

LONDON = ZoneInfo("Europe/London")


def events_of(org: Any, kind: str) -> list[dict[str, Any]]:
    with tenant_context(org):
        return [
            e.payload for e in OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at")
        ]


def set_learning(org: Any, **values: Any) -> None:
    with tenant_context(org):
        settings_service.update_settings(
            "learning", {f"learning.{k}": v for k, v in values.items()}
        )


def at(days: int, hour: int = 10) -> datetime:
    """A fixed local time ``days`` from today (London)."""
    day = now().astimezone(LONDON).date() + timedelta(days=days)
    return datetime.combine(day, time(hour), tzinfo=LONDON)


def lesson_for(org: Any, world: dict[str, Any], start: datetime, students: list[Any], tutor=None):
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(hours=1),
            service=world["service"] if len(students) == 1 else world["group"],
            attendees=[{"student": s} for s in students],
            tutors=[{"tutor": tutor or world["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
        ).lesson


@pytest.fixture
def world(org):
    tutor_membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", membership=tutor_membership
    )
    other_membership = MembershipFactory(organisation=org, role="tutor")
    other = TutorProfileFactory(
        organisation=org, status="active", first_name="Sam", membership=other_membership
    )
    admin = MembershipFactory(organisation=org, role="admin")
    family = make_household(org, "The Patels")
    others = make_household(org, "The Smiths")
    maths = SubjectFactory(organisation=org, name="Maths")
    service = ServiceFactory(organisation=org, name="Maths 1:1", subject=maths)
    group = ServiceFactory(
        organisation=org, name="Maths group", subject=maths, format="small_group", max_students=6
    )
    student = family["students"][0]
    with tenant_context(org):
        job = jobs.create_job(
            client=family["client"],
            service=service,
            students=[{"student": student}],
            tutors=[{"tutor": tutor}],
            status="active",
        )
    return {
        "tutor": tutor,
        "tutor_user": tutor_membership.user,
        "tutor_api": client_for(org, tutor_membership.user),
        "other_tutor": other,
        "other_api": client_for(org, other_membership.user),
        "admin": admin.user,
        "admin_api": client_for(org, admin.user),
        "family": family,
        "others": others,
        "student": student,
        "sibling": family["students"][1],
        "stranger": others["students"][0],
        "subject": maths,
        "service": service,
        "group": group,
        "job": job,
    }
