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

Phase 2:

* ``InvoiceDunningWorkflow`` (patched ``late-fees-collections``) also applies late fees
  and opens collections on the same timeline (FR-10-10, E10-T14).
* ``PackageExpiryWorkflow`` ``package:{org}:{purchase}:{n}``: started when a package with
  an expiry activates; reminder N days before → expiry (write off unused units). Signals
  ``depleted`` (stop) and ``extended(until)`` (new deadline).
* ``BillingPlanWorkflow`` ``billing-plan:{org}:{plan}``: charges each period of a recurring
  fixed fee when it starts; ``changed`` (pause, resume, edit, end) re-plans; continues as
  new every 24 periods.
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
PACKAGE_PROCESS = "package"
PLAN_PROCESS = "billing-plan"
REMINDER_TIME = time(9, 0)
LATE_FEES_PATCH = "late-fees-collections"
TUTOR_REVIEW_PATCH = "tutor-review"
STATEMENT_PROCESS = "client-statements"
PLAN_PERIODS_PER_RUN = 24


def package_workflow_id(organisation_id: object, purchase_id: object, run: str) -> str:
    return workflow_id(PACKAGE_PROCESS, organisation_id, purchase_id, run)


def plan_workflow_id(organisation_id: object, plan_id: object) -> str:
    return workflow_id(PLAN_PROCESS, organisation_id, plan_id)


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


# --- Phase 2 activities -----------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class FeeInput(WorkflowInput):
    invoice_id: str
    number: int


@dataclass(frozen=True, kw_only=True)
class PackageInput(WorkflowInput):
    purchase_id: str
    expires_at: str  # ISO datetime


@dataclass(frozen=True, kw_only=True)
class PlanInput(WorkflowInput):
    plan_id: str
    after: str = ""  # ISO date of the last period charged (continue-as-new)


@dataclass(frozen=True, kw_only=True)
class PlanPeriodInput(WorkflowInput):
    plan_id: str
    start: str


@tenant_activity
def invoice_dunning_plan(input: DunningInput) -> dict[str, Any]:
    from . import dunning

    return dunning.dunning_plan(input.invoice_id)


@tenant_activity
def apply_invoice_late_fee(input: FeeInput) -> str:
    from . import dunning

    return dunning.apply_late_fee(input.invoice_id, input.number)


@tenant_activity
def open_invoice_collections(input: DunningInput) -> bool:
    from . import dunning

    return dunning.open_collections(input.invoice_id, dedupe_key=idempotency_key())


@tenant_activity
def package_expiry(input: PackageInput) -> str:
    from . import packages

    return packages.expiry_of(input.purchase_id)


@tenant_activity
def remind_package_expiry(input: PackageInput) -> bool:
    from . import packages

    return packages.remind_expiry(input.purchase_id, dedupe_key=idempotency_key())


@tenant_activity
def expire_package(input: PackageInput) -> str:
    from . import packages

    return packages.expire_package(input.purchase_id, datetime.fromisoformat(input.expires_at))


@tenant_activity
def next_plan_period(input: PlanInput) -> dict[str, Any]:
    from . import plans

    return plans.next_period(input.plan_id, input.after)


@tenant_activity
def charge_plan_period(input: PlanPeriodInput) -> str:
    from . import plans

    return plans.charge_period(input.plan_id, input.start)


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=RUN_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class InvoiceRunWorkflow:
    def __init__(self) -> None:
        self.approved = False
        self.tutors_done = False
        self.step = "collecting"
        self.stats: dict[str, Any] = {}

    @workflow.signal(name="approve")
    def approve(self) -> None:
        self.approved = True

    @workflow.signal(name="tutors_done")
    def all_tutors_answered(self) -> None:
        """Gap G3: every tutor has checked their lessons on the drafts."""
        self.tutors_done = True

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
                tutor_days = int(self.stats.get("tutor_review_days", 0))
                if (
                    self.stats.get("tutor_review")
                    and workflow.patched(TUTOR_REVIEW_PATCH)
                    and tutor_days > days
                ):
                    # Gap G3: tutors have at least ``tutor_days`` to check their lessons;
                    # the window ends early once they all answer (or staff approve).
                    self.step = "tutor_review"
                    await report_step(input, self.step)
                    with contextlib.suppress(TimeoutError):
                        await workflow.wait_condition(
                            lambda: self.approved or self.tutors_done,
                            timeout=timedelta(days=tutor_days - days),
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
        self.fees: list[str] = []
        self.collections = False

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "closed": self.closed,
            "fees": self.fees,
            "collections": self.collections,
        }

    async def _with_fees(self, input: DunningInput) -> str:
        """Reminders, late fees and collections on one timeline (E10-T14)."""
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(
                organisation_id=input.organisation_id,
                keys=["billing.reminders_enabled", "billing.reminder_offsets"],
            ),
            start_to_close_timeout=TIMEOUT,
        )
        plan = await workflow.execute_activity(
            invoice_dunning_plan, input, start_to_close_timeout=TIMEOUT
        )
        offsets: list[int] = []
        if settings.get("billing.reminders_enabled", True):
            offsets = sorted({int(o) for o in settings.get("billing.reminder_offsets") or []})
        steps = [(o, 0, 0) for o in offsets]
        steps += [(int(o), 1, n) for n, o in enumerate(plan.get("fees") or [], start=1)]
        if plan.get("collections"):
            steps.append((int(plan["collections"]), 2, 0))
        steps.sort()
        if not steps:
            await report_step(input, "disabled", status="completed")
            return "disabled"
        calendar = BusinessCalendar(timezone=str(settings["timezone"]))
        due = date.fromisoformat(input.due_date)
        for offset, kind, number in steps:
            moment = datetime.combine(due + timedelta(days=offset), REMINDER_TIME)
            if await wait_until_local(moment, calendar, until=lambda: self.closed):
                break
            if not await workflow.execute_activity(
                invoice_is_open, input, start_to_close_timeout=TIMEOUT
            ):
                break
            if kind == 0:
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
            elif kind == 1:
                outcome = await workflow.execute_activity(
                    apply_invoice_late_fee,
                    FeeInput(
                        organisation_id=input.organisation_id,
                        invoice_id=input.invoice_id,
                        number=number,
                    ),
                    start_to_close_timeout=TIMEOUT,
                )
                self.fees.append(str(outcome))
            else:
                self.collections = bool(
                    await workflow.execute_activity(
                        open_invoice_collections, input, start_to_close_timeout=TIMEOUT
                    )
                )
        await report_step(input, "finished", status="completed")
        return f"sent:{len(self.sent)}"

    @workflow.run
    async def run(self, input: DunningInput) -> str:
        if workflow.patched(LATE_FEES_PATCH):
            return await self._with_fees(input)
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


@register_workflow(
    process=PACKAGE_PROCESS, task_queue="billing", cancel_permission="billing.package.manage"
)
@workflow.defn
class PackageExpiryWorkflow:
    """Replaces an expiry sweeper (E10-TW1): remind before, then expire unused units."""

    def __init__(self) -> None:
        self.depleted = False
        self.extended = ""
        self.reminded = False

    @workflow.signal(name="depleted")
    def deplete(self) -> None:
        self.depleted = True

    @workflow.signal(name="extended")
    def extend(self, until: str) -> None:
        self.extended = until

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"depleted": self.depleted, "reminded": self.reminded}

    def _woken(self) -> bool:
        return self.depleted or bool(self.extended)

    async def _wait(self, until: datetime) -> bool:
        """Sleep until ``until``; True when a signal woke us first."""
        delay = until - workflow.now()
        if delay <= timedelta(0):
            return self._woken()
        try:
            await workflow.wait_condition(self._woken, timeout=delay)
        except TimeoutError:
            return False
        return True

    @workflow.run
    async def run(self, input: PackageInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(
                organisation_id=input.organisation_id,
                keys=["billing.package_expiry_reminder_days"],
            ),
            start_to_close_timeout=TIMEOUT,
        )
        days = int(settings.get("billing.package_expiry_reminder_days") or 0)
        deadline = datetime.fromisoformat(input.expires_at)
        while True:
            remind_at = deadline - timedelta(days=days)
            if days and not self.reminded and remind_at > workflow.now():
                if await self._wait(remind_at):
                    if self.depleted:
                        break
                    deadline, self.extended = datetime.fromisoformat(self.extended), ""
                    continue
                self.reminded = bool(
                    await workflow.execute_activity(
                        remind_package_expiry, input, start_to_close_timeout=TIMEOUT
                    )
                )
            if await self._wait(deadline):
                if self.depleted:
                    break
                deadline, self.extended = datetime.fromisoformat(self.extended), ""
                self.reminded = False
                continue
            outcome = str(
                await workflow.execute_activity(
                    expire_package,
                    PackageInput(
                        organisation_id=input.organisation_id,
                        purchase_id=input.purchase_id,
                        expires_at=deadline.isoformat(),
                    ),
                    start_to_close_timeout=TIMEOUT,
                )
            )
            if outcome.startswith("moved:"):  # extended without a signal reaching us
                deadline = datetime.fromisoformat(outcome.removeprefix("moved:"))
                self.reminded = False
                continue
            await report_step(input, outcome, status="completed")
            return outcome
        await report_step(input, "depleted", status="completed")
        return "depleted"


@register_workflow(
    process=PLAN_PROCESS, task_queue="billing", cancel_permission="billing.plan.manage"
)
@workflow.defn
class BillingPlanWorkflow:
    """Charges each period of a recurring fixed fee when it starts (E10-T13)."""

    def __init__(self) -> None:
        self.changed = False
        self.charged: list[str] = []

    @workflow.signal(name="changed")
    def change(self) -> None:
        self.changed = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"charged": self.charged}

    @workflow.run
    async def run(self, input: PlanInput) -> str:
        after = input.after
        while True:
            self.changed = False
            nxt = await workflow.execute_activity(
                next_plan_period,
                PlanInput(
                    organisation_id=input.organisation_id, plan_id=input.plan_id, after=after
                ),
                start_to_close_timeout=TIMEOUT,
            )
            status = nxt.get("status")
            if status == "ended":
                break
            if status == "paused":
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(lambda: self.changed, timeout=timedelta(days=366))
                if not self.changed:
                    workflow.continue_as_new(
                        PlanInput(
                            organisation_id=input.organisation_id,
                            plan_id=input.plan_id,
                            after=after,
                        )
                    )
                after = max(after, str(nxt.get("today") or ""))  # skip periods while paused
                continue
            delay = datetime.fromisoformat(str(nxt["charge_at"])) - workflow.now()
            if delay > timedelta(0):
                try:
                    await workflow.wait_condition(lambda: self.changed, timeout=delay)
                    continue  # paused, resumed or edited: plan again
                except TimeoutError:
                    pass
            outcome = await workflow.execute_activity(
                charge_plan_period,
                PlanPeriodInput(
                    organisation_id=input.organisation_id,
                    plan_id=input.plan_id,
                    start=str(nxt["start"]),
                ),
                start_to_close_timeout=TIMEOUT,
            )
            if outcome == "paused":
                continue
            after = str(nxt["start"])
            self.charged.append(after)
            if len(self.charged) >= PLAN_PERIODS_PER_RUN:
                workflow.continue_as_new(
                    PlanInput(
                        organisation_id=input.organisation_id, plan_id=input.plan_id, after=after
                    )
                )
        await report_step(input, "ended", status="completed")
        return f"charged:{len(self.charged)}"


# --- gap G3: scheduled client statements (FR-10-9) ------------------------------------------

STATEMENT_BATCH = 50


@dataclass(frozen=True, kw_only=True)
class StatementRunInput(WorkflowInput):
    pass


@dataclass(frozen=True, kw_only=True)
class StatementBatchInput(WorkflowInput):
    client_ids: list[str]
    start: str  # ISO date
    end: str


@tenant_activity
def plan_statements(input: StatementRunInput) -> dict[str, Any]:
    """Last month's period and the clients to send statements to."""
    from . import services, statements

    start, end = statements.last_month(services.org_today())
    clients = sorted({client for client, _currency in statements.due(start, end)})
    return {"start": start.isoformat(), "end": end.isoformat(), "clients": clients}


@tenant_activity
def send_statement_batch(input: StatementBatchInput) -> int:
    from . import statements

    return statements.send(
        input.client_ids, date.fromisoformat(input.start), date.fromisoformat(input.end)
    )


@register_workflow(process=STATEMENT_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class StatementRunWorkflow:
    """Started monthly by the organisation's statement **Temporal Schedule**
    (``billing.statements.sync_schedule``): emails last month's statements in batches."""

    @workflow.run
    async def run(self, input: StatementRunInput) -> str:
        plan = await workflow.execute_activity(
            plan_statements, input, start_to_close_timeout=TIMEOUT
        )
        clients = list(plan["clients"])
        sent = 0
        for index in range(0, len(clients), STATEMENT_BATCH):
            sent += await workflow.execute_activity(
                send_statement_batch,
                StatementBatchInput(
                    organisation_id=input.organisation_id,
                    client_ids=clients[index : index + STATEMENT_BATCH],
                    start=str(plan["start"]),
                    end=str(plan["end"]),
                ),
                start_to_close_timeout=timedelta(minutes=30),
            )
        await report_step(input, "sent", status="completed")
        return f"sent:{sent}"
