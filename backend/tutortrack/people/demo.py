"""In-product sample data (FR-02-6, FR-27-6): three families, four students and two tutors.

Names are fictitious, addresses use ``example.com``, and ``crm.demo`` tags the records
"Sample data". Nothing is ever sent to them (``core.demo_mode``)."""

from __future__ import annotations

import contextlib
from datetime import date
from typing import Any

from tutortrack.tenancy.demo import DemoContext, demo_provider


def _born(years_ago: int, month: int, day: int) -> date:
    from tutortrack.core.time import now

    return date(now().year - years_ago, month, day)


def families() -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    return [
        (
            {
                "first_name": "Priya",
                "last_name": "Patel",
                "mobile": "+447700900101",
                "email": "priya.patel.sample@example.com",
            },
            [
                {
                    "first_name": "Arjun",
                    "year_group": "Year 10",
                    "date_of_birth": _born(15, 3, 14),
                    "subjects": [{"subject": "Maths", "level": "GCSE"}],
                },
                {
                    "first_name": "Maya",
                    "year_group": "Year 7",
                    "date_of_birth": _born(12, 9, 2),
                    "subjects": [{"subject": "English"}],
                },
            ],
        ),
        (
            {
                "first_name": "Tom",
                "last_name": "Okafor",
                "mobile": "+447700900102",
                "email": "tom.okafor.sample@example.com",
            },
            [
                {
                    "first_name": "Ada",
                    "year_group": "Year 12",
                    "date_of_birth": _born(17, 1, 21),
                    "subjects": [{"subject": "Physics", "level": "A level"}],
                },
            ],
        ),
        (
            {
                "first_name": "Grace",
                "last_name": "Hughes",
                "relationship": "self",
                "email": "grace.hughes.sample@example.com",
            },
            [],
        ),
    ]


TUTORS = [
    ("nia.adeyemi.sample@example.com", "Nia", "Adeyemi", [{"subject": "Maths", "level": "GCSE"}]),
    (
        "sam.clarke.sample@example.com",
        "Sam",
        "Clarke",
        [{"subject": "Physics", "level": "A level"}],
    ),
]


@demo_provider(order=50)
def sample_people(ctx: DemoContext) -> None:
    from tutortrack.core.exceptions import BusinessRuleViolation

    from . import services
    from .models import TutorProfile

    clients: dict[str, Any] = {}
    students: dict[str, Any] = {}
    tutors: dict[str, Any] = {}
    for contact, kids in families():
        client, _contact, created = services.quick_add_family(contact=contact, students=kids)
        clients[contact["last_name"]] = client
        for student in created:
            students[student.first_name] = student
    for email, first, last, subjects in TUTORS:
        tutor = TutorProfile.objects.filter(email=email).first()
        if tutor is None:
            tutor = services.create_tutor(
                email=email, first_name=first, last_name=last, invite=False
            )
            services.set_tutor_subjects(tutor, subjects)
        if tutor.status != TutorProfile.Status.ACTIVE:
            # The plan's tutor limit may stop this: they stay onboarding.
            with contextlib.suppress(BusinessRuleViolation):
                services.change_tutor_status(tutor, TutorProfile.Status.ACTIVE)
        tutors[first] = tutor
    ctx.extras.update(clients=clients, students=students, tutors=tutors)
