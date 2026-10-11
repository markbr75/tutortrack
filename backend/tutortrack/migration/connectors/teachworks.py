"""Teachworks REST API connector (FR-28-5).

``https://api.teachworks.com/v1/<resource>`` with ``Authorization: Token token=<key>``,
paged with ``page``/``per_page`` until a short page. Customers → clients and contacts,
students, employees → tutors (pay rate from their wage tier), services, lessons,
invoices, payments and packages (remaining value as client credit).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from tutortrack.integrations.providers import AccountInfo, AuthError, Credentials

from .base import joined, text

API = "https://api.teachworks.com/v1"
PER_PAGE = 100
ENTITIES = (
    "clients",
    "students",
    "tutors",
    "services",
    "lessons",
    "invoices",
    "payments",
    "packages",
)
CUSTOMER_STATUS = {"active": "active", "inactive": "dormant", "prospective": "prospect"}
STUDENT_STATUS = {
    "active": "active",
    "inactive": "finished",
    "prospective": "lead",
    "waiting": "waiting",
    "trial": "trial",
}
EMPLOYEE_STATUS = {"active": "active", "inactive": "inactive"}
LESSON_STATUS = {
    "scheduled": "planned",
    "attended": "completed",
    "missed": "missed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}
INVOICE_STATUS = {
    "paid": "paid",
    "unpaid": "issued",
    "partial": "partially_paid",
    "partially paid": "partially_paid",
    "void": "void",
    "draft": "issued",
}
METHODS = {
    "cash": "cash",
    "check": "cheque",
    "cheque": "cheque",
    "credit card": "other",
    "bank transfer": "bank_transfer",
    "ach": "bank_transfer",
    "e-transfer": "bank_transfer",
}


class Api(Protocol):
    def list(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]: ...


class HttpApi:
    def list(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]:
        from tutortrack.integrations.providers import http

        page = 1
        while page < 10_000:
            body = http.request(
                "GET",
                f"{API}/{resource}",
                auth_header=f"Token token={credentials.secret}",
                params={"page": page, "per_page": PER_PAGE},
                provider="teachworks",
            ).json()
            items = body if isinstance(body, list) else body.get(resource) or []
            yield from items
            if len(items) < PER_PAGE:
                return
            page += 1


def _money(value: Any) -> str:
    try:
        return str(Decimal(str(value))) if value not in (None, "") else ""
    except InvalidOperation:
        return ""


def _status(table: dict[str, str], value: Any, default: str) -> str:
    return table.get(text(value).lower(), default)


class TeachworksSource:
    provider = "teachworks"

    def __init__(self, api: Api | None = None) -> None:
        self.api: Api = api or HttpApi()
        self.timezone = "UTC"

    def supports(self, entity: str) -> bool:
        return entity in ENTITIES

    def verify(self, credentials: Credentials) -> AccountInfo:
        if not credentials.secret:
            raise AuthError("Enter your Teachworks API key.")
        next(iter(self.api.list(credentials, "customers")), None)
        return AccountInfo(f"teachworks:{credentials.secret[-6:]}", "Teachworks")

    def fetch(
        self, credentials: Credentials, entity: str, *, cutover: date
    ) -> Iterator[dict[str, Any]]:
        if entity == "clients":
            for c in self.api.list(credentials, "customers"):
                yield {
                    "external_id": c.get("id"),
                    "first_name": text(c.get("first_name")),
                    "last_name": text(c.get("last_name")),
                    "email": text(c.get("email")),
                    "phone": text(c.get("home_phone")),
                    "mobile": text(c.get("mobile_phone")),
                    "address_line1": text(c.get("address")),
                    "address_city": text(c.get("city")),
                    "address_region": text(c.get("state")),
                    "address_postcode": text(c.get("zip")),
                    "address_country": text(c.get("country")),
                    "status": _status(CUSTOMER_STATUS, c.get("status"), "active"),
                    "client_type": "individual" if c.get("type") == "independent" else "household",
                }
        elif entity == "students":
            for s in self.api.list(credentials, "students"):
                yield {
                    "external_id": s.get("id"),
                    "first_name": text(s.get("first_name")),
                    "last_name": text(s.get("last_name")),
                    "client_external_id": s.get("customer_id"),
                    "year_group": text(s.get("grade")),
                    "school": text(s.get("school")),
                    "date_of_birth": text(s.get("birth_date"))[:10],
                    "status": _status(STUDENT_STATUS, s.get("status"), "active"),
                }
        elif entity == "tutors":
            tiers = {t.get("id"): t for t in self.api.list(credentials, "wage_tiers")}
            for e in self.api.list(credentials, "employees"):
                tier = tiers.get(e.get("wage_tier_id")) or {}
                yield {
                    "external_id": e.get("id"),
                    "email": text(e.get("email")),
                    "first_name": text(e.get("first_name")),
                    "last_name": text(e.get("last_name")),
                    "phone": text(e.get("mobile_phone") or e.get("home_phone")),
                    "status": _status(EMPLOYEE_STATUS, e.get("status"), "active"),
                    "pay_rate": _money(tier.get("wage") or e.get("wage")),
                }
        elif entity == "services":
            for s in self.api.list(credentials, "services"):
                yield {
                    "external_id": s.get("id"),
                    "name": text(s.get("name")),
                    "charge_rate": _money(s.get("cost") or s.get("cost_per_hour")),
                    "pay_rate": _money(s.get("wage") or s.get("wage_per_hour")),
                    "default_duration_minutes": text(s.get("duration")),
                }
        elif entity == "lessons":
            for lesson in self.api.list(credentials, "lessons"):
                participants = lesson.get("participants") or []
                yield {
                    "external_id": lesson.get("id"),
                    "date": text(lesson.get("date") or lesson.get("from_date"))[:10],
                    "start_time": text(lesson.get("from_time"))[:5],
                    "end_time": text(lesson.get("to_time"))[:5],
                    "timezone": self.timezone,
                    "service_external_id": lesson.get("service_id"),
                    "service": text(lesson.get("service_name")),
                    "student_external_ids": joined(p.get("student_id") for p in participants),
                    "tutor_external_id": lesson.get("employee_id"),
                    "status": _status(LESSON_STATUS, lesson.get("status"), "planned"),
                    "notes": text(lesson.get("description")),
                }
        elif entity == "invoices":
            for i in self.api.list(credentials, "invoices"):
                yield {
                    "number": text(i.get("number") or i.get("id")),
                    "client_external_id": i.get("customer_id"),
                    "issue_date": text(i.get("date"))[:10],
                    "due_date": text(i.get("due_date"))[:10],
                    "total": _money(i.get("total")),
                    "amount_paid": _money(i.get("paid")),
                    "status": _status(INVOICE_STATUS, i.get("status"), "issued"),
                }
        elif entity == "payments":
            for p in self.api.list(credentials, "payments"):
                day = text(p.get("date"))[:10]
                if day and day < cutover.isoformat():
                    continue  # history: carried by the invoices' amount paid and balances
                yield {
                    "client_external_id": p.get("customer_id"),
                    "amount": _money(p.get("amount")),
                    "date": day,
                    "method": METHODS.get(text(p.get("payment_method")).lower(), "other"),
                    "reference": text(p.get("reference") or p.get("id")),
                    "invoice_number": text(p.get("invoice_number")),
                }
        elif entity == "packages":
            for p in self.api.list(credentials, "packages"):
                if not _money(p.get("remaining_value")):
                    continue
                yield {
                    "client_external_id": p.get("customer_id"),
                    "package": text(p.get("name")),
                    "remaining_value": _money(p.get("remaining_value")),
                    "remaining_hours": _money(p.get("remaining_hours")),
                    "expires_on": text(p.get("expiry_date"))[:10],
                }

    def totals(self, credentials: Credentials, *, cutover: date) -> dict[str, Any]:
        def count(resource: str) -> int:
            return sum(1 for _ in self.api.list(credentials, resource))

        future = sum(
            1
            for lesson in self.api.list(credentials, "lessons")
            if text(lesson.get("date"))[:10] >= cutover.isoformat()
            and _status(LESSON_STATUS, lesson.get("status"), "planned") == "planned"
        )
        return {
            "clients": count("customers"),
            "students": count("students"),
            "tutors": count("employees"),
            "invoices": count("invoices"),
            "future_lessons": future,
        }
