"""Billing workflows (E10-TW1, E32).

* ``InvoiceRunWorkflow`` ``invoice-run:{org}:{run}``: collect charges → draft invoices →
  review window (timer, or wait for ``approve`` when auto-issue is off) → issue. Started
  by ``POST /invoice-runs`` or by ``ScheduledInvoiceRunWorkflow``.
* ``ScheduledInvoiceRunWorkflow``: started by a per-branch **Temporal Schedule** (weekly
  or monthly, ``billing.invoice_schedule``); opens the run for the period just ended and
  runs ``InvoiceRunWorkflow`` as a child.
* ``InvoiceDunningWorkflow`` ``invoice-dunning:{org}:{invoice}``: started by
  ``invoice.issued``; one reminder per offset in ``billing.reminder_offsets`` at 09:00
  local time; ``closed`` (paid, voided, written off) ends it.
* ``PaymentRequestWorkflow`` ``payment-request:{org}:{request}``: reminders 3 and 7 days
  after a request is created until it is paid or cancelled.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    idempotency_key,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import (
    BusinessCalendar,
    SettingsSnapshotInput,
    snapshot_settings,
    wait_until_local,
)

TIMEOUT = timedelta(minutes=10)
RUN_PROCESS = "invoice-run"
SCHEDULE_PROCESS = "invoice-schedule"
DUNNING_PROCESS = "invoice-dunning"
REQUEST_PROCESS = "payment-request"
REMINDER_TIME = time(9, 0)


def run_workflow_id(organisation_id: object, run_id: object) -> str:
    return workflow_id(RUN_PROCESS, organisation_id, run_id)


def dunning_workflow_id(organisation_id: object, invoice_id: object) -> str:
    return workflow_id(DUNNING_PROCESS, organisation_id, invoice_id)


def request_workflow_id(organisation_id: object, request_id: object) -> str:
    return workflow_id(REQUEST_PROCESS, organisation_id, request_id)


# --- activities -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class InvoiceRunInput(WorkflowInput):
    run_id: str


@dataclass(frozen=True, kw_only=True)
class ScheduledRunInput(WorkflowInput):
    branch_id: str
    cadence: str  # weekly | monthly


@dataclass(frozen=True, kw_only=True)
class DunningInput(WorkflowInput):
    invoice_id: str
    due_date: str  # ISO date


@dataclass(frozen=True, kw_only=True)
class ReminderInput(WorkflowInput):
    invoice_id: str
    offset: int


@dataclass(frozen=True, kw_only=True)
class RequestInput(WorkflowInput):
    request_id: str


@tenant_activity
def collect_invoice_run(input: InvoiceRunInput) -> dict[str, Any]:
    from . import services

    return services.collect_run(input.run_id)


@tenant_activity
def issue_invoice_run(input: InvoiceRunInput) -> dict[str, Any]:
    from . import services

    return services.issue_run(input.run_id)


@tenant_activity
def open_scheduled_run(input: ScheduledRunInput) -> str:
    """Create (once) the run for the period that just ended; '' if it already existed."""
    from tutortrack.tenancy.models import Branch

    from . import services

    period = services.scheduled_period(input.cadence, services.org_today())
    branch = Branch.objects.get(pk=input.branch_id)
    run, created = services.create_run(
        period_start=period[0], period_end=period[1], branch=branch, start_workflow=False
    )
    if not created:
        return ""
    from .models import InvoiceRun

    InvoiceRun.objects.filter(pk=run.pk).update(
        workflow_id=run_workflow_id(input.organisation_id, run.pk)
    )
    return str(run.pk)


@tenant_activity
def send_invoice_reminder(input: ReminderInput) -> bool:
    from . import services

    return services.send_reminder(input.invoice_id, input.offset, dedupe_key=idempotency_key())


@tenant_activity
def invoice_is_open(input: DunningInput) -> bool:
    from .models import Invoice

    invoice = Invoice.objects.filter(pk=input.invoice_id).first()
    return bool(invoice and invoice.is_open)


@tenant_activity
def remind_payment_request(input: RequestInput) -> bool:
    from django.db import transaction

    from tutortrack.core.events import publish

    from .events import PaymentRequestSent
    from .models import PaymentRequest

    request = PaymentRequest.objects.filter(pk=input.request_id).first()
    if request is None or request.status != PaymentRequest.Status.OPEN:
        return False
    with transaction.atomic():
        publish(
            PaymentRequestSent(subject_id=request.pk, client_id=str(request.client_id)),
            branch_id=request.branch_id,
            dedupe_key=idempotency_key(),
        )
    return True


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=RUN_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class InvoiceRunWorkflow:
    def __init__(self) -> None:
        self.approved = False
        self.step = "collecting"
        self.stats: dict[str, Any] = {}

    @workflow.signal(name="approve")
    def approve(self) -> None:
        self.approved = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "stats": self.stats}

    @workflow.run
    async def run(self, input: InvoiceRunInput) -> str:
        await report_step(input, self.step)
        self.stats = await workflow.execute_activity(
            collect_invoice_run, input, start_to_close_timeout=TIMEOUT
        )
        if self.stats.get("drafts", 0):
            self.step = "review"
            await report_step(input, self.step)
            if self.stats.get("auto_issue", True):
                days = int(self.stats.get("review_days", 0))
                if days > 0:
                    with contextlib.suppress(TimeoutError):
                        await workflow.wait_condition(
                            lambda: self.approved, timeout=timedelta(days=days)
                        )
            else:
                try:
                    await workflow.wait_condition(lambda: self.approved, timeout=timedelta(days=90))
                except TimeoutError:
                    self.step = "not_approved"
                    await report_step(input, self.step, status="completed")
                    return self.step
        self.step = "issuing"
        await report_step(input, self.step)
        self.stats = await workflow.execute_activity(
            issue_invoice_run, input, start_to_close_timeout=timedelta(hours=1)
        )
        self.step = "completed"
        await report_step(input, self.step, status="completed")
        return self.step


@register_workflow(process=SCHEDULE_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class ScheduledInvoiceRunWorkflow:
    @workflow.run
    async def run(self, input: ScheduledRunInput) -> str:
        run_id = await workflow.execute_activity(
            open_scheduled_run, input, start_to_close_timeout=TIMEOUT
        )
        if not run_id:
            await report_step(input, "already_run", status="completed")
            return "already_run"
        result = await workflow.execute_child_workflow(
            InvoiceRunWorkflow.run,
            InvoiceRunInput(organisation_id=input.organisation_id, run_id=run_id),
            id=run_workflow_id(input.organisation_id, run_id),
        )
        await report_step(input, str(result), status="completed")
        return str(result)


@register_workflow(
    process=DUNNING_PROCESS, task_queue="billing", cancel_permission="billing.invoice.void"
)
@workflow.defn
class InvoiceDunningWorkflow:
    def __init__(self) -> None:
        self.closed = False
        self.sent: list[int] = []

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"sent": self.sent, "closed": self.closed}

    @workflow.run
    async def run(self, input: DunningInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(
                organisation_id=input.organisation_id,
                keys=["billing.reminders_enabled", "billing.reminder_offsets"],
            ),
            start_to_close_timeout=TIMEOUT,
        )
        if not settings.get("billing.reminders_enabled", True):
            await report_step(input, "disabled", status="completed")
            return "disabled"
        calendar = BusinessCalendar(timezone=str(settings["timezone"]))
        due = date.fromisoformat(input.due_date)
        offsets = sorted({int(o) for o in settings.get("billing.reminder_offsets") or []})
        for offset in offsets:
            moment = datetime.combine(due + timedelta(days=offset), REMINDER_TIME)
            if await wait_until_local(moment, calendar, until=lambda: self.closed):
                break
            still_open = await workflow.execute_activity(
                invoice_is_open, input, start_to_close_timeout=TIMEOUT
            )
            if not still_open:
                break
            await workflow.execute_activity(
                send_invoice_reminder,
                ReminderInput(
                    organisation_id=input.organisation_id,
                    invoice_id=input.invoice_id,
                    offset=offset,
                ),
                start_to_close_timeout=TIMEOUT,
            )
            self.sent.append(offset)
        await report_step(input, "finished", status="completed")
        return f"sent:{len(self.sent)}"


@register_workflow(process=REQUEST_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class PaymentRequestWorkflow:
    def __init__(self) -> None:
        self.closed = False

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.run
    async def run(self, input: RequestInput) -> str:
        reminded = 0
        for days in (3, 7):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.closed,
                    timeout=timedelta(days=days if not reminded else days - 3),
                )
            if self.closed:
                break
            if not await workflow.execute_activity(
                remind_payment_request, input, start_to_close_timeout=TIMEOUT
            ):
                break
            reminded += 1
        await report_step(input, "finished", status="completed")
        return f"reminded:{reminded}"
