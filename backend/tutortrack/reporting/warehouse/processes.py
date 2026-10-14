"""``WarehouseExportWorkflow`` (E26-T09).

Started nightly by the destination's Temporal Schedule (id ``warehouse-export:{org}:
{destination}-<time>``) or from "Export now" (``warehouse-export:{org}:{destination}:
<stamp>``): open the run → export each dataset (one activity each, retried with backoff
so a warehouse outage only delays the run) → finish (manifest, watermark). A run whose
datasets keep failing is marked failed; the next run starts from the last successful
watermark, so nothing is lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=30)
PROCESS = "warehouse-export"
RETRY = RetryPolicy(
    initial_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=30),
    maximum_attempts=6,
)


def export_workflow_id(org: object, destination_id: object, stamp: object) -> str:
    return workflow_id(PROCESS, org, destination_id, stamp)


@dataclass(frozen=True, kw_only=True)
class WarehouseExportInput(WorkflowInput):
    destination_id: str
    full: bool = False
    scheduled: bool = False
    requested_by: str = ""


@dataclass(frozen=True, kw_only=True)
class DatasetInput(WorkflowInput):
    export_id: str
    dataset: str


@dataclass(frozen=True, kw_only=True)
class ExportRunInput(WorkflowInput):
    export_id: str
    error: str = ""


@tenant_activity
def begin_warehouse_export(input: WarehouseExportInput) -> dict[str, Any]:
    from . import services

    run_key = str(activity.info().workflow_id or "")
    return services.begin(
        input.destination_id,
        run_key,
        full=input.full,
        scheduled=input.scheduled,
        requested_by=input.requested_by,
    )


@tenant_activity
def export_warehouse_dataset(input: DatasetInput) -> int:
    from . import services

    return int(services.export_dataset(input.export_id, input.dataset)["rows"])


@tenant_activity
def finish_warehouse_export(input: ExportRunInput) -> str:
    from . import services

    return services.finish(input.export_id)


@tenant_activity
def fail_warehouse_export(input: ExportRunInput) -> str:
    from . import services

    return services.fail(input.export_id, input.error)


@register_workflow(process=PROCESS, task_queue="default", cancel_permission="reporting.manage")
@workflow.defn
class WarehouseExportWorkflow:
    @workflow.run
    async def run(self, input: WarehouseExportInput) -> str:
        opened = await workflow.execute_activity(
            begin_warehouse_export, input, start_to_close_timeout=timedelta(minutes=5)
        )
        if "skipped" in opened:
            result = f"skipped:{opened['skipped']}"
            await report_step(input, result, status="completed")
            return result
        export_id = str(opened["export"])
        rows = 0
        failed = ""
        for dataset in opened["datasets"]:
            try:
                rows += await workflow.execute_activity(
                    export_warehouse_dataset,
                    DatasetInput(
                        organisation_id=input.organisation_id, export_id=export_id, dataset=dataset
                    ),
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=RETRY,
                )
            except ActivityError as exc:
                failed = f"{dataset}: {exc.cause or exc}"[:400]
                break
        run_input = ExportRunInput(
            organisation_id=input.organisation_id, export_id=export_id, error=failed
        )
        if failed:
            await workflow.execute_activity(
                fail_warehouse_export, run_input, start_to_close_timeout=timedelta(minutes=5)
            )
            await report_step(input, "failed", status="completed")
            return "failed"
        await workflow.execute_activity(
            finish_warehouse_export, run_input, start_to_close_timeout=timedelta(minutes=5)
        )
        await report_step(input, f"exported:{rows}", status="completed")
        return f"exported:{rows}"
