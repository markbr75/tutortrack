"""Webhook delivery on Temporal (E27-TW1).

``WebhookDeliveryWorkflow`` ``webhook-delivery:{org}:{delivery}``: started when a delivery is
created (an event matched an endpoint, a test event, or a manual redelivery). It POSTs the
signed payload; on failure it waits with exponential backoff and tries again, 15 attempts
over roughly 72 hours, then marks the delivery failed. Each attempt is recorded in the
delivery log with the workflow's clock, so the log shows the real intervals. The signal
``retry_now`` (the "retry now" button) cuts the current wait short. An endpoint that is
paused, disabled (3 days of continuous failure) or deleted ends the workflow as cancelled.
This replaces a ``next_attempt_at`` column and a sweeper (CLAUDE.md 4a).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

PROCESS = "webhook-delivery"
TIMEOUT = timedelta(minutes=1)
# Waits between attempts: 15 attempts spread over ~72 hours.
RETRY_DELAYS = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=4),
    timedelta(hours=6),
    timedelta(hours=8),
    timedelta(hours=10),
    timedelta(hours=12),
    timedelta(hours=14),
    timedelta(hours=15),
)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))


def delivery_workflow_id(org: object, delivery_id: object) -> str:
    return workflow_id(PROCESS, org, delivery_id)


@dataclass(frozen=True, kw_only=True)
class DeliveryInput(WorkflowInput):
    delivery_id: str


@dataclass(frozen=True, kw_only=True)
class AttemptInput(WorkflowInput):
    delivery_id: str
    number: int
    attempted_at: str  # the workflow's clock (ISO), for the delivery log


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def attempt_delivery(input: AttemptInput) -> str:
    """One HTTP attempt. Returns ``succeeded``, ``retry`` or ``cancelled``."""
    from datetime import datetime

    from . import services

    return services.attempt_delivery(
        input.delivery_id, input.number, datetime.fromisoformat(input.attempted_at)
    )


@tenant_activity
def give_up_delivery(input: DeliveryInput) -> bool:
    from . import services

    return services.give_up(input.delivery_id)


# --- workflow -----------------------------------------------------------------------------------


@register_workflow(
    process=PROCESS, task_queue="default", cancel_permission="developer.webhook.manage"
)
@workflow.defn
class WebhookDeliveryWorkflow:
    def __init__(self) -> None:
        self.nudges = 0
        self.attempts = 0

    @workflow.signal(name="retry_now")
    def retry_now(self) -> None:
        self.nudges += 1

    @workflow.query
    def state(self) -> dict[str, int]:
        return {"attempts": self.attempts}

    @workflow.run
    async def run(self, input: DeliveryInput) -> str:
        for number in range(1, MAX_ATTEMPTS + 1):
            self.attempts = number
            outcome = await workflow.execute_activity(
                attempt_delivery,
                AttemptInput(
                    organisation_id=input.organisation_id,
                    delivery_id=input.delivery_id,
                    number=number,
                    attempted_at=workflow.now().isoformat(),
                ),
                start_to_close_timeout=TIMEOUT,
                retry_policy=ACTIVITY_RETRY,
            )
            if outcome in ("succeeded", "cancelled"):
                await report_step(input, outcome, status="completed")
                return outcome
            if number == MAX_ATTEMPTS:
                break
            await report_step(input, f"retry-{number}")
            seen = self.nudges
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda seen=seen: self.nudges != seen,  # type: ignore[misc]
                    timeout=RETRY_DELAYS[number - 1],
                )
        await workflow.execute_activity(
            give_up_delivery, input, start_to_close_timeout=TIMEOUT, retry_policy=ACTIVITY_RETRY
        )
        await report_step(input, "failed", status="completed")
        return "failed"
