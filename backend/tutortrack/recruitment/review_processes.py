"""Temporal workflows added by gap batch G5a (E18 FR-18-2, FR-18-9).

* ``InterviewWorkflow`` ``interview:{org}:{interview}``: started when an applicant books an
  interview (``application.interview_booked``). Creates the video meeting (retried; the
  booking stands if the provider keeps failing), emails the applicant the time and link,
  alerts recruiters, then reminds the applicant 24 hours before.
* ``ProbationReviewWorkflow`` ``probation:{org}:{review}``: started by
  ``probation.scheduled``. Reminds staff ``recruitment.probation_reminder_days`` before the
  due date (09:00 local), tells them on the day, then chases weekly (up to eight times)
  until the outcome is recorded (signal ``closed`` from ``probation.completed``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import (
    BusinessCalendar,
    delay_until_local,
    wait_until_local,
)

TIMEOUT = timedelta(minutes=5)
INTERVIEW_PROCESS = "interview"
PROBATION_PROCESS = "probation"
MEETING_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=5,
    non_retryable_error_types=["AuthError", "ConfigurationError"],
)
REMINDER_BEFORE = timedelta(hours=24)
CHASE_EVERY = timedelta(days=7)
MAX_CHASES = 8


def interview_workflow_id(org: object, interview_id: object) -> str:
    return workflow_id(INTERVIEW_PROCESS, org, interview_id)


def probation_workflow_id(org: object, review_id: object) -> str:
    return workflow_id(PROBATION_PROCESS, org, review_id)


@dataclass(frozen=True, kw_only=True)
class InterviewInput(WorkflowInput):
    interview_id: str


@dataclass(frozen=True, kw_only=True)
class InterviewReminderInput(WorkflowInput):
    interview_id: str
    start: str


@dataclass(frozen=True, kw_only=True)
class ProbationInput(WorkflowInput):
    review_id: str


@dataclass(frozen=True, kw_only=True)
class ProbationAlertInput(WorkflowInput):
    review_id: str
    stage: str


# --- activities -----------------------------------------------------------------------------


@tenant_activity
def interview_snapshot(input: InterviewInput) -> dict[str, Any]:
    from . import interviews

    return interviews.interview_snapshot(input.interview_id)


@tenant_activity
def provision_interview_meeting(input: InterviewInput) -> str:
    from . import interviews

    return interviews.provision_meeting(input.interview_id)


@tenant_activity
def confirm_interview(input: InterviewInput) -> bool:
    from . import interviews

    return interviews.confirm(input.interview_id)


@tenant_activity
def remind_interview(input: InterviewReminderInput) -> bool:
    from . import interviews

    return interviews.remind(input.interview_id, input.start)


@tenant_activity
def probation_snapshot(input: ProbationInput) -> dict[str, Any]:
    from . import performance

    return performance.probation_snapshot(input.review_id)


@tenant_activity
def probation_alert(input: ProbationAlertInput) -> bool:
    from . import performance

    return performance.probation_alert(input.review_id, input.stage)


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=INTERVIEW_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class InterviewWorkflow:
    @workflow.run
    async def run(self, input: InterviewInput) -> str:
        snap = await workflow.execute_activity(
            interview_snapshot, input, start_to_close_timeout=TIMEOUT
        )
        if not snap["booked"]:
            await report_step(input, "not_booked", status="completed")
            return "not_booked"
        video = "none"
        if snap["video"]:
            await report_step(input, "creating_meeting")
            try:
                video = await workflow.execute_activity(
                    provision_interview_meeting,
                    input,
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=MEETING_RETRY,
                )
            except ActivityError:
                video = "failed"  # the interview stands; staff can add a link by hand
        await workflow.execute_activity(confirm_interview, input, start_to_close_timeout=TIMEOUT)
        start = datetime.fromisoformat(snap["start"])
        remind_at = start - REMINDER_BEFORE
        reminded = False
        if remind_at > workflow.now():
            await report_step(input, "waiting")
            await workflow.sleep(remind_at - workflow.now())
            reminded = await workflow.execute_activity(
                remind_interview,
                InterviewReminderInput(
                    organisation_id=input.organisation_id,
                    interview_id=input.interview_id,
                    start=snap["start"],
                ),
                start_to_close_timeout=TIMEOUT,
            )
        result = f"video:{video},reminded:{str(reminded).lower()}"
        await report_step(input, result, status="completed")
        return result


@register_workflow(process=PROBATION_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class ProbationReviewWorkflow:
    def __init__(self) -> None:
        self.closed = False

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    async def _alert(self, input: ProbationInput, stage: str) -> bool:
        return bool(
            await workflow.execute_activity(
                probation_alert,
                ProbationAlertInput(
                    organisation_id=input.organisation_id, review_id=input.review_id, stage=stage
                ),
                start_to_close_timeout=TIMEOUT,
            )
        )

    async def _finish(self, input: ProbationInput, result: str) -> str:
        await report_step(input, result, status="completed")
        return result

    @workflow.run
    async def run(self, input: ProbationInput) -> str:
        snap = await workflow.execute_activity(
            probation_snapshot, input, start_to_close_timeout=TIMEOUT
        )
        if not snap["open"]:
            return await self._finish(input, "reviewed")
        calendar = BusinessCalendar(timezone=snap["timezone"])
        due = date.fromisoformat(snap["due_on"])
        upcoming = datetime.combine(due - timedelta(days=int(snap["reminder_days"])), time(9, 0))
        if delay_until_local(workflow.now(), upcoming, calendar) > timedelta(0):
            await report_step(input, "waiting")
            if await wait_until_local(upcoming, calendar, until=lambda: self.closed):
                return await self._finish(input, "reviewed")
            if not await self._alert(input, "upcoming"):
                return await self._finish(input, "reviewed")
        if await wait_until_local(
            datetime.combine(due, time(9, 0)), calendar, until=lambda: self.closed
        ):
            return await self._finish(input, "reviewed")
        if not await self._alert(input, "due"):
            return await self._finish(input, "reviewed")
        await report_step(input, "due")
        for _round in range(MAX_CHASES):
            try:
                await workflow.wait_condition(lambda: self.closed, timeout=CHASE_EVERY)
                return await self._finish(input, "reviewed")
            except TimeoutError:
                if not await self._alert(input, "overdue"):
                    return await self._finish(input, "reviewed")
        return await self._finish(input, "unreviewed")
