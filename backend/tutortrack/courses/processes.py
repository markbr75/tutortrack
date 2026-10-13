"""Temporal workflows for class enrolment and term rollover (E20-TW1).

* ``EnrolmentPaymentWorkflow`` ``enrolment-payment:{org}:{enrolment}``: started by
  ``enrolment.created`` for a place held while the family pays. Waits for
  ``payment_received`` (from ``payment_request.paid``) until the hold expires, then
  confirms the enrolment (sessions and fees) or releases the place to the waitlist.
  Signal ``cancelled`` ends it early. Replaces a pending-payment sweeper.
* ``TermRolloverWorkflow`` ``rollover:{org}:{rollover}``: started by
  ``term.rollover_started``. Sends confirm/opt-out requests to families, reminds those who
  haven't answered half way to the deadline, and at the deadline (or when everyone has
  answered, or on ``finalise``) enrols the continuing students, releases the other places
  to the waitlists and bills next term's fees. Signals: ``responded`` (each answer),
  ``finalise`` (staff close it early), ``cancel``. Replaces a batch job and manual
  reminders.
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

TIMEOUT = timedelta(minutes=5)
PAYMENT_PROCESS = "enrolment-payment"
ROLLOVER_PROCESS = "rollover"
MAX_ROUNDS = 5000


def payment_workflow_id(org: object, enrolment_id: object) -> str:
    return workflow_id(PAYMENT_PROCESS, org, enrolment_id)


def rollover_workflow_id(org: object, rollover_id: object) -> str:
    return workflow_id(ROLLOVER_PROCESS, org, rollover_id)


@dataclass(frozen=True, kw_only=True)
class EnrolmentInput(WorkflowInput):
    enrolment_id: str


@dataclass(frozen=True, kw_only=True)
class RolloverInput(WorkflowInput):
    rollover_id: str


@dataclass(frozen=True, kw_only=True)
class RolloverRound(WorkflowInput):
    rollover_id: str
    reminder: bool = False


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def enrolment_payment_state(input: EnrolmentInput) -> dict[str, str]:
    from . import services

    return services.payment_state(input.enrolment_id)


@tenant_activity
def confirm_paid_enrolment(input: EnrolmentInput) -> str:
    from . import services

    return services.confirm_enrolment(input.enrolment_id)


@tenant_activity
def release_unpaid_enrolment(input: EnrolmentInput) -> str:
    from . import services

    return services.release_enrolment(input.enrolment_id, reason="unpaid")


@tenant_activity
def rollover_status(input: RolloverInput) -> dict[str, Any]:
    from . import services

    return services.rollover_state(input.rollover_id)


@tenant_activity
def send_rollover_round(input: RolloverRound) -> int:
    from . import services

    return services.send_rollover_requests(input.rollover_id, reminder=input.reminder)


@tenant_activity
def finalise_term_rollover(input: RolloverInput) -> dict[str, int]:
    from . import services

    return services.finalise_rollover(input.rollover_id)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=PAYMENT_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class EnrolmentPaymentWorkflow:
    def __init__(self) -> None:
        self.paid = False
        self.cancelled = False

    @workflow.signal(name="payment_received")
    def payment_received(self) -> None:
        self.paid = True

    @workflow.signal(name="cancelled")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, bool]:
        return {"paid": self.paid, "cancelled": self.cancelled}

    @workflow.run
    async def run(self, input: EnrolmentInput) -> str:
        state = await workflow.execute_activity(
            enrolment_payment_state, input, start_to_close_timeout=TIMEOUT
        )
        if state["status"] != "pending_payment":
            await report_step(input, state["status"], status="completed")
            return state["status"]
        await report_step(input, "awaiting_payment")
        remaining = datetime.fromisoformat(state["expires_at"]) - workflow.now()
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.paid or self.cancelled, timeout=remaining
                )
        if self.cancelled and not self.paid:
            await report_step(input, "cancelled", status="completed")
            return "cancelled"
        activity = confirm_paid_enrolment if self.paid else release_unpaid_enrolment
        outcome = await workflow.execute_activity(activity, input, start_to_close_timeout=TIMEOUT)
        await report_step(input, outcome, status="completed")
        return str(outcome)


@register_workflow(
    process=ROLLOVER_PROCESS, task_queue="default", cancel_permission="courses.rollover.manage"
)
@workflow.defn
class TermRolloverWorkflow:
    def __init__(self) -> None:
        self.responses = 0
        self.finalise_now = False
        self.cancelled = False
        self.everyone_answered = False
        self.checked = -1  # answers counted at the last check (-1: check once at the start)

    @workflow.signal(name="responded")
    def responded(self) -> None:
        self.responses += 1

    @workflow.signal(name="finalise")
    def finalise(self) -> None:
        self.finalise_now = True

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"responses": self.responses, "finalise_now": self.finalise_now}

    def _done(self) -> bool:
        return self.finalise_now or self.cancelled or self.everyone_answered

    async def _status(self, input: RolloverInput) -> dict[str, Any]:
        return await workflow.execute_activity(
            rollover_status, input, start_to_close_timeout=TIMEOUT
        )

    async def _wait_until(self, input: RolloverInput, until: datetime) -> None:
        """Wait for the deadline, staff, or the last family's answer (answers that came
        before the wait are checked first)."""
        for _round in range(MAX_ROUNDS):
            if self.responses != self.checked and not self._done():
                self.checked = self.responses
                state = await self._status(input)
                if int(state["pending"]) == 0:
                    self.everyone_answered = True
            left = until - workflow.now()
            if left <= timedelta(0) or self._done():
                return
            try:
                await workflow.wait_condition(
                    lambda: self.responses != self.checked or self.finalise_now or self.cancelled,
                    timeout=left,
                )
            except TimeoutError:
                return

    @workflow.run
    async def run(self, input: RolloverInput) -> str:
        state = await self._status(input)
        if state["status"] != "running":
            await report_step(input, state["status"], status="completed")
            return str(state["status"])
        round_input = RolloverRound(
            organisation_id=input.organisation_id, rollover_id=input.rollover_id
        )
        await workflow.execute_activity(
            send_rollover_round, round_input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, "waiting")
        deadline = datetime.fromisoformat(str(state["deadline"]))
        start = workflow.now()
        await self._wait_until(input, start + (deadline - start) / 2)
        if not self._done():
            state = await self._status(input)
            if state["status"] == "running" and int(state["pending"]) > 0:
                await workflow.execute_activity(
                    send_rollover_round,
                    RolloverRound(
                        organisation_id=input.organisation_id,
                        rollover_id=input.rollover_id,
                        reminder=True,
                    ),
                    start_to_close_timeout=TIMEOUT,
                )
                await report_step(input, "reminded")
            await self._wait_until(input, deadline)
        if self.cancelled:
            await report_step(input, "cancelled", status="completed")
            return "cancelled"
        result = await workflow.execute_activity(
            finalise_term_rollover, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, "finalised", status="completed")
        return f"finalised:{int(result.get('enrolled', 0))}"
