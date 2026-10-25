"""Billing's built-in workflows (E33 T04): the invoicing cycle, payment chasing, payment
request reminders and monthly statements.

Each organisation's first version comes from the settings these replace, so nothing changes
on the day they ship; the replaced Temporal Schedules are removed when they are installed.
The replaced settings stay readable for one release (``replaced_by`` in ``org_settings``).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from tutortrack.automations.builtin_workflows import builtin_workflow

MAX_STEPS = 30  # automations.services.MAX_STEPS
CHASING_STOPS = ["invoice.paid", "invoice.voided", "invoice.written_off"]
DEFAULT_OFFSETS = [-3, 0, 3, 7, 14, 30]
DEFAULT_FEE_DAYS = 14  # LateFeeRule.days_overdue's default
REMINDER = {"type": "action", "action": "send_invoice_reminder", "config": {}}
LATE_FEE = {"type": "action", "action": "late_fee", "config": {}}
COLLECTIONS = {"type": "action", "action": "open_collections", "config": {}}


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


# --- invoicing cycle -------------------------------------------------------------------------


def _invoicing(
    *, frequency: str = "monthly", day: int = 1, review_days: int = 2, auto_issue: bool = True,
    email: bool = True,
) -> dict[str, Any]:  # fmt: skip
    trigger: dict[str, Any] = {"subject": "branch", "frequency": frequency, "time": "06:00",
                               "start": "invoice_run.due"}  # fmt: skip
    if frequency == "weekly":
        trigger["weekday"] = (day - 1) % 7  # the setting counts 1 = Monday ... 7 = Sunday
    else:
        trigger["day"] = min(max(day, 1), 28)
    issue = "after_review" if auto_issue else "when_approved"
    start = {"period": "schedule", "review_days": review_days, "issue": issue, "email": email}
    return {
        "trigger_type": "schedule",
        "trigger_config": trigger,
        "steps": [{"type": "action", "action": "start_invoice_run", "config": start}],
    }


def invoicing_from_settings() -> dict[str, Any]:
    """``billing.invoice_schedule`` (manual: switched off), ``invoice_day``,
    ``review_days``, ``auto_issue`` and ``auto_send``, at organisation level."""
    schedule = str(_setting("billing.invoice_schedule"))
    definition = _invoicing(
        frequency="weekly" if schedule == "weekly" else "monthly",
        day=int(_setting("billing.invoice_day")),
        review_days=int(_setting("billing.review_days")),
        auto_issue=bool(_setting("billing.auto_issue")),
        email=bool(_setting("billing.auto_send")),
    )
    return definition | {"enabled": schedule != "manual"}


def _retire_invoice_schedules() -> None:
    from .schedules import retire_invoice_schedules

    retire_invoice_schedules()


@builtin_workflow(
    "invoicing_cycle", "invoicing",
    name=N_("Invoicing cycle"),
    description=N_("On a schedule, start each branch's invoice run, give staff time to review "
                   "the drafts, then issue and email them."),
    first_version=invoicing_from_settings, enabled=False, retire=_retire_invoice_schedules,
    off_means=N_("Invoices are made by hand: start an invoice run from Billing."),
)  # fmt: skip
def invoicing_cycle() -> dict[str, Any]:
    return _invoicing()


# --- payment chasing -------------------------------------------------------------------------


def _chasing_steps(offsets: list[int], fee_days: list[int], collections: int) -> list[Any]:
    """Reminders, late fees and collections on one timeline from the due date, at 09:00
    local time (as ``InvoiceDunningWorkflow`` did). Monthly late fees past the step limit
    are left out."""
    fees = list(fee_days)
    while True:
        items = sorted(
            [(o, 0) for o in offsets] + [(d, 1) for d in fees]
            + ([(collections, 2)] if collections else [])
        )  # fmt: skip
        steps: list[Any] = []
        last = None
        for day, kind in items:
            if day != last:
                steps.append({"type": "wait", "until": "invoice.due_date", "offset_days": day,
                              "at": "09:00"})  # fmt: skip
                last = day
            steps.append((REMINDER, LATE_FEE, COLLECTIONS)[kind])
        if len(steps) <= MAX_STEPS or len(fees) <= 1:
            return steps
        fees.pop()


def _chasing(offsets: list[int], fee_days: list[int], collections: int) -> dict[str, Any]:
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "invoice.issued"},
        "steps": _chasing_steps(offsets, fee_days, collections),
        "stop_when": list(CHASING_STOPS),
    }


def chasing_from_settings() -> dict[str, Any]:
    """``billing.reminders_enabled`` and ``reminder_offsets``, the late fee rule's timing
    (the organisation-wide rule, else a branch's) and ``collections_after_days``."""
    from . import dunning
    from .models import LateFeeRule

    reminders = bool(_setting("billing.reminders_enabled"))
    offsets = sorted({int(o) for o in _setting("billing.reminder_offsets") or []})
    rule = dunning.rule_for(None) or LateFeeRule.objects.filter(active=True).first()
    fee_days = dunning.fee_offsets(rule) if rule is not None else [DEFAULT_FEE_DAYS]
    collections = int(_setting("billing.collections_after_days"))
    definition = _chasing(offsets if reminders else [], fee_days, collections)
    return definition | {"enabled": reminders or rule is not None or collections > 0}


@builtin_workflow(
    "payment_chasing", "invoicing",
    name=N_("Payment chasing"),
    description=N_("Remind families before and after an invoice is due, apply your late fee "
                   "rule and open a collections case, until the invoice is paid."),
    first_version=chasing_from_settings,
    off_means=N_("No payment reminders, late fees or collections happen automatically: chase "
                 "unpaid invoices yourself."),
)  # fmt: skip
def payment_chasing() -> dict[str, Any]:
    return _chasing(DEFAULT_OFFSETS, [DEFAULT_FEE_DAYS], 0)


# --- payment request reminders ---------------------------------------------------------------


@builtin_workflow(
    "payment_request_reminders", "invoicing",
    name=N_("Payment request reminders"),
    description=N_("Remind the family 3 and 7 days after a payment request, until it is paid "
                   "or cancelled."),
    off_means=N_("Families aren't reminded about open payment requests."),
)  # fmt: skip
def payment_request_reminders() -> dict[str, Any]:
    remind = {"type": "action", "action": "remind_payment_request", "config": {}}
    return {
        "trigger_type": "event",
        "trigger_config": {"event": "payment_request.created"},
        "steps": [{"type": "wait", "days": 3}, remind, {"type": "wait", "days": 4}, remind],
        "stop_when": ["payment_request.paid", "payment_request.cancelled"],
    }


# --- monthly statements ----------------------------------------------------------------------


def _statements(day: int = 1) -> dict[str, Any]:
    trigger = {"subject": "client", "frequency": "monthly", "day": min(day, 28),
               "time": "07:00", "start": "statement.due"}  # fmt: skip
    return {
        "trigger_type": "schedule",
        "trigger_config": trigger,
        "steps": [{"type": "action", "action": "send_statement", "config": {}}],
    }


def statements_from_settings() -> dict[str, Any]:
    """``billing.statement_schedule`` (none: switched off) and ``statement_day``."""
    definition = _statements(int(_setting("billing.statement_day")))
    return definition | {"enabled": _setting("billing.statement_schedule") == "monthly"}


def _retire_statement_schedule() -> None:
    from .statements import retire_schedule

    retire_schedule()


@builtin_workflow(
    "monthly_statements", "invoicing",
    name=N_("Monthly statements"),
    description=N_("Each month, email last month's statement to every family with account "
                   "activity or a balance."),
    first_version=statements_from_settings, enabled=False, retire=_retire_statement_schedule,
    off_means=N_("Statements are sent by hand from a family's billing page."),
)  # fmt: skip
def monthly_statements() -> dict[str, Any]:
    return _statements()
