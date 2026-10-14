"""Temporal workflows for reviews, referrals and affiliate statements (E25-TW1).

* ``ReviewRequestWorkflow`` ``review-request:{org}:{request}``: started by
  ``review.requested``. Sends the review link, reminds once after
  ``growth.review_reminder_days`` and closes the request when the link expires. Signals:
  ``submitted`` (from ``review.submitted``) and ``cancelled`` (staff) stop it. Replaces a
  reminder job.
* ``ReferralRewardWorkflow`` ``referral:{org}:{referral}``: started by ``referral.created``.
  Waits until the referee's first payment or N completed lessons (signal ``milestone``
  from ``payment.succeeded`` / ``lesson.completed`` makes it check) up to the programme
  deadline, then runs the fraud checks and gives the rewards (credit to the referrer,
  discount to the referee), or expires the referral. Signal ``cancel`` (staff) ends it.
  Replaces milestone polling.
* ``AffiliateStatementRunWorkflow``: a per-organisation Temporal Schedule (1st of the
  month, when ``growth.statement_schedule`` is ``monthly``) that issues last month's
  affiliate statements.
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
REVIEW_PROCESS = "review-request"
REFERRAL_PROCESS = "referral"
STATEMENT_PROCESS = "affiliate-statements"
MAX_CHECKS = 2000
OPEN = ("pending", "reminded")


def review_workflow_id(org: object, request_id: object) -> str:
    return workflow_id(REVIEW_PROCESS, org, request_id)


def referral_workflow_id(org: object, referral_id: object) -> str:
    return workflow_id(REFERRAL_PROCESS, org, referral_id)


@dataclass(frozen=True, kw_only=True)
class ReviewRequestInput(WorkflowInput):
    request_id: str


@dataclass(frozen=True, kw_only=True)
class ReviewSend(WorkflowInput):
    request_id: str
    reminder: bool = False


@dataclass(frozen=True, kw_only=True)
class ReferralInput(WorkflowInput):
    referral_id: str


@dataclass(frozen=True, kw_only=True)
class StatementRunInput(WorkflowInput):
    pass


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def review_request_state(input: ReviewRequestInput) -> dict[str, str]:
    from . import services

    return services.review_request_state(input.request_id)


@tenant_activity
def send_review_request(input: ReviewSend) -> bool:
    from . import services

    return services.send_review_request(input.request_id, reminder=input.reminder)


@tenant_activity
def expire_review_request(input: ReviewRequestInput) -> str:
    from . import services

    return services.expire_request(input.request_id)


@tenant_activity
def referral_state(input: ReferralInput) -> dict[str, str]:
    from . import services

    return services.referral_state(input.referral_id)


@tenant_activity
def referral_milestone_reached(input: ReferralInput) -> bool:
    from . import services

    return services.milestone_reached(input.referral_id)


@tenant_activity
def convert_referral(input: ReferralInput) -> str:
    from . import services

    return services.convert_referral(input.referral_id)


@tenant_activity
def reward_referral(input: ReferralInput) -> str:
    from . import services

    return services.reward_referral(input.referral_id)


@tenant_activity
def expire_referral(input: ReferralInput) -> str:
    from . import services

    return services.expire_referral(input.referral_id)


@tenant_activity
def issue_monthly_statements(input: StatementRunInput) -> int:
    from . import services

    return len(services.issue_statements())


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(
    process=REVIEW_PROCESS, task_queue="default", cancel_permission="growth.review.manage"
)
@workflow.defn
class ReviewRequestWorkflow:
    def __init__(self) -> None:
        self.submitted = False
        self.cancelled = False

    @workflow.signal(name="submitted")
    def submit(self) -> None:
        self.submitted = True

    @workflow.signal(name="cancelled")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, bool]:
        return {"submitted": self.submitted, "cancelled": self.cancelled}

    def _done(self) -> bool:
        return self.submitted or self.cancelled

    async def _wait_until(self, until: datetime) -> None:
        left = until - workflow.now()
        if left > timedelta(0) and not self._done():
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(self._done, timeout=left)

    def _outcome(self) -> str:
        return "submitted" if self.submitted else "cancelled"

    @workflow.run
    async def run(self, input: ReviewRequestInput) -> str:
        state = await workflow.execute_activity(
            review_request_state, input, start_to_close_timeout=TIMEOUT
        )
        if state["status"] not in OPEN:
            await report_step(input, state["status"], status="completed")
            return str(state["status"])
        send = ReviewSend(organisation_id=input.organisation_id, request_id=input.request_id)
        await workflow.execute_activity(send_review_request, send, start_to_close_timeout=TIMEOUT)
        await report_step(input, "sent")
        await self._wait_until(datetime.fromisoformat(state["reminder_at"]))
        if not self._done():
            reminder = ReviewSend(
                organisation_id=input.organisation_id, request_id=input.request_id, reminder=True
            )
            await workflow.execute_activity(
                send_review_request, reminder, start_to_close_timeout=TIMEOUT
            )
            await report_step(input, "reminded")
            await self._wait_until(datetime.fromisoformat(state["expires_at"]))
        if self._done():
            await report_step(input, self._outcome(), status="completed")
            return self._outcome()
        outcome = await workflow.execute_activity(
            expire_review_request, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, str(outcome), status="completed")
        return str(outcome)


@register_workflow(
    process=REFERRAL_PROCESS, task_queue="default", cancel_permission="growth.referral.manage"
)
@workflow.defn
class ReferralRewardWorkflow:
    def __init__(self) -> None:
        self.checks = 0
        self.seen = 0
        self.cancelled = False

    @workflow.signal(name="milestone")
    def milestone(self) -> None:
        self.checks += 1

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"checks": self.checks, "cancelled": self.cancelled}

    async def _reached(self, input: ReferralInput) -> bool:
        return bool(
            await workflow.execute_activity(
                referral_milestone_reached, input, start_to_close_timeout=TIMEOUT
            )
        )

    async def _wait_for_milestone(self, input: ReferralInput, deadline: datetime) -> bool:
        if await self._reached(input):  # paid before the workflow started
            return True
        for _round in range(MAX_CHECKS):
            left = deadline - workflow.now()
            if left <= timedelta(0) or self.cancelled:
                return False
            try:
                await workflow.wait_condition(
                    lambda: self.checks != self.seen or self.cancelled, timeout=left
                )
            except TimeoutError:
                return False
            if self.cancelled:
                return False
            self.seen = self.checks
            if await self._reached(input):
                return True
        return False

    @workflow.run
    async def run(self, input: ReferralInput) -> str:
        state = await workflow.execute_activity(
            referral_state, input, start_to_close_timeout=TIMEOUT
        )
        if state["status"] not in ("pending", "converted"):
            await report_step(input, state["status"], status="completed")
            return str(state["status"])
        if state["status"] == "pending":
            await report_step(input, "waiting_for_milestone")
            reached = await self._wait_for_milestone(
                input, datetime.fromisoformat(state["deadline"])
            )
            if self.cancelled:
                await report_step(input, "cancelled", status="completed")
                return "cancelled"
            if not reached:
                outcome = await workflow.execute_activity(
                    expire_referral, input, start_to_close_timeout=TIMEOUT
                )
                await report_step(input, str(outcome), status="completed")
                return str(outcome)
            converted = await workflow.execute_activity(
                convert_referral, input, start_to_close_timeout=TIMEOUT
            )
            if converted != "converted":
                await report_step(input, str(converted), status="completed")
                return str(converted)
            await report_step(input, "converted")
        outcome = await workflow.execute_activity(
            reward_referral, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, str(outcome), status="completed")
        return str(outcome)


@register_workflow(process=STATEMENT_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class AffiliateStatementRunWorkflow:
    @workflow.run
    async def run(self, input: StatementRunInput) -> str:
        issued = await workflow.execute_activity(
            issue_monthly_statements, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, f"issued:{issued}", status="completed")
        return f"issued:{issued}"
