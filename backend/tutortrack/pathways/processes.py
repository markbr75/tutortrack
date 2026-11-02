"""``PathwayRunWorkflow`` ``pathway:{org}:{run}`` (E34 FR-34-1, T01): the clock of one run.

The run's state lives in ``services``: finishing a step moves the run on straight away and
signals ``changed``. The workflow calls ``tick`` (reminders, overdue notices, re-checking
system steps) and sleeps until the next time ``tick`` asks for, or until a change. It ends
when the run is completed, turned down or cancelled. Long runs continue as new after
``MAX_ROUNDS`` wake-ups to keep the history small.
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

PROCESS = "pathway"
TIMEOUT = timedelta(minutes=5)
MAX_ROUNDS = 200


def run_workflow_id(organisation_id: object, run_id: object) -> str:
    return workflow_id(PROCESS, organisation_id, run_id)


@dataclass(frozen=True, kw_only=True)
class PathwayRunInput(WorkflowInput):
    run_id: str


@dataclass(frozen=True, kw_only=True)
class TickInput(WorkflowInput):
    run_id: str
    at: str  # the workflow's time, so reminders agree with the timers that fire them


@tenant_activity
def tick_run(input: TickInput) -> dict[str, Any]:
    from . import services

    return services.tick(input.run_id, at=datetime.fromisoformat(input.at))


@register_workflow(process=PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class PathwayRunWorkflow:
    def __init__(self) -> None:
        self.changes = 0
        self.stage = ""

    @workflow.signal(name="changed")
    def changed(self) -> None:
        self.changes += 1

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"stage": self.stage}

    @workflow.run
    async def run(self, input: PathwayRunInput) -> str:
        for _round in range(MAX_ROUNDS):
            seen = self.changes  # read before the activity: a signal mid-activity still counts
            tick = TickInput(
                organisation_id=input.organisation_id,
                run_id=input.run_id,
                at=workflow.now().isoformat(),
            )
            state = await workflow.execute_activity(tick_run, tick, start_to_close_timeout=TIMEOUT)
            if state["finished"]:
                await report_step(input, state["status"], status="completed")
                return str(state["status"])
            if state["stage"] != self.stage:
                self.stage = state["stage"]
                await report_step(input, self.stage)
            timeout: timedelta | None = None
            if state["wake_at"]:
                timeout = max(
                    datetime.fromisoformat(state["wake_at"]) - workflow.now(), timedelta(seconds=1)
                )
            await self._wait_for_change(seen, timeout)
        workflow.continue_as_new(input)

    async def _wait_for_change(self, seen: int, timeout: timedelta | None) -> None:
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(lambda: self.changes != seen, timeout=timeout)
