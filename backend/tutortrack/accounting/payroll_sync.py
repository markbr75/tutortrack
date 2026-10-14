"""Xero Payroll sync (E23-T10; E12 FR-12-8 "sync via API (Xero Payroll UK)").

When a pay run is approved and Xero Payroll is connected, ``XeroPayrollSyncWorkflow``
sends each employed tutor's hours (paid through the payroll provider) as a draft
timesheet: one line per day against the mapped earnings rate (default: the first
ordinary-earnings rate). Tutors are matched to Xero employees by email, or linked by
finance. Bonuses and reimbursements aren't timesheet units, so they are listed in the
sync result for the payroll administrator to add in Xero (and stay in the E12 CSV
export).

Idempotent: each timesheet is pushed with the key ``tt-<sync>-<tutor>``, so a retried
activity never duplicates one; tutors already sent are skipped on a retry.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import AuthError, ProviderError, RateLimited
from tutortrack.people.models import TutorProfile

from .models import AccountMapping, PayrollEmployeeLink, PayrollTimesheetSync

PROVIDER = "xero_payroll"


def connection() -> IntegrationConnection | None:
    return (
        IntegrationConnection.objects.filter(provider=PROVIDER, user__isnull=True)
        .exclude(status=IntegrationConnection.Status.DISCONNECTED)
        .first()
    )


def _creds() -> Any:
    from tutortrack.integrations import services as integrations

    conn = connection()
    if conn is None:
        raise BusinessRuleViolation(_("Connect Xero Payroll first."))
    return integrations.credentials(conn)


def _client() -> Any:
    from .providers import payroll_client

    return payroll_client()


def earnings_rate() -> str:
    mapping = AccountMapping.objects.filter(
        provider=PROVIDER, kind="earnings_rate", key="default"
    ).first()
    if mapping is not None:
        return mapping.external_id
    rates = _client().earnings_rates(_creds())
    ordinary = next((r for r in rates if r.kind == "OrdinaryEarnings"), None)
    if ordinary is None and not rates:
        raise BusinessRuleViolation(_("Xero Payroll has no earnings rates."))
    return (ordinary or rates[0]).id


@transaction.atomic
def set_earnings_rate(rate_id: str, name: str = "") -> AccountMapping:
    mapping, _created = AccountMapping.objects.update_or_create(
        provider=PROVIDER,
        kind="earnings_rate",
        key="default",
        defaults={"external_id": rate_id[:100], "name": name[:200]},
    )
    audit.record(mapping, "update", {"earnings_rate": rate_id})
    return mapping


@transaction.atomic
def match_employees() -> list[PayrollEmployeeLink]:
    """Link employed tutors to Xero employees with the same email (manual links stay)."""
    employees = {e.email: e for e in _client().employees(_creds()) if e.email}
    linked = set(
        PayrollEmployeeLink.objects.filter(provider=PROVIDER).values_list("tutor_id", flat=True)
    )
    tutors = TutorProfile.objects.filter(employment_type=TutorProfile.Employment.EMPLOYEE)
    created = []
    for tutor in tutors.exclude(pk__in=linked):
        employee = employees.get(tutor.email.lower())
        if employee is None:
            continue
        link = PayrollEmployeeLink.objects.create(
            tutor=tutor,
            provider=PROVIDER,
            employee_id=employee.id,
            calendar_id=employee.calendar_id,
            name=f"{employee.first_name} {employee.last_name}".strip(),
            matched_by="email",
        )
        created.append(link)
    return created


@transaction.atomic
def link_employee(tutor: TutorProfile, employee_id: str) -> PayrollEmployeeLink:
    employee = next((e for e in _client().employees(_creds()) if e.id == employee_id), None)
    if employee is None:
        message = _("That employee isn't in Xero Payroll.")
        raise BusinessRuleViolation(message, extra={"errors": {"employee_id": [message]}})
    link, _created = PayrollEmployeeLink.objects.update_or_create(
        provider=PROVIDER,
        tutor=tutor,
        defaults={
            "employee_id": employee.id,
            "calendar_id": employee.calendar_id,
            "name": f"{employee.first_name} {employee.last_name}".strip(),
            "matched_by": "manual",
        },
    )
    audit.record(link, "update", {"employee_id": employee_id})
    return link


def status() -> dict[str, Any]:
    conn = connection()
    links = list(PayrollEmployeeLink.objects.filter(provider=PROVIDER).select_related("tutor"))
    linked = {link.tutor_id for link in links}
    unlinked = TutorProfile.objects.filter(
        employment_type=TutorProfile.Employment.EMPLOYEE
    ).exclude(pk__in=linked)
    rate = AccountMapping.objects.filter(
        provider=PROVIDER, kind="earnings_rate", key="default"
    ).first()
    return {
        "connected": conn is not None,
        "connection_id": str(conn.pk) if conn else None,
        "account_name": conn.account_name if conn else "",
        "earnings_rate": {"id": rate.external_id, "name": rate.name} if rate else None,
        "links": [
            {
                "tutor": str(link.tutor_id),
                "tutor_name": link.tutor.full_name,
                "employee_id": link.employee_id,
                "name": link.name,
                "matched_by": link.matched_by,
            }
            for link in links
        ],
        "unlinked": [{"tutor": str(t.pk), "tutor_name": t.full_name} for t in unlinked[:200]],
        "syncs": list(PayrollTimesheetSync.objects.select_related("pay_run")[:20]),
    }


def should_sync(pay_run_id: Any) -> bool:
    from tutortrack.payroll.selectors import employee_timesheets

    return connection() is not None and bool(employee_timesheets(pay_run_id))


def sync_pay_run(pay_run_id: Any) -> str:
    """Send the run's employed tutors' hours; returns the sync status. Rate limits and
    provider outages raise (Temporal retries); a lost authorisation is recorded."""
    from tutortrack.payroll.selectors import employee_timesheets

    with transaction.atomic():
        sync, _created = PayrollTimesheetSync.objects.select_for_update().get_or_create(
            provider=PROVIDER, pay_run_id=pay_run_id
        )
        sync.attempts += 1
        sync.save(update_fields=["attempts", "updated_at"])
    done = {r["tutor"]: r for r in sync.results if r.get("timesheet")}
    results: list[dict[str, Any]] = list(done.values())
    try:
        creds = _creds()
        rate = earnings_rate()
        client = _client()
        if not PayrollEmployeeLink.objects.filter(provider=PROVIDER).exists():
            match_employees()
        links = {
            str(link.tutor_id): link
            for link in PayrollEmployeeLink.objects.filter(provider=PROVIDER)
        }
        for row in employee_timesheets(pay_run_id):
            if row["tutor_id"] in done:
                continue
            entry: dict[str, Any] = {
                "tutor": row["tutor_id"],
                "name": row["name"],
                "hours": str(sum(row["days"].values(), Decimal(0))),
                "other": str(row["other"]),
                "currency": row["currency"],
            }
            link = links.get(row["tutor_id"])
            if link is None:
                entry["problem"] = "no_employee"
            elif not row["days"]:
                entry["problem"] = "no_hours"
            else:
                from .providers.xero_payroll import Employee

                employee = Employee(link.employee_id, "", calendar_id=link.calendar_id)
                entry["timesheet"] = client.push_timesheet(
                    creds,
                    employee=employee,
                    start=row["period"][0],
                    end=row["period"][1],
                    lines=sorted(row["days"].items()),
                    earnings_rate=rate,
                    idempotency_key=f"tt-{sync.pk}-{row['tutor_id']}",
                )
            results.append(entry)
    except AuthError as exc:
        _finish(sync, results, PayrollTimesheetSync.Status.ERROR, str(exc))
        return PayrollTimesheetSync.Status.ERROR
    except (RateLimited, ProviderError):
        _finish(sync, results, PayrollTimesheetSync.Status.PENDING, "")
        raise
    except BusinessRuleViolation as exc:
        _finish(sync, results, PayrollTimesheetSync.Status.ERROR, str(exc))
        return PayrollTimesheetSync.Status.ERROR
    problems = any(r.get("problem") for r in results)
    state = PayrollTimesheetSync.Status.PARTIAL if problems else PayrollTimesheetSync.Status.SYNCED
    _finish(sync, results, state, "")
    return state


def _finish(
    sync: PayrollTimesheetSync, results: list[dict[str, Any]], state: str, error: str
) -> None:
    with transaction.atomic():
        PayrollTimesheetSync.objects.filter(pk=sync.pk).update(
            results=results,
            status=state,
            error=error[:500],
            synced_at=now() if state in ("synced", "partial") else None,
            updated_at=now(),
        )


@transaction.atomic
def mark_failed(pay_run_id: Any, error: str) -> None:
    PayrollTimesheetSync.objects.filter(provider=PROVIDER, pay_run_id=pay_run_id).update(
        status=PayrollTimesheetSync.Status.ERROR, error=error[:500], updated_at=now()
    )
