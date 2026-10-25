"""Temporal workflows for automations (E14-TW1).

* ``AutomationRunWorkflow`` ``automation:{org}:{automation}:{subject}:{key}``: interprets
  the run's automation version. Actions are activities (``execute_step``, idempotent per
  run and step); **wait** steps are durable timers; **branch** steps evaluate their
  condition against the record as it is then and continue down one arm. The run log is the
  ``AutomationRunStep`` rows the activities write. ``start_at`` resumes a retried run at a
  top-level step.
* ``AutomationScheduleWorkflow``: started by the automation's Temporal Schedule (schedule
  and date triggers); one activity picks the records and starts a run for each.

E33 (patch ``stop-when``): the ``stop`` signal (sent when a stop-when event arrives for the
run's record) ends the run before its next step, waking it from a wait. Actions with an
"only if" that no longer holds are skipped by ``execute_step``; waits can count from a date
on the record, end at a time of day, on a business day or outside quiet hours
(``services.start_wait``).

E33 T02: a paused workflow's runs hold before their next action (``execute_step`` answers
``paused``) until the ``resume`` signal, re-checking every few hours in case it was missed.
Only runs that meet a pause take the new path, so older histories replay unchanged.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import WorkflowInput, register_workflow, tenant_activity
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
RETRY = RetryPolicy(maximum_attempts=5)
STOP_WHEN = "stop-when"  # workflow.patched id (E33 T01)
PAUSE_RECHECK = timedelta(hours=6)
RUN_PROCESS = "automation"
SCHEDULE_PROCESS = "automation-schedule"


@dataclass(frozen=True, kw_only=True)
class RunInput(WorkflowInput):
    run_id: str
    start_at: int = 0


@dataclass(frozen=True, kw_only=True)
class StepInput(WorkflowInput):
    run_id: str
    key: str
    step: dict[str, Any]
    now: str = ""


@dataclass(frozen=True, kw_only=True)
class FinishInput(WorkflowInput):
    run_id: str
    status: str
    error: str = ""
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class ScheduleInput(WorkflowInput):
    automation_id: str


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def load_plan(input: RunInput) -> list[dict[str, Any]]:
    from . import services

    return services.load_plan(input.run_id)


@tenant_activity
def execute_step(input: StepInput) -> dict[str, Any]:
    from . import services

    return services.execute_step(input.run_id, input.key, input.step)


@tenant_activity
def evaluate_branch(input: StepInput) -> bool:
    from . import services

    return services.evaluate_branch(input.run_id, input.key, input.step.get("if") or {})


@tenant_activity
def start_wait(input: StepInput) -> str:
    from . import services

    return services.start_wait(input.run_id, input.key, input.step, input.now)


@tenant_activity
def end_wait(input: StepInput) -> None:
    from . import services

    services.end_wait(input.run_id, input.key)


@tenant_activity
def finish_run(input: FinishInput) -> None:
    from . import services

    services.finish(input.run_id, input.status, input.error, input.reason)


@tenant_activity
def fan_out(input: ScheduleInput) -> int:
    from . import services

    return services.fan_out(input.automation_id)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=RUN_PROCESS, task_queue="default", cancel_permission="automation.manage")
@workflow.defn
class AutomationRunWorkflow:
    def __init__(self) -> None:
        self._stop_reason = ""
        self._resumed = False

    @workflow.signal
    def stop(self, reason: str = "") -> None:
        """A stop-when event arrived for the run's record (E33)."""
        self._stop_reason = reason or "stopped"

    @workflow.signal
    def resume(self) -> None:
        """The workflow was resumed: a held run carries on (E33)."""
        self._resumed = True

    async def _wait(self, delay: timedelta) -> None:
        if delay <= timedelta(0):
            return
        if not workflow.patched(STOP_WHEN):
            await workflow.sleep(delay)  # runs started before stop-when: as they were
            return
        with contextlib.suppress(TimeoutError):  # the time came
            await workflow.wait_condition(lambda: bool(self._stop_reason), timeout=delay)

    async def _steps(
        self, input: RunInput, steps: list[dict[str, Any]], prefix: str, start_at: int = 0
    ) -> str:
        for index, step in enumerate(steps):
            if index < start_at:
                continue
            if self._stop_reason:
                return "stopped"
            key = f"{prefix}{index}"
            si = StepInput(organisation_id=input.organisation_id, run_id=input.run_id, key=key,
                           step=step, now=workflow.now().isoformat())  # fmt: skip
            kind = step.get("type")
            if kind == "action":
                self._resumed = False
                result = await workflow.execute_activity(
                    execute_step, si, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
                )
                while result.get("status") == "paused":
                    with contextlib.suppress(TimeoutError):
                        await workflow.wait_condition(
                            lambda: self._resumed or bool(self._stop_reason),
                            timeout=PAUSE_RECHECK,
                        )
                    if self._stop_reason:
                        return "stopped"
                    self._resumed = False
                    result = await workflow.execute_activity(
                        execute_step, si, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
                    )
                if result.get("status") == "failed":
                    return "failed"
            elif kind == "wait":
                until = await workflow.execute_activity(
                    start_wait, si, start_to_close_timeout=TIMEOUT
                )
                await self._wait(datetime.fromisoformat(until) - workflow.now())
                if self._stop_reason:
                    return "stopped"
                await workflow.execute_activity(end_wait, si, start_to_close_timeout=TIMEOUT)
            elif kind == "branch":
                matched = await workflow.execute_activity(
                    evaluate_branch, si, start_to_close_timeout=TIMEOUT
                )
                arm = "then" if matched else "else"
                outcome = await self._steps(input, step.get(arm) or [], f"{key}.{arm}.")
                if outcome in ("failed", "stopped"):
                    return outcome
        return "completed"

    @workflow.run
    async def run(self, input: RunInput) -> str:
        steps = await workflow.execute_activity(load_plan, input, start_to_close_timeout=TIMEOUT)
        error = ""
        try:
            outcome = await self._steps(input, steps, "", input.start_at)
        except ActivityError as exc:  # an action kept failing unexpectedly
            outcome, error = "failed", str(exc.cause or exc)[:500]
        await workflow.execute_activity(
            finish_run,
            FinishInput(organisation_id=input.organisation_id, run_id=input.run_id,
                        status=outcome, error=error, reason=self._stop_reason),
            start_to_close_timeout=TIMEOUT,
        )  # fmt: skip
        await report_step(input, outcome, status="completed")
        return outcome


@register_workflow(process=SCHEDULE_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class AutomationScheduleWorkflow:
    @workflow.run
    async def run(self, input: ScheduleInput) -> int:
        started: int = await workflow.execute_activity(
            fan_out, input, start_to_close_timeout=timedelta(minutes=30)
        )
        return started
