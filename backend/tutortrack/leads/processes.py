"""Temporal workflows for leads (E17-TW1).

* ``EnquiryFollowUpWorkflow`` ``enquiry:{org}:{id}``: started by ``enquiry.received``.
  Sends the acknowledgement and tells the owner, then watches each stage's SLA: when an
  enquiry sits in a stage past its SLA hours, ``enquiry.sla_breached`` and a staff alert.
  After a trial lesson it reminds the owner to record the outcome. Signals
  ``stage_changed`` (re-read the stage), ``trial_done`` and ``closed`` (won or lost).
* ``WaitlistOfferWorkflow`` ``waitlist-offer:{org}:{entry}``: started by
  ``waitlist.place_offered``; waits for ``responded`` until the offer expires, then expires
  it and (setting) offers the place to the next student.
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
ENQUIRY_PROCESS = "enquiry"
OFFER_PROCESS = "waitlist-offer"
MAX_STAGE_CHANGES = 200


def enquiry_workflow_id(organisation_id: object, enquiry_id: object) -> str:
    return workflow_id(ENQUIRY_PROCESS, organisation_id, enquiry_id)


def offer_workflow_id(organisation_id: object, entry_id: object) -> str:
    return workflow_id(OFFER_PROCESS, organisation_id, entry_id)


@dataclass(frozen=True, kw_only=True)
class EnquiryInput(WorkflowInput):
    enquiry_id: str


@dataclass(frozen=True, kw_only=True)
class BreachInput(WorkflowInput):
    enquiry_id: str
    stage_id: str


@dataclass(frozen=True, kw_only=True)
class OfferInput(WorkflowInput):
    entry_id: str
    expires_at: str


# --- activities -----------------------------------------------------------------------------


@tenant_activity
def acknowledge_enquiry(input: EnquiryInput) -> bool:
    from . import services

    return services.acknowledge(input.enquiry_id)


@tenant_activity
def enquiry_sla(input: EnquiryInput) -> dict[str, Any]:
    from . import services

    return services.sla_status(input.enquiry_id)


@tenant_activity
def breach_enquiry_sla(input: BreachInput) -> bool:
    from . import services

    return services.breach_sla(input.enquiry_id, input.stage_id)


@tenant_activity
def trial_follow_up(input: EnquiryInput) -> bool:
    from . import services

    return services.trial_follow_up(input.enquiry_id)


@tenant_activity
def trial_follow_up_hours(input: EnquiryInput) -> int:
    from tutortrack.tenancy.settings_service import get_setting

    return int(get_setting("leads.trial_follow_up_hours"))


@tenant_activity
def expire_waitlist_offer(input: OfferInput) -> str:
    from . import services

    return services.expire_offer(input.entry_id)


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=ENQUIRY_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class EnquiryFollowUpWorkflow:
    def __init__(self) -> None:
        self.changes = 0
        self.closed = False
        self.trial_done = False

    @workflow.signal(name="stage_changed")
    def stage_changed(self) -> None:
        self.changes += 1

    @workflow.signal(name="trial_done")
    def trial(self) -> None:
        self.trial_done = True

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"changes": self.changes, "closed": self.closed}

    async def _breach(self, input: EnquiryInput, stage_id: str) -> bool:
        return bool(
            await workflow.execute_activity(
                breach_enquiry_sla,
                BreachInput(organisation_id=input.organisation_id, enquiry_id=input.enquiry_id,
                            stage_id=stage_id),
                start_to_close_timeout=TIMEOUT,
            )
        )  # fmt: skip

    @workflow.run
    async def run(self, input: EnquiryInput) -> str:
        await workflow.execute_activity(acknowledge_enquiry, input, start_to_close_timeout=TIMEOUT)
        breaches = 0
        followed_up = False
        for _round in range(MAX_STAGE_CHANGES):
            if self.closed:
                break
            sla = await workflow.execute_activity(
                enquiry_sla, input, start_to_close_timeout=TIMEOUT
            )
            if not sla.get("open"):
                break
            seen = self.changes
            deadline = (
                datetime.fromisoformat(sla["deadline"])
                if sla.get("deadline") and not sla.get("breached")
                else None
            )
            if deadline is not None and deadline <= workflow.now():
                if await self._breach(input, sla["stage"]):
                    breaches += 1
                continue
            wait: timedelta | None = deadline - workflow.now() if deadline else None
            if self.trial_done and not followed_up:
                hours = await workflow.execute_activity(
                    trial_follow_up_hours, input, start_to_close_timeout=TIMEOUT
                )
                follow = timedelta(hours=hours)
                wait = follow if wait is None else min(wait, follow)
            trial_seen = self.trial_done
            try:
                await workflow.wait_condition(
                    lambda seen=seen, trial_seen=trial_seen: (  # type: ignore[misc]
                        self.closed or self.changes != seen or self.trial_done != trial_seen
                    ),
                    timeout=wait,
                )
            except TimeoutError:
                if self.trial_done and not followed_up:
                    followed_up = True
                    await workflow.execute_activity(
                        trial_follow_up, input, start_to_close_timeout=TIMEOUT
                    )
        await report_step(input, "finished", status="completed")
        return f"breaches:{breaches}"


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
