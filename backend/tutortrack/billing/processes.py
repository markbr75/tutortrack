"""Billing workflows (E10-TW1, E32).

* ``InvoiceRunWorkflow`` ``invoice-run:{org}:{run}``: collect charges → draft invoices →
  review window (timer, or wait for ``approve`` when auto-issue is off) → issue. Started
  by ``POST /invoice-runs`` or by the Invoicing cycle built-in workflow (E33 T04).

The Invoicing cycle, Payment chasing, Payment request reminders and Monthly statements
built-in workflows (E33 T04, ``workflows_builtin.py``) replaced ``ScheduledInvoiceRunWorkflow``,
``InvoiceDunningWorkflow``, ``PaymentRequestWorkflow`` and ``StatementRunWorkflow`` (removed in
E33 T09). ``SCHEDULE_PROCESS`` and ``STATEMENT_PROCESS`` name their old Temporal Schedules,
which are deleted when the built-ins are installed.

Phase 2:

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
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import (
    SettingsSnapshotInput,
    snapshot_settings,
)

TIMEOUT = timedelta(minutes=10)
RUN_PROCESS = "invoice-run"
SCHEDULE_PROCESS = "invoice-schedule"
PACKAGE_PROCESS = "package"
PLAN_PROCESS = "billing-plan"
TUTOR_REVIEW_PATCH = "tutor-review"
STATEMENT_PROCESS = "client-statements"
PLAN_PERIODS_PER_RUN = 24


def package_workflow_id(organisation_id: object, purchase_id: object, run: str) -> str:
    return workflow_id(PACKAGE_PROCESS, organisation_id, purchase_id, run)


def plan_workflow_id(organisation_id: object, plan_id: object) -> str:
    return workflow_id(PLAN_PROCESS, organisation_id, plan_id)


def run_workflow_id(organisation_id: object, run_id: object) -> str:
    return workflow_id(RUN_PROCESS, organisation_id, run_id)


# --- activities -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class InvoiceRunInput(WorkflowInput):
    run_id: str


@tenant_activity
def collect_invoice_run(input: InvoiceRunInput) -> dict[str, Any]:
    from . import services

    return services.collect_run(input.run_id)


@tenant_activity
def issue_invoice_run(input: InvoiceRunInput) -> dict[str, Any]:
    from . import services

    return services.issue_run(input.run_id)


# --- Phase 2 activities -----------------------------------------------------------------------


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
def package_expiry(input: PackageInput) -> str:
    from . import packages

    return packages.expiry_of(input.purchase_id)


@tenant_activity
def remind_package_expiry(input: PackageInput) -> bool:
    from . import packages

    return packages.remind_expiry(input.purchase_id)


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


@register_workflow(
    process=PACKAGE_PROCESS, task_queue="billing", cancel_permission="billing.package.manage"
)
@workflow.defn
class PackageExpiryWorkflow:
    """Replaces an expiry sweeper (E10-TW1): expire unused units. Runs started before E33
    T06 also remind before; the Package expiry built-in workflow does that now."""

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
        days = 0  # the Package expiry built-in workflow sends the reminder (E33 T06)
        if not workflow.patched("package-reminder-in-workflows"):
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
