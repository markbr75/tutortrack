"""Temporal workflows for automations (E14-TW1).

* ``AutomationRunWorkflow`` ``automation:{org}:{automation}:{subject}:{key}``: interprets
  the run's automation version. Actions are activities (``execute_step``, idempotent per
  run and step); **wait** steps are durable timers; **branch** steps evaluate their
  condition against the record as it is then and continue down one arm. The run log is the
  ``AutomationRunStep`` rows the activities write. ``start_at`` resumes a retried run at a
  top-level step.
* ``AutomationScheduleWorkflow``: started by the automation's Temporal Schedule (schedule
  and date triggers); one activity picks the records and starts a run for each.
"""

from __future__ import annotations

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

    services.finish(input.run_id, input.status, input.error)


@tenant_activity
def fan_out(input: ScheduleInput) -> int:
    from . import services

    return services.fan_out(input.automation_id)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=RUN_PROCESS, task_queue="default", cancel_permission="automation.manage")
@workflow.defn
class AutomationRunWorkflow:
    async def _steps(
        self, input: RunInput, steps: list[dict[str, Any]], prefix: str, start_at: int = 0
    ) -> str:
        for index, step in enumerate(steps):
            if index < start_at:
                continue
            key = f"{prefix}{index}"
            si = StepInput(organisation_id=input.organisation_id, run_id=input.run_id, key=key,
                           step=step, now=workflow.now().isoformat())  # fmt: skip
            kind = step.get("type")
            if kind == "action":
                result = await workflow.execute_activity(
                    execute_step, si, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
                )
                if result.get("status") == "failed":
                    return "failed"
            elif kind == "wait":
                until = await workflow.execute_activity(
                    start_wait, si, start_to_close_timeout=TIMEOUT
                )
                delay = datetime.fromisoformat(until) - workflow.now()
                if delay > timedelta(0):
                    await workflow.sleep(delay)
                await workflow.execute_activity(end_wait, si, start_to_close_timeout=TIMEOUT)
            elif kind == "branch":
                matched = await workflow.execute_activity(
                    evaluate_branch, si, start_to_close_timeout=TIMEOUT
                )
                arm = "then" if matched else "else"
                outcome = await self._steps(input, step.get(arm) or [], f"{key}.{arm}.")
                if outcome == "failed":
                    return "failed"
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
                        status=outcome, error=error),
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
