"""Temporal workflows for leads (E17-TW1). The Enquiry follow-up built-in workflows (E33
T06) replaced ``EnquiryFollowUpWorkflow`` (removed in E33 T09).

* ``WaitlistOfferWorkflow`` ``waitlist-offer:{org}:{entry}``: started by
  ``waitlist.place_offered``; waits for ``responded`` until the offer expires, then expires
  it and (setting) offers the place to the next student.
* ``ProposalWorkflow`` ``proposal:{org}:{proposal}`` (E17-T09): started by ``proposal.sent``;
  reminds the family ``leads.proposal_reminder_days`` before the proposal expires and
  expires it at the deadline. Signal ``responded`` (accepted, declined or withdrawn) ends
  it. Conversion and the deposit request happen when the family accepts.
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
from tutortrack.core.workflows.timers import SettingsSnapshotInput, snapshot_settings

TIMEOUT = timedelta(minutes=5)
OFFER_PROCESS = "waitlist-offer"
PROPOSAL_PROCESS = "proposal"


def offer_workflow_id(organisation_id: object, entry_id: object) -> str:
    return workflow_id(OFFER_PROCESS, organisation_id, entry_id)


def proposal_workflow_id(organisation_id: object, proposal_id: object) -> str:
    return workflow_id(PROPOSAL_PROCESS, organisation_id, proposal_id)


@dataclass(frozen=True, kw_only=True)
class ProposalInput(WorkflowInput):
    proposal_id: str
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class OfferInput(WorkflowInput):
    entry_id: str
    expires_at: str


# --- activities -----------------------------------------------------------------------------


@tenant_activity
def expire_waitlist_offer(input: OfferInput) -> str:
    from . import services

    return services.expire_offer(input.entry_id)


@tenant_activity
def remind_proposal(input: ProposalInput) -> bool:
    from . import proposals

    return proposals.remind(input.proposal_id)


@tenant_activity
def expire_proposal(input: ProposalInput) -> bool:
    from . import proposals

    return proposals.expire(input.proposal_id)


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=OFFER_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class WaitlistOfferWorkflow:
    def __init__(self) -> None:
        self.responded = False

    @workflow.signal(name="responded")
    def respond(self) -> None:
        self.responded = True

    @workflow.run
    async def run(self, input: OfferInput) -> str:
        remaining = datetime.fromisoformat(input.expires_at) - workflow.now()
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.responded, timeout=remaining)
        if self.responded:
            await report_step(input, "responded", status="completed")
            return "responded"
        following = await workflow.execute_activity(
            expire_waitlist_offer, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, "expired", status="completed")
        return f"expired:{'cascaded' if following else 'none'}"


@register_workflow(
    process=PROPOSAL_PROCESS, task_queue="default", cancel_permission="leads.proposal.manage"
)
@workflow.defn
class ProposalWorkflow:
    def __init__(self) -> None:
        self.responded = False
        self.step = "sent"

    @workflow.signal(name="responded")
    def respond(self) -> None:
        self.responded = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    async def _wait_until(self, moment: datetime) -> bool:
        """Sleep until ``moment``; True if the family answered meanwhile."""
        remaining = moment - workflow.now()
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.responded, timeout=remaining)
        return self.responded

    @workflow.run
    async def run(self, input: ProposalInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(
                organisation_id=input.organisation_id, keys=["leads.proposal_reminder_days"]
            ),
            start_to_close_timeout=TIMEOUT,
        )
        expires = datetime.fromisoformat(input.expires_at)
        days = int(settings.get("leads.proposal_reminder_days", 3))
        await report_step(input, self.step)
        if days > 0 and await self._wait_until(expires - timedelta(days=days)):
            return await self._finish(input, "responded")
        if days > 0:
            await workflow.execute_activity(remind_proposal, input, start_to_close_timeout=TIMEOUT)
            self.step = "reminded"
            await report_step(input, self.step)
        if await self._wait_until(expires):
            return await self._finish(input, "responded")
        await workflow.execute_activity(expire_proposal, input, start_to_close_timeout=TIMEOUT)
        return await self._finish(input, "expired")

    async def _finish(self, input: ProposalInput, step: str) -> str:
        self.step = step
        await report_step(input, step, status="completed")
        return step
