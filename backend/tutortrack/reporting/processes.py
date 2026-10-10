"""Scheduled report delivery on Temporal (E26-T07, FR-26-4).

``ScheduledReportWorkflow`` is started by each scheduled report's Temporal Schedule (cron in
the organisation's timezone; the run's workflow id is ``scheduled-report:{org}:{id}-<time>``).
It generates the file as the report's owner (retried), then emails it to the recipients
(retried). If either keeps failing the run is marked failed (``report_run.failed``) instead of
the workflow failing, so the next scheduled run still happens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import (
    WorkflowInput,
    idempotency_key,
    register_workflow,
    tenant_activity,
)

PROCESS = "scheduled-report"
RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30), backoff_coefficient=2.0, maximum_attempts=3
)


@dataclass(frozen=True, kw_only=True)
class ScheduledReportInput(WorkflowInput):
    scheduled_id: str


@dataclass(frozen=True, kw_only=True)
class RunInput(WorkflowInput):
    scheduled_id: str
    run_key: str
    run_id: str = ""
    error: str = ""


# --- activities ---------------------------------------------------------------------------------


@tenant_activity
def generate_report(input: RunInput) -> str:
    from . import services

    return services.generate_scheduled_run(input.scheduled_id, input.run_key)


@tenant_activity
def deliver_report(input: RunInput) -> int:
    from . import services

    return services.deliver_run(input.run_id, dedupe_key=idempotency_key())


@tenant_activity
def fail_report(input: RunInput) -> str:
    from . import services

    return services.fail_run(
        input.scheduled_id, input.run_key, input.error, dedupe_key=idempotency_key()
    )


# --- workflow -----------------------------------------------------------------------------------


@register_workflow(
    process=PROCESS, task_queue="default", cancel_permission="reporting.schedule.manage"
)
@workflow.defn
class ScheduledReportWorkflow:
    def __init__(self) -> None:
        self.step = "starting"

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    @workflow.run
    async def run(self, input: ScheduledReportInput) -> str:
        base = RunInput(
            organisation_id=input.organisation_id,
            scheduled_id=input.scheduled_id,
            run_key=workflow.info().workflow_id,
        )
        self.step = "generating"
        try:
            run_id = await workflow.execute_activity(
                generate_report,
                base,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RETRY,
            )
        except ActivityError as exc:
            return await self._fail(base, exc)
        if not run_id:
            self.step = "skipped"
            return "skipped"
        self.step = "delivering"
        delivery = RunInput(
            organisation_id=input.organisation_id,
            scheduled_id=input.scheduled_id,
            run_key=base.run_key,
            run_id=run_id,
        )
        try:
            sent = await workflow.execute_activity(
                deliver_report,
                delivery,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RETRY,
            )
        except ActivityError as exc:
            return await self._fail(base, exc)
        self.step = "delivered"
        return f"delivered:{sent}"

    async def _fail(self, base: RunInput, exc: ActivityError) -> str:
        self.step = "failed"
        failed = RunInput(
            organisation_id=base.organisation_id,
            scheduled_id=base.scheduled_id,
            run_key=base.run_key,
            error=str(exc.cause or exc)[:500],
        )
        await workflow.execute_activity(
            fail_report, failed, start_to_close_timeout=timedelta(minutes=1)
        )
        return "failed"
