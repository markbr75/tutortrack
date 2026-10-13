"""Temporal workflows for booking, reschedule requests and time off (E08-TW1).

* ``BookingHoldWorkflow`` ``booking-hold:{org}:{hold}``: started by ``booking.held``. Waits
  for the person to press Book (signal ``submitted``) until the hold expires, then for the
  payment (``paid``, from ``payment_request.paid``) until the payment hold expires, then for
  staff approval (``decided``) when bookings need it. Releases the slot on timeout; declines
  bookings nobody approved before the lesson. Replaces a Redis lock plus an expiry job.
* ``RescheduleRequestWorkflow`` ``reschedule:{org}:{request}``: started by
  ``reschedule.requested``. Reminds staff at half the window and declines the request at
  its deadline unless it was answered (``answered``).
* ``TimeOffApprovalWorkflow`` ``time-off:{org}:{exception}``: started by
  ``time_off.requested``. Waits for the admin decision (``decided``), reminding at half the
  time to the start; on approval flags the clashing lessons and asks for cover (E19
  ``create_cover`` starts ``CoverRequestWorkflow``); declines it if the time off starts
  undecided.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
HOLD_PROCESS = "booking-hold"
RESCHEDULE_PROCESS = "reschedule"
TIME_OFF_PROCESS = "time-off"
APPROVAL_WINDOW = timedelta(hours=48)


def hold_workflow_id(org: object, hold_id: object) -> str:
    return workflow_id(HOLD_PROCESS, org, hold_id)


def reschedule_workflow_id(org: object, request_id: object) -> str:
    return workflow_id(RESCHEDULE_PROCESS, org, request_id)


def time_off_workflow_id(org: object, exception_id: object) -> str:
    return workflow_id(TIME_OFF_PROCESS, org, exception_id)


@dataclass(frozen=True, kw_only=True)
class HoldInput(WorkflowInput):
    hold_id: str


@dataclass(frozen=True, kw_only=True)
class RescheduleInput(WorkflowInput):
    request_id: str


@dataclass(frozen=True, kw_only=True)
class TimeOffInput(WorkflowInput):
    exception_id: str


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def booking_state(input: HoldInput) -> dict[str, str]:
    from . import services

    return services.hold_state(input.hold_id)


@tenant_activity
def release_booking(input: HoldInput) -> bool:
    from . import services

    return services.release_hold(input.hold_id)


@tenant_activity
def confirm_paid_booking(input: HoldInput) -> str:
    from . import services

    return services.payment_received(input.hold_id)


@tenant_activity
def decline_unapproved_booking(input: HoldInput) -> bool:
    from . import services

    return services.decline_unanswered_booking(input.hold_id)


@tenant_activity
def reschedule_status(input: RescheduleInput) -> dict[str, str]:
    from . import services

    return services.reschedule_state(input.request_id)


@tenant_activity
def remind_reschedule_approver(input: RescheduleInput) -> bool:
    from . import services

    return services.remind_reschedule(input.request_id)


@tenant_activity
def expire_reschedule_request(input: RescheduleInput) -> bool:
    from . import services

    return services.expire_reschedule(input.request_id)


@tenant_activity
def time_off_status(input: TimeOffInput) -> dict[str, str]:
    from . import services

    return services.time_off_state(input.exception_id)


@tenant_activity
def remind_time_off_approver(input: TimeOffInput) -> bool:
    from . import services

    return services.remind_time_off(input.exception_id)


@tenant_activity
def expire_time_off_request(input: TimeOffInput) -> bool:
    from . import services

    return services.expire_time_off(input.exception_id)


@tenant_activity
def flag_time_off_cover(input: TimeOffInput) -> int:
    from . import services
    from .models import AvailabilityException

    exception = AvailabilityException.objects.filter(pk=input.exception_id).first()
    return len(services.flag_cover(exception)) if exception is not None else 0


# --- workflows ----------------------------------------------------------------------------------


def _remaining(deadline_iso: str) -> timedelta:
    return datetime.fromisoformat(deadline_iso) - workflow.now()


@register_workflow(process=HOLD_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class BookingHoldWorkflow:
    def __init__(self) -> None:
        self.events = 0
        self.is_paid = False

    @workflow.signal(name="submitted")
    def submitted(self) -> None:
        self.events += 1

    @workflow.signal(name="paid")
    def paid(self) -> None:
        self.events += 1
        self.is_paid = True

    @workflow.signal(name="decided")
    def decided(self) -> None:
        self.events += 1

    @workflow.signal(name="cancelled")
    def cancelled(self) -> None:
        self.events += 1

    async def _state(self, input: HoldInput) -> dict[str, str]:
        return await workflow.execute_activity(booking_state, input, start_to_close_timeout=TIMEOUT)

    async def _wait(self, until: timedelta, *, paid: bool = False) -> bool:
        """Wait for a new signal (or, with ``paid``, a payment that already arrived) up to
        ``until``; False on timeout."""
        seen = self.events
        if paid and self.is_paid:
            return True
        if until <= timedelta(0):
            return False
        try:
            await workflow.wait_condition(
                lambda: self.events != seen or (paid and self.is_paid), timeout=until
            )
        except TimeoutError:
            return False
        return True

    @workflow.run
    async def run(self, input: HoldInput) -> str:
        for _round in range(50):
            state = await self._state(input)
            status = state["status"]
            if status in ("confirmed", "declined", "expired", "cancelled", "missing"):
                await report_step(input, status, status="completed")
                return status
            if status in ("held", "awaiting_payment"):
                await report_step(input, status)
                paying = status == "awaiting_payment"
                if not await self._wait(_remaining(state["expires_at"]), paid=paying):
                    state = await self._state(input)
                    if state["status"] == status:  # nothing arrived: release the slot
                        await workflow.execute_activity(
                            release_booking, input, start_to_close_timeout=TIMEOUT
                        )
                    continue
                if paying and self.is_paid:
                    await workflow.execute_activity(
                        confirm_paid_booking, input, start_to_close_timeout=TIMEOUT
                    )
                continue
            # awaiting_approval: until the lesson (at most 48 hours from the request)
            await report_step(input, status)
            created = datetime.fromisoformat(state["created_at"])
            deadline = min(datetime.fromisoformat(state["start"]), created + APPROVAL_WINDOW)
            if not await self._wait(deadline - workflow.now()):
                await workflow.execute_activity(
                    decline_unapproved_booking, input, start_to_close_timeout=TIMEOUT
                )
        return "unfinished"


@register_workflow(process=RESCHEDULE_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class RescheduleRequestWorkflow:
    def __init__(self) -> None:
        self.answered = False

    @workflow.signal(name="answered")
    def answer(self) -> None:
        self.answered = True

    @workflow.run
    async def run(self, input: RescheduleInput) -> str:
        state = await workflow.execute_activity(
            reschedule_status, input, start_to_close_timeout=TIMEOUT
        )
        if state["status"] != "pending":
            await report_step(input, state["status"], status="completed")
            return state["status"]
        await report_step(input, "waiting")
        remaining = _remaining(state["deadline"])
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.answered, timeout=remaining / 2)
            if not self.answered:
                await workflow.execute_activity(
                    remind_reschedule_approver, input, start_to_close_timeout=TIMEOUT
                )
                left = _remaining(state["deadline"])
                if left > timedelta(0):
                    with contextlib.suppress(TimeoutError):
                        await workflow.wait_condition(lambda: self.answered, timeout=left)
        if not self.answered:
            await workflow.execute_activity(
                expire_reschedule_request, input, start_to_close_timeout=TIMEOUT
            )
        state = await workflow.execute_activity(
            reschedule_status, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, state["status"], status="completed")
        return state["status"]


@register_workflow(process=TIME_OFF_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class TimeOffApprovalWorkflow:
    def __init__(self) -> None:
        self.decided = False

    @workflow.signal(name="decided")
    def decide(self) -> None:
        self.decided = True

    @workflow.run
    async def run(self, input: TimeOffInput) -> str:
        state = await workflow.execute_activity(
            time_off_status, input, start_to_close_timeout=TIMEOUT
        )
        if state["status"] == "requested":
            await report_step(input, "waiting")
            remaining = _remaining(state["start"])
            if remaining > timedelta(0):
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(lambda: self.decided, timeout=remaining / 2)
                if not self.decided:
                    await workflow.execute_activity(
                        remind_time_off_approver, input, start_to_close_timeout=TIMEOUT
                    )
                    left = _remaining(state["start"])
                    if left > timedelta(0):
                        with contextlib.suppress(TimeoutError):
                            await workflow.wait_condition(lambda: self.decided, timeout=left)
            if not self.decided:
                await workflow.execute_activity(
                    expire_time_off_request, input, start_to_close_timeout=TIMEOUT
                )
            state = await workflow.execute_activity(
                time_off_status, input, start_to_close_timeout=TIMEOUT
            )
        if state["status"] == "approved":
            flagged = await workflow.execute_activity(
                flag_time_off_cover, input, start_to_close_timeout=TIMEOUT
            )
            outcome = "approved_cover" if flagged else "approved"
        else:
            outcome = state["status"]
        await report_step(input, outcome, status="completed")
        return outcome
