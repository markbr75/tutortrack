"""Temporal workflows for homework and library loans (E21-TW1).

* ``HomeworkReminderWorkflow`` ``homework:{org}:{assignment}:{round}``: started by
  ``homework.assigned`` (round 1) and ``homework.returned`` (each resubmission round).
  Reminds the student and family ``learning.homework_reminder_hours`` before the due
  time (unless the homework was set inside that window), then at the due time marks it
  overdue (``homework.overdue``) and tells the family and the tutor. Signal ``changed``
  (hand-in, new due date, cancelled, excused) makes it re-read the assignment; it ends as
  soon as the assignment is no longer open. Replaces a ``next_reminder_at`` sweeper.
* ``LoanReminderWorkflow`` ``loan:{org}:{loan}``: started by ``loan.created``. Reminds
  ``learning.loan_reminder_days`` before the due date, marks the loan overdue
  (``loan.overdue``) the day after it, then sends up to ``learning.loan_overdue_notices``
  notices every ``learning.loan_overdue_notice_days``. Signal ``changed`` (returned, lost,
  extended) re-reads the loan; it ends when the loan is closed or the notices run out.

Both workflows only orchestrate: every decision that depends on data is made by an
activity calling the services (idempotent: reminders and overdue marks happen once).
"""

from __future__ import annotations

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

TIMEOUT = timedelta(minutes=5)
HOMEWORK_PROCESS = "homework"
LOAN_PROCESS = "loan"
MAX_ROUNDS = 200


def homework_workflow_id(org: object, assignment_id: object, round_: object) -> str:
    return workflow_id(HOMEWORK_PROCESS, org, assignment_id, round_)


def loan_workflow_id(org: object, loan_id: object) -> str:
    return workflow_id(LOAN_PROCESS, org, loan_id)


@dataclass(frozen=True, kw_only=True)
class AssignmentInput(WorkflowInput):
    assignment_id: str


@dataclass(frozen=True, kw_only=True)
class LoanInput(WorkflowInput):
    loan_id: str


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def homework_state(input: AssignmentInput) -> dict[str, Any]:
    from . import services

    return services.assignment_state(input.assignment_id)


@tenant_activity
def remind_homework(input: AssignmentInput) -> bool:
    from . import services

    return services.send_homework_reminder(input.assignment_id)


@tenant_activity
def homework_overdue(input: AssignmentInput) -> str:
    from tutortrack.core.workflows import idempotency_key

    from . import services

    return services.mark_homework_overdue(input.assignment_id, dedupe_key=idempotency_key())


@tenant_activity
def loan_status(input: LoanInput) -> dict[str, Any]:
    from . import services

    return services.loan_state(input.loan_id)


@tenant_activity
def remind_loan(input: LoanInput) -> bool:
    from . import services

    return services.send_loan_reminder(input.loan_id)


@tenant_activity
def loan_overdue(input: LoanInput) -> bool:
    from tutortrack.core.workflows import idempotency_key

    from . import services

    return services.mark_loan_overdue(input.loan_id, dedupe_key=idempotency_key())


@tenant_activity
def loan_notice(input: LoanInput) -> bool:
    from . import services

    return services.send_overdue_notice(input.loan_id)


# --- workflows ----------------------------------------------------------------------------------


class _Waits:
    """Sleep until a moment unless a ``changed`` signal arrives first."""

    def __init__(self) -> None:
        self.changes = 0

    async def sleep_until(self, moment: datetime) -> bool:
        """True when woken early by a signal (the caller re-reads the state)."""
        left = moment - workflow.now()
        if left <= timedelta(0):
            return False
        seen = self.changes
        try:
            await workflow.wait_condition(lambda: self.changes != seen, timeout=left)
        except TimeoutError:
            return False
        return True


@register_workflow(process=HOMEWORK_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class HomeworkReminderWorkflow(_Waits):
    def __init__(self) -> None:
        super().__init__()
        self.step = "starting"

    @workflow.signal(name="changed")
    def changed(self) -> None:
        self.changes += 1

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "changes": self.changes}

    @workflow.run
    async def run(self, input: AssignmentInput) -> str:
        for _round in range(MAX_ROUNDS):
            state = await workflow.execute_activity(
                homework_state, input, start_to_close_timeout=TIMEOUT
            )
            if not state["open"]:
                self.step = str(state["status"])
                await report_step(input, self.step, status="completed")
                return self.step
            due = datetime.fromisoformat(state["due_at"])
            if state["remind"] and workflow.now() < due:
                self.step = "waiting_to_remind"
                await report_step(input, self.step)
                if await self.sleep_until(datetime.fromisoformat(state["remind_at"])):
                    continue
                await workflow.execute_activity(
                    remind_homework, input, start_to_close_timeout=TIMEOUT
                )
                continue
            self.step = "waiting_for_due"
            await report_step(input, self.step)
            if await self.sleep_until(due):
                continue
            outcome = await workflow.execute_activity(
                homework_overdue, input, start_to_close_timeout=TIMEOUT
            )
            self.step = str(outcome)
            await report_step(input, self.step, status="completed")
            return self.step
        return "gave_up"


@register_workflow(
    process=LOAN_PROCESS, task_queue="default", cancel_permission="learning.library.manage"
)
@workflow.defn
class LoanReminderWorkflow(_Waits):
    def __init__(self) -> None:
        super().__init__()
        self.step = "starting"

    @workflow.signal(name="changed")
    def changed(self) -> None:
        self.changes += 1

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "changes": self.changes}

    async def _finish(self, input: LoanInput, step: str) -> str:
        self.step = step
        await report_step(input, step, status="completed")
        return step

    @workflow.run
    async def run(self, input: LoanInput) -> str:
        for _round in range(MAX_ROUNDS):
            state = await workflow.execute_activity(
                loan_status, input, start_to_close_timeout=TIMEOUT
            )
            if not state["open"]:
                return await self._finish(input, str(state["status"]))
            due = datetime.fromisoformat(state["due_at"])
            if not state["overdue"]:
                if state["remind"] and workflow.now() < due:
                    self.step = "waiting_to_remind"
                    await report_step(input, self.step)
                    if await self.sleep_until(datetime.fromisoformat(state["remind_at"])):
                        continue
                    await workflow.execute_activity(
                        remind_loan, input, start_to_close_timeout=TIMEOUT
                    )
                    continue
                self.step = "on_loan"
                await report_step(input, self.step)
                if await self.sleep_until(due):
                    continue
                await workflow.execute_activity(loan_overdue, input, start_to_close_timeout=TIMEOUT)
                continue
            if int(state["notices"]) >= int(state["max_notices"]):
                return await self._finish(input, "overdue")
            self.step = "overdue"
            await report_step(input, self.step)
            if await self.sleep_until(datetime.fromisoformat(state["next_notice_at"])):
                continue
            await workflow.execute_activity(loan_notice, input, start_to_close_timeout=TIMEOUT)
        return "gave_up"
