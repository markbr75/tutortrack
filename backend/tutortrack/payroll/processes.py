"""Temporal workflows for payroll (E12-TW1).

* ``PayRunWorkflow`` ``pay-run:{org}:{run}``: assemble → wait for approval (``approved``,
  reminders every 3 days; ``cancelled`` ends it) → statements → payouts → wait until every
  payout is settled (``settled`` signal, checked daily) → paid / partially failed.
* ``ScheduledPayRunWorkflow``: started by a per-branch Temporal Schedule at the cut-off
  (``payroll.pay_period``); opens the run for the period just ended and runs
  ``PayRunWorkflow`` as a child.
* ``ExpenseApprovalWorkflow`` ``expense:{org}:{expense}``: started by ``expense.submitted``;
  notifies approvers and reminds them after 3 and 7 days until ``decided``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=10)
RUN_PROCESS = "pay-run"
SCHEDULE_PROCESS = "pay-run-schedule"
EXPENSE_PROCESS = "expense-approval"
REMIND_EVERY = timedelta(days=3)
SETTLE_CHECK = timedelta(days=1)
MAX_SETTLE_DAYS = 60


def pay_run_workflow_id(organisation_id: object, pay_run_id: object) -> str:
    return workflow_id(RUN_PROCESS, organisation_id, pay_run_id)


def expense_workflow_id(organisation_id: object, expense_id: object) -> str:
    return workflow_id(EXPENSE_PROCESS, organisation_id, expense_id)


@dataclass(frozen=True, kw_only=True)
class PayRunInput(WorkflowInput):
    pay_run_id: str


@dataclass(frozen=True, kw_only=True)
class ScheduledPayRunInput(WorkflowInput):
    branch_id: str
    cadence: str


@dataclass(frozen=True, kw_only=True)
class ExpenseInput(WorkflowInput):
    expense_id: str


# --- activities -----------------------------------------------------------------------------


@tenant_activity
def assemble_pay_run(input: PayRunInput) -> dict[str, Any]:
    from . import services

    return services.assemble(input.pay_run_id)


@tenant_activity
def pay_run_status(input: PayRunInput) -> str:
    from .models import PayRun

    run = PayRun.objects.filter(pk=input.pay_run_id).first()
    return run.status if run else "cancelled"


@tenant_activity
def remind_pay_run_approvers(input: PayRunInput) -> bool:
    from . import services

    return services.remind_approvers(input.pay_run_id)


@tenant_activity
def issue_pay_statements(input: PayRunInput) -> int:
    from . import services

    return services.issue_statements(input.pay_run_id)


@tenant_activity
def send_pay_run_payouts(input: PayRunInput) -> int:
    from . import services

    return services.send_payouts(input.pay_run_id)


@tenant_activity
def payouts_outstanding(input: PayRunInput) -> int:
    from . import services
    from .models import PayRun

    return services.outstanding(PayRun.objects.get(pk=input.pay_run_id))


@tenant_activity
def finalise_pay_run(input: PayRunInput) -> str:
    from . import services

    return services.finalise(input.pay_run_id)


@tenant_activity
def open_scheduled_pay_run(input: ScheduledPayRunInput) -> str:
    """Create (once) the run for the period that just ended; '' if it already existed."""
    from tutortrack.tenancy.models import Branch

    from . import services
    from .models import PayRun

    if input.cadence == "fortnightly":
        today = services.org_today()
        if today.isocalendar().week % 2:
            return ""  # every other week
    start, end = services.scheduled_period(input.cadence, services.org_today())
    branch = Branch.objects.get(pk=input.branch_id)
    run, created = services.create_pay_run(
        period_start=start, period_end=end, branch=branch, start_workflow=False
    )
    if not created:
        return ""
    PayRun.objects.filter(pk=run.pk).update(
        workflow_id=pay_run_workflow_id(input.organisation_id, run.pk)
    )
    return str(run.pk)


@tenant_activity
def remind_expense_approvers(input: ExpenseInput) -> bool:
    from . import services

    return services.expense_reminder(input.expense_id)


# --- workflows ------------------------------------------------------------------------------


@register_workflow(
    process=RUN_PROCESS, task_queue="payroll", cancel_permission="payroll.payrun.create"
)
@workflow.defn
class PayRunWorkflow:
    def __init__(self) -> None:
        self.approved = False
        self.cancelled = False
        self.settled = 0
        self.step = "assembling"

    @workflow.signal(name="approved")
    def approve(self) -> None:
        self.approved = True

    @workflow.signal(name="cancelled")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.signal(name="settled")
    def settle(self) -> None:
        self.settled += 1

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "approved": self.approved, "cancelled": self.cancelled}

    @workflow.run
    async def run(self, input: PayRunInput) -> str:
        await workflow.execute_activity(assemble_pay_run, input, start_to_close_timeout=TIMEOUT)
        self.step = "review"
        await report_step(input, "review")
        while not (self.approved or self.cancelled):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.approved or self.cancelled, timeout=REMIND_EVERY
                )
            if self.approved or self.cancelled:
                break
            status = await workflow.execute_activity(
                pay_run_status, input, start_to_close_timeout=TIMEOUT
            )
            if status == "approved":
                self.approved = True
                break
            if status == "cancelled":
                self.cancelled = True
                break
            await workflow.execute_activity(
                remind_pay_run_approvers, input, start_to_close_timeout=TIMEOUT
            )
        if self.cancelled:
            await report_step(input, "cancelled", status="completed")
            return "cancelled"
        self.step = "statements"
        await workflow.execute_activity(issue_pay_statements, input, start_to_close_timeout=TIMEOUT)
        self.step = "paying"
        await report_step(input, "paying")
        pending = await workflow.execute_activity(
            send_pay_run_payouts, input, start_to_close_timeout=TIMEOUT
        )
        days = 0
        while pending and days < MAX_SETTLE_DAYS:
            seen = self.settled
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda seen=seen: self.settled != seen,  # type: ignore[misc]
                    timeout=SETTLE_CHECK,
                )
            days += 1
            pending = await workflow.execute_activity(
                payouts_outstanding, input, start_to_close_timeout=TIMEOUT
            )
        result = await workflow.execute_activity(
            finalise_pay_run, input, start_to_close_timeout=TIMEOUT
        )
        self.step = result
        await report_step(input, result, status="completed")
        return result


@register_workflow(process=SCHEDULE_PROCESS, task_queue="payroll", cancel_permission=None)
@workflow.defn
class ScheduledPayRunWorkflow:
    @workflow.run
    async def run(self, input: ScheduledPayRunInput) -> str:
        run_id = await workflow.execute_activity(
            open_scheduled_pay_run, input, start_to_close_timeout=TIMEOUT
        )
        if not run_id:
            await report_step(input, "skipped", status="completed")
            return "skipped"
        child_input = PayRunInput(organisation_id=input.organisation_id, pay_run_id=run_id)
        await workflow.start_child_workflow(
            PayRunWorkflow.run,
            child_input,
            id=pay_run_workflow_id(input.organisation_id, run_id),
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        await report_step(input, "opened", status="completed")
        return run_id


@register_workflow(process=EXPENSE_PROCESS, task_queue="payroll", cancel_permission=None)
@workflow.defn
class ExpenseApprovalWorkflow:
    def __init__(self) -> None:
        self.decided = False
        self.reminded = 0

    @workflow.signal(name="decided")
    def decide(self) -> None:
        self.decided = True

    @workflow.run
    async def run(self, input: ExpenseInput) -> str:
        await workflow.execute_activity(
            remind_expense_approvers, input, start_to_close_timeout=TIMEOUT
        )
        for wait in (timedelta(days=3), timedelta(days=4)):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.decided, timeout=wait)
            if self.decided:
                break
            if not await workflow.execute_activity(
                remind_expense_approvers, input, start_to_close_timeout=TIMEOUT
            ):
                break
            self.reminded += 1
        await report_step(input, "finished", status="completed")
        return f"reminded:{self.reminded}"
