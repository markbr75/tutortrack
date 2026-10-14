"""Fake TutorCruncher, Teachworks and Google Sheets accounts (dev and tests, no keys).

They answer in the providers' own JSON shapes, so the real mapping code runs. Tests (or
a developer) replace an account's data with ``set_dataset(provider, {...})``; otherwise a
small sample agency is served: two families, three students, two tutors, a weekly job
with past and future appointments, invoices and a balance.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.cache import cache

from tutortrack.integrations.providers import AuthError, Credentials

KEY = "migration:fake:{provider}"
TIMEOUT = 60 * 60 * 24


def set_dataset(provider: str, data: dict[str, list[dict[str, Any]]]) -> None:
    cache.set(KEY.format(provider=provider), data, TIMEOUT)


def dataset(provider: str) -> dict[str, list[dict[str, Any]]]:
    data: dict[str, list[dict[str, Any]]] | None = cache.get(KEY.format(provider=provider))
    if data is None:
        data = SAMPLES[provider]()
        set_dataset(provider, data)
    return data


def _check(credentials: Credentials) -> None:
    if not credentials.secret or "wrong" in credentials.secret:
        raise AuthError("Those details weren't accepted.")


class FakeApi:
    def __init__(self, provider: str) -> None:
        self.provider = provider

    def list(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]:
        _check(credentials)
        yield from dataset(self.provider).get(resource, [])

    def detail(self, credentials: Credentials, resource: str, pk: Any) -> dict[str, Any]:
        _check(credentials)
        for item in dataset(self.provider).get(resource, []):
            if str(item.get("id")) == str(pk):
                return item
        raise AuthError("Not found.")


def _weekly(start: datetime, weeks: int, hours: int = 1) -> list[tuple[datetime, datetime]]:
    return [
        (start + timedelta(weeks=i), start + timedelta(weeks=i, hours=hours)) for i in range(weeks)
    ]


def tutorcruncher_sample() -> dict[str, list[dict[str, Any]]]:
    today = datetime.now(UTC).replace(hour=16, minute=0, second=0, microsecond=0)
    first = today - timedelta(weeks=2)
    appointments = []
    for index, (start, finish) in enumerate(_weekly(first, 6)):
        appointments.append(
            {
                "id": 9000 + index,
                "start": start.isoformat(),
                "finish": finish.isoformat(),
                "topic": "GCSE Maths",
                "status": "complete" if start < today else "planned",
                "service": {"id": 300},
                "rcras": [{"recipient": 201, "charge_rate": "45.00"}],
                "cjas": [{"contractor": 101, "pay_rate": "25.00"}],
            }
        )
    return {
        "clients": [
            {
                "id": 11,
                "status": "live",
                "balance": "-90.00",
                "user": {
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "email": "jane.smith@example.com",
                    "phone": "07700 900001",
                    "street": "1 High St",
                    "town": "London",
                    "postcode": "SW1A 1AA",
                    "country": "United Kingdom",
                },
                "labels": [{"name": "VIP"}],
            },
            {
                "id": 12,
                "status": "prospect",
                "balance": "30.00",
                "agent": {"id": 1},
                "user": {
                    "first_name": "Omar",
                    "last_name": "Khan",
                    "email": "omar.khan@example.com",
                },
            },
        ],
        "recipients": [
            {
                "id": 201,
                "user": {"first_name": "Tom", "last_name": "Smith"},
                "paying_client": {"id": 11},
                "academic_year": {"name": "Year 10"},
            },
            {
                "id": 202,
                "user": {"first_name": "Lily", "last_name": "Smith"},
                "paying_client": {"id": 11},
            },
            {
                "id": 203,
                "user": {"first_name": "Zara", "last_name": "Khan"},
                "paying_client": {"id": 12},
                "date_of_birth": "2012-05-01",
            },
        ],
        "contractors": [
            {
                "id": 101,
                "status": "approved",
                "user": {
                    "first_name": "Alex",
                    "last_name": "Jones",
                    "email": "alex.jones@example.com",
                    "mobile": "07700 900100",
                },
                "skills": [{"subject": "Maths", "qual_level": "GCSE"}],
            },
            {
                "id": 102,
                "status": "pending",
                "user": {"first_name": "Priya", "last_name": "Patel", "email": "priya@example.com"},
            },
        ],
        "services": [
            {
                "id": 300,
                "name": "GCSE Maths for Tom",
                "status": "in-progress",
                "dft_charge_rate": "45.00",
                "dft_contractor_rate": "25.00",
                "rcrs": [{"recipient": 201, "paying_client": 11}],
                "conjobs": [{"contractor": 101, "pay_rate": "25.00"}],
            },
        ],
        "appointments": appointments,
        "invoices": [
            {
                "id": 501,
                "display_id": "INV-501",
                "client": {"id": 11},
                "date_sent": (today - timedelta(days=20)).date().isoformat(),
                "gross": "90.00",
                "tax": "0.00",
                "status": "paid",
            },
            {
                "id": 502,
                "display_id": "INV-502",
                "client": {"id": 11},
                "date_sent": (today - timedelta(days=6)).date().isoformat(),
                "gross": "90.00",
                "tax": "0.00",
                "status": "unpaid",
            },
        ],
        "agents": [
            {
                "id": 1,
                "commission_rate": "10.00",
                "user": {
                    "first_name": "Sam",
                    "last_name": "Agent",
                    "email": "sam.agent@example.com",
                },
            }
        ],
        "reviews": [
            {
                "id": 801,
                "client": {"id": 11},
                "contractor": {"id": 101},
                "rating": 5,
                "review": "Alex is brilliant.",
                "public": True,
            }
        ],
        "proformas": [
            {"id": 601, "client": {"id": 12}, "gross": "120.00", "status": "unpaid"},
            {"id": 602, "client": {"id": 11}, "gross": "60.00", "status": "paid"},
        ],
        "adhoccharges": [
            {
                "id": 701,
                "client": {"id": 11},
                "description": "Exam entry fee",
                "charge_client": "45.00",
                "date": (today + timedelta(days=3)).date().isoformat(),
            },
            {
                "id": 702,
                "client": {"id": 11},
                "description": "Old workbook",
                "charge_client": "10.00",
                "date": (today - timedelta(days=30)).date().isoformat(),
            },
        ],
    }


def teachworks_sample() -> dict[str, list[dict[str, Any]]]:
    today = datetime.now(UTC).replace(hour=17, minute=0, second=0, microsecond=0)
    lessons = []
    for index, (start, _finish) in enumerate(_weekly(today + timedelta(days=1), 4)):
        lessons.append(
            {
                "id": 7000 + index,
                "date": start.date().isoformat(),
                "from_time": "17:00",
                "to_time": "18:00",
                "service_id": 31,
                "employee_id": 21,
                "participants": [{"student_id": 41}],
                "status": "Scheduled",
            }
        )
    return {
        "customers": [
            {
                "id": 1,
                "first_name": "Maria",
                "last_name": "Garcia",
                "email": "maria@example.com",
                "mobile_phone": "555-0100",
                "city": "Austin",
                "state": "TX",
                "zip": "73301",
                "country": "US",
                "status": "Active",
            },
        ],
        "students": [
            {
                "id": 41,
                "first_name": "Leo",
                "last_name": "Garcia",
                "customer_id": 1,
                "grade": "8",
                "status": "Active",
            },
        ],
        "wage_tiers": [{"id": 5, "name": "Senior", "wage": "30.00"}],
        "employees": [
            {
                "id": 21,
                "first_name": "Sam",
                "last_name": "Lee",
                "email": "sam.lee@example.com",
                "status": "Active",
                "wage_tier_id": 5,
            },
        ],
        "services": [
            {"id": 31, "name": "Algebra 1:1", "cost": "60.00", "wage": "30.00", "duration": 60},
        ],
        "lessons": lessons,
        "invoices": [
            {
                "id": 61,
                "number": "TW-1001",
                "customer_id": 1,
                "date": (today - timedelta(days=10)).date().isoformat(),
                "total": "120.00",
                "paid": "60.00",
                "status": "Partial",
            },
        ],
        "payments": [],
        "packages": [
            {
                "id": 81,
                "customer_id": 1,
                "name": "5 lesson bundle",
                "remaining_value": "120.00",
                "remaining_hours": "2",
            },
        ],
    }


def sheet_sample() -> dict[str, Any]:
    return {
        "values": [
            ["First name", "Last name", "Parent email", "Year group"],
            ["Ava", "Brown", "kate.brown@example.com", "Year 7"],
            ["Noah", "Brown", "kate.brown@example.com", "Year 5"],
        ],
        "title": [{"name": "Students"}],
    }


SAMPLES: dict[str, Any] = {
    "tutorcruncher": tutorcruncher_sample,
    "teachworks": teachworks_sample,
    "google_sheets": sheet_sample,
}


def fake_tutorcruncher() -> Any:
    from .tutorcruncher import TutorCruncherSource

    return TutorCruncherSource(FakeApi("tutorcruncher"))


def fake_teachworks() -> Any:
    from .teachworks import TeachworksSource

    return TeachworksSource(FakeApi("teachworks"))
