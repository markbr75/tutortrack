"""Keeping ``WorkflowLink`` current from inside workflows (E32 §5, FR-32-5 timelines).

await report_step(input, "waiting_for_payment")
...
await report_step(input, "", status="completed")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from temporalio import workflow

from .activity import WorkflowInput, tenant_activity


@dataclass(frozen=True, kw_only=True)
class LinkUpdate(WorkflowInput):
    workflow_id: str
    step: str = ""
    status: str = "running"
    error: str = ""


@tenant_activity
def update_link(update: LinkUpdate) -> None:
    from ..models import WorkflowLink

    changes: dict[str, object] = {"current_step": update.step[:60], "status": update.status}
    if update.status != "running":
        changes["closed_at"] = datetime.now(UTC)
    if update.error:
        changes["last_error"] = update.error[:4000]
    WorkflowLink.objects.filter(workflow_id=update.workflow_id).update(**changes)


async def report_step(input: WorkflowInput, step: str, *, status: str = "running") -> None:
    """Record the workflow's current step (or final status) for the process timeline."""
    await workflow.execute_activity(
        update_link,
        LinkUpdate(
            organisation_id=input.organisation_id,
            workflow_id=workflow.info().workflow_id,
            step=step,
            status=status,
        ),
        start_to_close_timeout=timedelta(seconds=30),
    )
