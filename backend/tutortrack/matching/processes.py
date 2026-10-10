"""Temporal workflows for job offers and cover (E19-TW1).

* ``JobOfferCascadeWorkflow`` ``job-offer:{org}:{batch}``: started by
  ``job_offer.batch_started``. Sends the offers in waves (everyone at once, or one tutor
  at a time), waits for answers until each wave expires, and moves on. The first acceptance
  wins (or, when a coordinator must confirm, the first confirmed one): the tutor is assigned,
  the series created and the others withdrawn. Signals ``responded`` (a tutor answered or an
  offer was withdrawn), ``decided`` (a coordinator confirmed or rejected) and ``cancelled``.
  The id is per batch rather than per job (as the epic sketched) because Temporal ids can't
  be reused once a workflow has finished, and a job can be offered again.
* ``CoverRequestWorkflow`` ``cover:{org}:{request}``: started by ``cover_request.created``.
  Tells the eligible tutors and waits for ``accepted`` (the acceptance itself moves the
  lessons) or ``cancelled`` until the deadline, then escalates the request as unfilled.
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
OFFER_PROCESS = "job-offer"
COVER_PROCESS = "cover"
CONFIRM_WAIT = timedelta(days=7)
MAX_ROUNDS = 100


def offer_workflow_id(org: object, batch_id: object) -> str:
    return workflow_id(OFFER_PROCESS, org, batch_id)


def cover_workflow_id(org: object, request_id: object) -> str:
    return workflow_id(COVER_PROCESS, org, request_id)


@dataclass(frozen=True, kw_only=True)
class CascadeInput(WorkflowInput):
    batch_id: str
    expiry_hours: int
    admin_confirms: bool = False


@dataclass(frozen=True, kw_only=True)
class WaveInput(WorkflowInput):
    batch_id: str
    offer_ids: list[str]
    expires_at: str = ""


@dataclass(frozen=True, kw_only=True)
class OfferInput(WorkflowInput):
    batch_id: str
    offer_id: str


@dataclass(frozen=True, kw_only=True)
class CoverInput(WorkflowInput):
    request_id: str
    deadline: str  # ISO datetime


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def plan_offers(input: CascadeInput) -> list[list[str]]:
    from . import services

    return services.plan_offers(input.batch_id)


@tenant_activity
def send_wave(input: WaveInput) -> list[str]:
    from . import services

    return services.send_offers(
        input.batch_id, input.offer_ids, datetime.fromisoformat(input.expires_at)
    )


@tenant_activity
def wave_state(input: WaveInput) -> dict[str, Any]:
    from . import services

    return services.offer_state(input.batch_id, input.offer_ids)


@tenant_activity
def expire_wave(input: WaveInput) -> int:
    from . import services

    return services.expire_offers(input.offer_ids)


@tenant_activity
def request_confirmation(input: OfferInput) -> bool:
    from . import services

    return services.request_confirmation(input.batch_id, input.offer_id)


@tenant_activity
def fill_offer(input: OfferInput) -> str:
    from . import services

    return services.fill(input.batch_id, input.offer_id)


@tenant_activity
def exhaust_offers(input: CascadeInput) -> bool:
    from . import services

    return services.exhaust(input.batch_id)


@tenant_activity
def notify_cover(input: CoverInput) -> int:
    from . import services

    return services.notify_cover(input.request_id)


@tenant_activity
def cover_unfilled(input: CoverInput) -> bool:
    from . import services

    return services.mark_unfilled(input.request_id)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=OFFER_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class JobOfferCascadeWorkflow:
    def __init__(self) -> None:
        self.answers = 0
        self.decisions = 0
        self.cancelled = False

    @workflow.signal(name="responded")
    def responded(self) -> None:
        self.answers += 1

    @workflow.signal(name="decided")
    def decided(self) -> None:
        self.decisions += 1

    @workflow.signal(name="cancelled")
    def cancel(self) -> None:
        self.cancelled = True

    async def _wave(self, input: CascadeInput, offer_ids: list[str]) -> str:
        """Run one wave; returns ``filled``, ``closed`` or ``next``."""
        deadline = workflow.now() + timedelta(hours=input.expiry_hours)
        wave = WaveInput(
            organisation_id=input.organisation_id,
            batch_id=input.batch_id,
            offer_ids=offer_ids,
            expires_at=deadline.isoformat(),
        )
        sent = await workflow.execute_activity(send_wave, wave, start_to_close_timeout=TIMEOUT)
        if not sent:
            return "next"
        wave = WaveInput(
            organisation_id=input.organisation_id, batch_id=input.batch_id, offer_ids=sent
        )
        handled: set[str] = set()
        for _round in range(MAX_ROUNDS):
            state = await workflow.execute_activity(
                wave_state, wave, start_to_close_timeout=TIMEOUT
            )
            if self.cancelled or state["batch"] in ("filled", "exhausted", "cancelled"):
                return "closed"
            fresh = [o for o in state["accepted"] if o not in handled]
            if fresh:
                offer = OfferInput(
                    organisation_id=input.organisation_id,
                    batch_id=input.batch_id,
                    offer_id=fresh[0],
                )
                handled.add(fresh[0])
                if input.admin_confirms:
                    await workflow.execute_activity(
                        request_confirmation, offer, start_to_close_timeout=TIMEOUT
                    )
                    seen = self.decisions
                    try:
                        await workflow.wait_condition(
                            lambda seen=seen: self.cancelled or self.decisions != seen,  # type: ignore[misc]
                            timeout=CONFIRM_WAIT,
                        )
                    except TimeoutError:
                        handled.discard(offer.offer_id)  # still unconfirmed: ask again
                        continue
                    state = await workflow.execute_activity(
                        wave_state, wave, start_to_close_timeout=TIMEOUT
                    )
                    if offer.offer_id not in state["confirmed"]:
                        continue
                result = await workflow.execute_activity(
                    fill_offer, offer, start_to_close_timeout=TIMEOUT
                )
                if result in ("filled", "closed"):
                    return result
                continue
            if not state["pending"]:
                return "next"
            remaining = deadline - workflow.now()
            if remaining <= timedelta(0):
                await workflow.execute_activity(expire_wave, wave, start_to_close_timeout=TIMEOUT)
                return "next"
            seen = self.answers
            try:
                await workflow.wait_condition(
                    lambda seen=seen: self.cancelled or self.answers != seen,  # type: ignore[misc]
                    timeout=remaining,
                )
            except TimeoutError:
                await workflow.execute_activity(expire_wave, wave, start_to_close_timeout=TIMEOUT)
                state = await workflow.execute_activity(
                    wave_state, wave, start_to_close_timeout=TIMEOUT
                )
                if not [o for o in state["accepted"] if o not in handled]:
                    return "next"
        return "next"

    @workflow.run
    async def run(self, input: CascadeInput) -> str:
        waves = await workflow.execute_activity(plan_offers, input, start_to_close_timeout=TIMEOUT)
        for offer_ids in waves:
            if self.cancelled:
                break
            outcome = await self._wave(input, offer_ids)
            if outcome in ("filled", "closed"):
                await report_step(input, outcome, status="completed")
                return outcome
        if self.cancelled:
            await report_step(input, "cancelled", status="completed")
            return "cancelled"
        await workflow.execute_activity(exhaust_offers, input, start_to_close_timeout=TIMEOUT)
        await report_step(input, "exhausted", status="completed")
        return "exhausted"


@register_workflow(process=COVER_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class CoverRequestWorkflow:
    def __init__(self) -> None:
        self.closed = False

    @workflow.signal(name="accepted")
    def accepted(self) -> None:
        self.closed = True

    @workflow.signal(name="cancelled")
    def cancel(self) -> None:
        self.closed = True

    @workflow.run
    async def run(self, input: CoverInput) -> str:
        notified = await workflow.execute_activity(
            notify_cover, input, start_to_close_timeout=TIMEOUT
        )
        remaining = datetime.fromisoformat(input.deadline) - workflow.now()
        if notified and remaining > timedelta(0) and not self.closed:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.closed, timeout=remaining)
        if self.closed:
            await report_step(input, "closed", status="completed")
            return "closed"
        result = await workflow.execute_activity(
            cover_unfilled, input, start_to_close_timeout=TIMEOUT
        )
        outcome = "unfilled" if result else "closed"
        await report_step(input, outcome, status="completed")
        return outcome
