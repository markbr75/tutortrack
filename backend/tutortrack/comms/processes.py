"""Temporal workflow for broadcasts (E13-TW1).

``BroadcastWorkflow`` ``broadcast:{org}:{broadcast}``: started by ``broadcast.scheduled``.
Waits for the scheduled time, resolves the segment into recipients (consent,
preferences and suppressions applied once), then queues throttled batches
(``comms.broadcast_batch_size`` every ``comms.broadcast_batch_pause_seconds``; each
message is handed to the Celery send task) and records the final statistics. Texts and
WhatsApp messages wait for the end of quiet hours. Signals: ``pause``, ``resume`` and
``cancel`` (from the API through the services). Replaces a scheduled-broadcast beat job.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import WorkflowInput, register_workflow, tenant_activity
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
MAX_BATCHES = 5000
MAX_QUIET_WAITS = 60  # a guard: each wait lasts until quiet hours end
LIVE = ("scheduled", "sending", "paused")


@dataclass(frozen=True, kw_only=True)
class BroadcastInput(WorkflowInput):
    broadcast_id: str


@dataclass(frozen=True, kw_only=True)
class BroadcastClock(WorkflowInput):
    broadcast_id: str
    at: str  # the workflow's time (ISO), so quiet hours follow workflow time


@dataclass(frozen=True, kw_only=True)
class BroadcastBatch(WorkflowInput):
    broadcast_id: str
    batch: int


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def broadcast_state(input: BroadcastInput) -> dict[str, Any]:
    from . import broadcasts

    return broadcasts.state(input.broadcast_id)


@tenant_activity
def resolve_broadcast_recipients(input: BroadcastInput) -> int:
    from . import broadcasts

    return broadcasts.resolve_recipients(input.broadcast_id)


@tenant_activity
def broadcast_quiet_wait(input: BroadcastClock) -> int:
    from . import broadcasts

    return broadcasts.quiet_wait_seconds(input.broadcast_id, at=datetime.fromisoformat(input.at))


@tenant_activity
def send_broadcast_batch(input: BroadcastBatch) -> dict[str, int]:
    from . import broadcasts

    return broadcasts.send_batch(input.broadcast_id, input.batch)


@tenant_activity
def finish_broadcast(input: BroadcastInput) -> str:
    from . import broadcasts

    return broadcasts.finish(input.broadcast_id)


# --- workflow -----------------------------------------------------------------------------------


@register_workflow(
    process="broadcast", task_queue="default", cancel_permission="comms.broadcast.send"
)
@workflow.defn
class BroadcastWorkflow:
    def __init__(self) -> None:
        self.paused = False
        self.cancelled = False
        self.batches = 0
        self.quiet_waits = 0

    @workflow.signal(name="pause")
    def pause(self) -> None:
        self.paused = True

    @workflow.signal(name="resume")
    def resume(self) -> None:
        self.paused = False

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"paused": self.paused, "cancelled": self.cancelled, "batches": self.batches}

    async def _sleep(self, delay: timedelta) -> None:
        """Wait, unless cancelled first."""
        if delay > timedelta(0) and not self.cancelled:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.cancelled, timeout=delay)

    async def _while_paused(self, input: BroadcastInput) -> None:
        if self.paused and not self.cancelled:
            await report_step(input, "paused")
            await workflow.wait_condition(lambda: not self.paused or self.cancelled)
            if not self.cancelled:
                await report_step(input, "sending")

    async def _state(self, input: BroadcastInput) -> dict[str, Any]:
        found: dict[str, Any] = await workflow.execute_activity(
            broadcast_state, input, start_to_close_timeout=TIMEOUT
        )
        return found

    async def _end(self, input: BroadcastInput, outcome: str) -> str:
        await report_step(input, outcome, status="completed")
        return outcome

    @workflow.run
    async def run(self, input: BroadcastInput) -> str:
        state = await self._state(input)
        if state["status"] not in LIVE:
            return await self._end(input, str(state["status"]))
        self.paused = state["status"] == "paused"
        if state["scheduled_for"]:
            await report_step(input, "waiting")
            await self._sleep(datetime.fromisoformat(state["scheduled_for"]) - workflow.now())
        await self._while_paused(input)
        if self.cancelled:
            return await self._end(input, "cancelled")
        remaining = await workflow.execute_activity(
            resolve_broadcast_recipients, input, start_to_close_timeout=TIMEOUT
        )
        await report_step(input, "sending")
        pause = timedelta(seconds=int(state.get("pause_seconds") or 0))
        while remaining > 0 and self.batches < MAX_BATCHES:
            await self._while_paused(input)
            if self.cancelled:
                break
            clock = BroadcastClock(
                organisation_id=input.organisation_id,
                broadcast_id=input.broadcast_id,
                at=workflow.now().isoformat(),
            )
            quiet = await workflow.execute_activity(
                broadcast_quiet_wait, clock, start_to_close_timeout=TIMEOUT
            )
            if quiet > 0 and self.quiet_waits < MAX_QUIET_WAITS:
                self.quiet_waits += 1
                await report_step(input, "quiet_hours")
                await self._sleep(timedelta(seconds=quiet))
                continue
            self.batches += 1
            batch = BroadcastBatch(
                organisation_id=input.organisation_id,
                broadcast_id=input.broadcast_id,
                batch=self.batches,
            )
            result = await workflow.execute_activity(
                send_broadcast_batch, batch, start_to_close_timeout=TIMEOUT
            )
            remaining = int(result["remaining"])
            if not result["status"]:  # not sending in the database: a signal is on its way
                current = await self._state(input)
                if current["status"] == "cancelled":
                    self.cancelled = True
                elif current["status"] == "paused":
                    self.paused = True
                elif current["status"] not in LIVE:
                    break
                continue
            if remaining > 0:
                await self._sleep(pause)
        if self.cancelled:
            return await self._end(input, "cancelled")
        outcome = await workflow.execute_activity(
            finish_broadcast, input, start_to_close_timeout=TIMEOUT
        )
        return await self._end(input, str(outcome))
