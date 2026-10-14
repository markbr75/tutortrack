"""The platform insights run as a platform Temporal Schedule (E30-TW1 Part 2), and starting
it on demand from the console."""

from __future__ import annotations

import contextlib
from datetime import date

from tutortrack.core.time import now
from tutortrack.core.workflows import runtime
from tutortrack.core.workflows.schedules import ensure_platform_schedule

from .processes import INSIGHTS_PROCESS, InsightsInput, PlatformInsightsWorkflow

CRON = ["30 3 * * *"]  # 03:30 UTC, after the tenants' 02:00 local retention runs in Europe


def ensure_insights_schedule() -> str:
    return ensure_platform_schedule(
        process=INSIGHTS_PROCESS,
        workflow=PlatformInsightsWorkflow,
        input=InsightsInput(),
        cron=CRON,
    )


def run_now(day: date | None = None) -> str:
    """Start a run for ``day`` (default today, UTC) and return its workflow id. Rows are
    replaced per organisation and day, so a second run for the same day is harmless."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from tutortrack.core.workflows.client import get_client
    from tutortrack.core.workflows.ops import process_info

    day = day or now().date()
    workflow_id = f"{INSIGHTS_PROCESS}:platform:manual-{day.isoformat()}-{now():%H%M%S}"
    info = process_info(PlatformInsightsWorkflow)

    async def _start() -> None:
        client = await get_client()
        with contextlib.suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                PlatformInsightsWorkflow.run,
                InsightsInput(day=day.isoformat()),
                id=workflow_id,
                task_queue=info.task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )

    runtime.run(_start())
    return workflow_id
