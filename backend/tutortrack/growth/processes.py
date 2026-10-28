"""Temporal workflows for referrals and affiliate statements (E25-TW1). The Review request
built-in workflow (E33 T06) replaced ``ReviewRequestWorkflow`` (removed in E33 T09).

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
REFERRAL_PROCESS = "referral"
STATEMENT_PROCESS = "affiliate-statements"
MAX_CHECKS = 2000


def referral_workflow_id(org: object, referral_id: object) -> str:
    return workflow_id(REFERRAL_PROCESS, org, referral_id)


@dataclass(frozen=True, kw_only=True)
class ReferralInput(WorkflowInput):
    referral_id: str


@dataclass(frozen=True, kw_only=True)
class StatementRunInput(WorkflowInput):
    pass


# --- activities ---------------------------------------------------------------------------------


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
