"""TutorCruncher REST API connector (FR-28-3).

``https://secure.tutorcruncher.com/api/<resource>/`` with ``Authorization: token <key>``;
list endpoints page with ``next`` links (100 per page) and detail endpoints carry the full
record. ``http.request`` retries 429/5xx briefly and raises ``RateLimited`` beyond that, so
the pulling activity backs off on Temporal.

Their model → ours (docs/01-competitive-analysis.md): clients → clients and contacts,
recipients → students, contractors → tutors, services → jobs (rates on the job, one
catalogue service), appointments → lessons, invoices → historic invoices, client balances
→ opening balances, labels → tags. Agents, reviews, proformas and ad hoc charges are counted
in the source totals but have no import yet (E25/E10 Phase 2).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from tutortrack.integrations.providers import AccountInfo, AuthError, Credentials

from .base import joined, text

API = "https://secure.tutorcruncher.com/api"
SERVICE_NAME = "Tuition (TutorCruncher)"
ENTITIES = (
    "clients",
    "students",
    "tutors",
    "services",
    "jobs",
    "lessons",
    "invoices",
    "opening_balances",
    "tags",
)
UNSUPPORTED = ("agents", "reviews", "proformas", "adhoccharges")
CLIENT_STATUS = {"live": "active", "prospect": "prospect", "dormant": "dormant"}
TUTOR_STATUS = {
    "approved": "active",
    "pending": "onboarding",
    "rejected": "inactive",
    "dormant": "inactive",
    "archived": "inactive",
}
JOB_STATUS = {
    "pending": "draft",
    "available": "seeking_tutor",
    "in-progress": "active",
    "finished": "completed",
    "gone-cold": "cancelled",
    "planned": "active",
}
LESSON_STATUS = {
    "planned": "planned",
    "awaiting-report": "completed",
    "complete": "completed",
    "cancelled": "cancelled",
    "cancelled-chargeable": "cancelled",
}
INVOICE_STATUS = {
    "paid": "paid",
    "unpaid": "issued",
    "void": "void",
    "draft": "issued",
    "confirmed": "issued",
    "partially-paid": "partially_paid",
}


class Api(Protocol):
    def list(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]: ...

    def detail(self, credentials: Credentials, resource: str, pk: Any) -> dict[str, Any]: ...


class HttpApi:
    """The live API."""

    def _auth(self, credentials: Credentials) -> str:
        return f"token {credentials.secret}"

    def list(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]:
        from tutortrack.integrations.providers import http

        url: str | None = f"{API}/{resource}/"
        pages = 0
        while url and pages < 10_000:
            if not url.startswith(f"{API}/"):
                break  # only follow links on their API host
            body = http.request(
                "GET", url, auth_header=self._auth(credentials), provider="tutorcruncher"
            ).json()
            yield from body.get("results") or []
            url = body.get("next")
            pages += 1

    def detail(self, credentials: Credentials, resource: str, pk: Any) -> dict[str, Any]:
        from tutortrack.integrations.providers import http

        body: dict[str, Any] = http.request(
            "GET",
            f"{API}/{resource}/{int(pk)}/",
            auth_header=self._auth(credentials),
            provider="tutorcruncher",
        ).json()
        return body


def _money(value: Any) -> str:
    try:
        return str(Decimal(str(value))) if value not in (None, "") else ""
    except InvalidOperation:
        return ""


def _day(value: Any) -> str:
    raw = text(value)
    return raw[:10] if raw else ""


def _moment(value: Any) -> datetime:
    moment = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _name(value: Any) -> str:
    return text(value.get("name")) if isinstance(value, dict) else text(value)


def _labels(record: dict[str, Any]) -> str:
    return joined((label or {}).get("name") for label in record.get("labels") or [])


class TutorCruncherSource:
    provider = "tutorcruncher"

    def __init__(self, api: Api | None = None) -> None:
        self.api: Api = api or HttpApi()
        self.timezone = "UTC"  # the organisation's: appointment times are shown in it

    def supports(self, entity: str) -> bool:
        return entity in ENTITIES

    def verify(self, credentials: Credentials) -> AccountInfo:
        if not credentials.secret:
            raise AuthError("Enter your TutorCruncher API key.")
        first = next(iter(self.api.list(credentials, "clients")), None)
        branch = text((first or {}).get("branch")) or "TutorCruncher"
        return AccountInfo(f"tutorcruncher:{credentials.secret[-6:]}", branch)

    def _details(self, credentials: Credentials, resource: str) -> Iterator[dict[str, Any]]:
        for item in self.api.list(credentials, resource):
            if "user" not in item and item.get("id") is not None:
                yield self.api.detail(credentials, resource, item["id"])  # list rows are summaries
            else:
                yield item

    # --- mapping ---

    def fetch(
        self, credentials: Credentials, entity: str, *, cutover: date
    ) -> Iterator[dict[str, Any]]:
        if entity == "clients":
            for c in self._details(credentials, "clients"):
                user = c.get("user") or {}
                yield {
                    "external_id": c.get("id"),
                    "client_name": "",
                    "client_type": "household",
                    "status": CLIENT_STATUS.get(text(c.get("status")).lower(), "active"),
                    "first_name": user.get("first_name") or "",
                    "last_name": user.get("last_name") or "",
                    "email": user.get("email") or "",
                    "phone": user.get("phone") or "",
                    "mobile": user.get("mobile") or "",
                    "address_line1": user.get("street") or "",
                    "address_city": user.get("town") or "",
                    "address_postcode": user.get("postcode") or "",
                    "address_country": text(user.get("country")),
                    "tags": _labels(c),
                }
        elif entity == "students":
            for r in self._details(credentials, "recipients"):
                user = r.get("user") or {}
                paying = r.get("paying_client") or {}
                yield {
                    "external_id": r.get("id"),
                    "first_name": user.get("first_name") or "",
                    "last_name": user.get("last_name") or "",
                    "date_of_birth": _day(r.get("date_of_birth")),
                    "school": text(r.get("school")),
                    "year_group": _name(r.get("academic_year")),
                    "client_external_id": paying.get("id") if isinstance(paying, dict) else paying,
                    "tags": _labels(r),
                }
        elif entity == "tutors":
            for t in self._details(credentials, "contractors"):
                user = t.get("user") or {}
                skills = [
                    f"{text(s.get('subject'))}: {text(s.get('qual_level'))}".rstrip(": ")
                    for s in t.get("skills") or []
                ]
                yield {
                    "external_id": t.get("id"),
                    "email": user.get("email") or "",
                    "first_name": user.get("first_name") or "",
                    "last_name": user.get("last_name") or "",
                    "phone": user.get("mobile") or user.get("phone") or "",
                    "status": TUTOR_STATUS.get(text(t.get("status")).lower(), "onboarding"),
                    "subjects": joined(skills),
                    "address_postcode": user.get("postcode") or "",
                    "tags": _labels(t),
                }
        elif entity == "services":
            yield {"name": SERVICE_NAME, "format": "one_to_one", "charge_rate": "0"}
        elif entity == "jobs":
            for s in self.api.list(credentials, "services"):
                rcrs = s.get("rcrs") or []
                conjobs = s.get("conjobs") or []
                client_id = next(
                    (r.get("paying_client") for r in rcrs if r.get("paying_client")), None
                )
                yield {
                    "external_id": s.get("id"),
                    "name": text(s.get("name")),
                    "client_external_id": client_id,
                    "student_external_ids": joined(r.get("recipient") for r in rcrs),
                    "service": SERVICE_NAME,
                    "tutor_external_id": conjobs[0].get("contractor") if conjobs else "",
                    "charge_rate": _money(s.get("dft_charge_rate")),
                    "pay_rate": _money(
                        (conjobs[0] if conjobs else {}).get("pay_rate")
                        or s.get("dft_contractor_rate")
                    ),
                    "status": JOB_STATUS.get(text(s.get("status")).lower(), "active"),
                }
        elif entity == "lessons":
            local = ZoneInfo(self.timezone)
            for a in self.api.list(credentials, "appointments"):
                start = _moment(a.get("start")).astimezone(local)
                finish = _moment(a.get("finish")).astimezone(local)
                cjas = a.get("cjas") or []
                yield {
                    "external_id": a.get("id"),
                    "date": start.date().isoformat(),
                    "start_time": start.strftime("%H:%M"),
                    "end_time": finish.strftime("%H:%M"),
                    "timezone": self.timezone,
                    "job_external_id": (a.get("service") or {}).get("id"),
                    "student_external_ids": joined(
                        r.get("recipient") for r in a.get("rcras") or []
                    ),
                    "tutor_external_id": cjas[0].get("contractor") if cjas else "",
                    "status": LESSON_STATUS.get(text(a.get("status")).lower(), "planned"),
                    "notes": text(a.get("topic")),
                }
        elif entity == "invoices":
            for i in self.api.list(credentials, "invoices"):
                status = INVOICE_STATUS.get(text(i.get("status")).lower(), "issued")
                gross = _money(i.get("gross"))
                yield {
                    "number": text(i.get("display_id") or i.get("id")),
                    "client_external_id": (i.get("client") or {}).get("id"),
                    "issue_date": _day(i.get("date_sent") or i.get("date")),
                    "due_date": _day(i.get("date_due")),
                    "total": gross,
                    "tax": _money(i.get("tax")),
                    "amount_paid": gross if status == "paid" else _money(i.get("amount_paid")),
                    "status": status,
                }
        elif entity == "opening_balances":
            for c in self._details(credentials, "clients"):
                balance = _money(c.get("balance"))
                if balance and Decimal(balance) != 0:
                    # TutorCruncher: positive balance = credit held for the client.
                    yield {
                        "client_external_id": c.get("id"),
                        "balance": str(-Decimal(balance)),
                        "as_of": cutover.isoformat(),
                    }
        elif entity == "tags":
            return

    def totals(self, credentials: Credentials, *, cutover: date) -> dict[str, Any]:
        def count(resource: str) -> int:
            return sum(1 for _ in self.api.list(credentials, resource))

        balance = Decimal(0)
        for c in self._details(credentials, "clients"):
            value = _money(c.get("balance"))
            if value:
                balance -= Decimal(value)
        future = 0
        for a in self.api.list(credentials, "appointments"):
            start = text(a.get("start"))[:10]
            status = LESSON_STATUS.get(text(a.get("status")).lower(), "planned")
            if start >= cutover.isoformat() and status == "planned":
                future += 1
        totals: dict[str, Any] = {
            "clients": count("clients"),
            "students": count("recipients"),
            "tutors": count("contractors"),
            "jobs": count("services"),
            "invoices": count("invoices"),
            "balances_sum": str(balance),
            "future_lessons": future,
        }
        for resource in UNSUPPORTED:
            try:
                totals[f"not_imported_{resource}"] = count(resource)
            except Exception:
                totals[f"not_imported_{resource}"] = None
        return totals
