"""Temporal workflows for imports, migrations and exports (E28-TW1).

* ``ImportWorkflow`` ``import:{org}:{batch}``: started by ``import.submitted`` (mapping
  done). Validates and dry-runs, then waits for the user: signal ``confirm`` imports,
  ``revalidate`` (mapping changed) checks again, ``cancel`` stops. Rows are imported in
  checkpointed chunks (each chunk an activity; applied rows are marked in the same
  savepoint, so a retried chunk skips them). Then the report, and the **rollback window
  timer**: signal ``rollback`` reverts the batch; the timer's expiry finalises it.
* ``MigrationProjectWorkflow`` ``migration:{org}:{project}``: started by
  ``migration_project.started``. Runs the cutover steps in order: each step pulls the
  source's records into import batches (API sources) and waits for the user to confirm it
  (signal ``step_done`` with the step) before the next; then the reconciliation report.
  Signal ``cancel`` stops it.
* ``TenantExportWorkflow`` ``tenant-export:{org}:{export}``: started by ``export.requested``
  (owner, account closure, platform). Exports entity by entity (checkpointed), zips, emails
  the link, then waits until the link expires (7 days by default) and deletes the file.
  Signal ``cancel`` stops it and deletes what was made.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import WorkflowInput, register_workflow, tenant_activity, workflow_id
from tutortrack.core.workflows.links import report_step

IMPORT_PROCESS = "import"
PROJECT_PROCESS = "migration"
EXPORT_PROCESS = "tenant-export"
QUEUE = "imports"
CHUNK = 250
SHORT = timedelta(minutes=5)
LONG = timedelta(minutes=30)
HEARTBEAT = timedelta(minutes=2)
CONFIRM_WAIT = timedelta(days=14)
STEP_WAIT = timedelta(days=60)
RETRIES = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=2))


def import_workflow_id(org: object, batch_id: object) -> str:
    return workflow_id(IMPORT_PROCESS, org, batch_id)


def project_workflow_id(org: object, project_id: object) -> str:
    return workflow_id(PROJECT_PROCESS, org, project_id)


def export_workflow_id(org: object, export_id: object) -> str:
    return workflow_id(EXPORT_PROCESS, org, export_id)


@dataclass(frozen=True, kw_only=True)
class BatchInput(WorkflowInput):
    batch_id: str


@dataclass(frozen=True, kw_only=True)
class ChunkInput(WorkflowInput):
    batch_id: str
    row: int
    size: int = CHUNK


@dataclass(frozen=True, kw_only=True)
class StopInput(WorkflowInput):
    batch_id: str
    status: str
    error: str = ""


@dataclass(frozen=True, kw_only=True)
class ProjectInput(WorkflowInput):
    project_id: str


@dataclass(frozen=True, kw_only=True)
class StepInput(WorkflowInput):
    project_id: str
    step: str


@dataclass(frozen=True, kw_only=True)
class ExportInput(WorkflowInput):
    export_id: str


@dataclass(frozen=True, kw_only=True)
class EntityInput(WorkflowInput):
    export_id: str
    entity: str


@dataclass(frozen=True, kw_only=True)
class ExportEndInput(WorkflowInput):
    export_id: str
    status: str = "expired"
    error: str = ""


def _beat(detail: Any = None) -> None:
    activity.heartbeat(detail)


# --- import activities --------------------------------------------------------------------------


@tenant_activity
def validate_import(input: BatchInput) -> dict[str, Any]:
    from . import services

    return services.validate(input.batch_id, heartbeat=_beat)


@tenant_activity
def begin_import(input: BatchInput) -> str:
    from . import services

    return services.start_import(input.batch_id)


@tenant_activity
def import_rows(input: ChunkInput) -> dict[str, Any]:
    from . import services

    return services.import_chunk(input.batch_id, input.row, input.size, heartbeat=_beat)


def _seconds_until(moment: Any) -> float:
    """Windows are measured from real time and waited for on the workflow's clock."""
    from tutortrack.core.time import now

    if moment is None:
        return 0.0
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    return max((moment - now()).total_seconds(), 0.0)


@tenant_activity
def finish_import(input: BatchInput) -> float:
    """Returns the rollback window in seconds."""
    from . import services

    return _seconds_until(services.finish_import(input.batch_id))


@tenant_activity
def stop_import(input: StopInput) -> None:
    from . import services

    if input.status == "cancelled_during_import":
        services.cancel_import(input.batch_id)
    else:
        services.finish_validation_only(input.batch_id, input.status, input.error)


@tenant_activity
def import_status(input: BatchInput) -> dict[str, Any]:
    from .models import ImportBatch

    batch = ImportBatch.objects.get(pk=input.batch_id)
    return {"status": str(batch.status), "seconds": _seconds_until(batch.rollback_until)}


@tenant_activity
def rollback_rows(input: ChunkInput) -> dict[str, Any]:
    from . import services

    return services.rollback_chunk(input.batch_id, input.row, input.size)


@tenant_activity
def finish_rollback(input: BatchInput) -> dict[str, int]:
    from . import services

    return services.finish_rollback(input.batch_id)


@tenant_activity
def finalise_import(input: BatchInput) -> bool:
    from . import services

    return services.finalise(input.batch_id)


# --- project activities -------------------------------------------------------------------------


@tenant_activity
def project_steps(input: ProjectInput) -> list[str]:
    from . import services
    from .models import MigrationProject

    project = MigrationProject.objects.get(pk=input.project_id)
    return [
        step
        for step in services.STEP_KEYS
        if (project.steps.get(step) or {}).get("status") not in ("done", "skipped")
    ]


@tenant_activity
def start_project_step(input: StepInput) -> list[str]:
    from . import services

    return services.start_step(input.project_id, input.step)


@tenant_activity
def step_finished(input: StepInput) -> bool:
    from .models import MigrationProject

    project = MigrationProject.objects.get(pk=input.project_id)
    return (project.steps.get(input.step) or {}).get("status") in ("done", "skipped")


@tenant_activity
def reconcile_project(input: ProjectInput) -> dict[str, Any]:
    from . import services

    return services.reconcile(input.project_id)


@tenant_activity
def expire_project(input: ProjectInput) -> None:
    from . import services

    services.expire_project(input.project_id)


# --- export activities --------------------------------------------------------------------------


@tenant_activity
def plan_export(input: ExportInput) -> list[str]:
    from . import services

    return services.export_plan(input.export_id)


@tenant_activity
def export_entity(input: EntityInput) -> int:
    from . import services

    return services.export_entity(input.export_id, input.entity)


@tenant_activity
def build_export(input: ExportInput) -> float:
    """Returns how long the download stays available, in seconds."""
    from . import services

    return _seconds_until(services.export_archive(input.export_id, heartbeat=_beat))


@tenant_activity
def end_export(input: ExportEndInput) -> None:
    from . import services

    services.expire_export(input.export_id, status=input.status, error=input.error)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=IMPORT_PROCESS, task_queue=QUEUE, cancel_permission=None)
@workflow.defn
class ImportWorkflow:
    def __init__(self) -> None:
        self.confirmed = False
        self.cancelled = False
        self.revalidations = 0
        self.rollback_requested = False

    @workflow.signal(name="confirm")
    def confirm(self) -> None:
        self.confirmed = True

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.signal(name="revalidate")
    def revalidate(self) -> None:
        self.revalidations += 1

    @workflow.signal(name="rollback")
    def rollback(self) -> None:
        self.rollback_requested = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"confirmed": self.confirmed, "cancelled": self.cancelled}

    async def _stop(self, input: BatchInput, status: str, error: str = "") -> str:
        await workflow.execute_activity(
            stop_import,
            StopInput(
                organisation_id=input.organisation_id,
                batch_id=input.batch_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=SHORT,
        )
        await report_step(input, status, status="completed")
        return status

    @workflow.run
    async def run(self, input: BatchInput) -> str:
        # 1. Validate and dry-run, then wait for the user.
        while True:
            seen = self.revalidations

            def decided(seen: int = seen) -> bool:
                return self.confirmed or self.cancelled or self.revalidations != seen

            await report_step(input, "validating")
            try:
                await workflow.execute_activity(
                    validate_import,
                    input,
                    start_to_close_timeout=LONG,
                    heartbeat_timeout=HEARTBEAT,
                    retry_policy=RETRIES,
                )
            except ActivityError as exc:
                return await self._stop(input, "failed", str(exc.cause or exc))
            await report_step(input, "awaiting_confirmation")
            try:
                await workflow.wait_condition(
                    decided,
                    timeout=CONFIRM_WAIT,
                )
            except TimeoutError:
                return await self._stop(input, "cancelled", "Not confirmed in time.")
            if self.cancelled:
                return await self._stop(input, "cancelled")
            if self.confirmed:
                break
        # 2. Import in checkpointed chunks.
        await workflow.execute_activity(begin_import, input, start_to_close_timeout=SHORT)
        await report_step(input, "importing")
        row = 0
        while True:
            if self.cancelled:  # what was imported stays (and can be rolled back)
                await workflow.execute_activity(
                    stop_import,
                    StopInput(
                        organisation_id=input.organisation_id,
                        batch_id=input.batch_id,
                        status="cancelled_during_import",
                    ),
                    start_to_close_timeout=LONG,
                )
                break
            try:
                result = await workflow.execute_activity(
                    import_rows,
                    ChunkInput(
                        organisation_id=input.organisation_id, batch_id=input.batch_id, row=row
                    ),
                    start_to_close_timeout=LONG,
                    heartbeat_timeout=HEARTBEAT,
                    retry_policy=RETRIES,
                )
            except ActivityError as exc:
                return await self._stop(input, "failed", str(exc.cause or exc))
            row = int(result["last_row"])
            if result["done"]:
                break
        current = await workflow.execute_activity(
            import_status, input, start_to_close_timeout=SHORT
        )
        if current["status"] == "importing":
            window = await workflow.execute_activity(
                finish_import, input, start_to_close_timeout=LONG, retry_policy=RETRIES
            )
        elif current["status"] == "completed":
            window = float(current["seconds"])
        else:
            await report_step(input, current["status"], status="completed")
            return current["status"]
        # 3. The rollback window.
        await report_step(input, "rollback_window")
        remaining = timedelta(seconds=window)
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.rollback_requested, timeout=remaining)
        if not self.rollback_requested:
            await workflow.execute_activity(finalise_import, input, start_to_close_timeout=SHORT)
            await report_step(input, "finalised", status="completed")
            return "finalised"
        await report_step(input, "rolling_back")
        before = 2**31 - 1
        while True:
            result = await workflow.execute_activity(
                rollback_rows,
                ChunkInput(
                    organisation_id=input.organisation_id, batch_id=input.batch_id, row=before
                ),
                start_to_close_timeout=LONG,
                retry_policy=RETRIES,
            )
            if result["done"]:
                break
            before = int(result["before_row"])
        await workflow.execute_activity(finish_rollback, input, start_to_close_timeout=SHORT)
        await report_step(input, "rolled_back", status="completed")
        return "rolled_back"


@register_workflow(process=PROJECT_PROCESS, task_queue=QUEUE, cancel_permission=None)
@workflow.defn
class MigrationProjectWorkflow:
    def __init__(self) -> None:
        self.done: list[str] = []
        self.cancelled = False

    @workflow.signal(name="step_done")
    def step_done(self, step: str) -> None:
        self.done.append(step)

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"done": list(self.done), "cancelled": self.cancelled}

    @workflow.run
    async def run(self, input: ProjectInput) -> str:
        steps = await workflow.execute_activity(project_steps, input, start_to_close_timeout=SHORT)
        for step in steps:
            step_input = StepInput(
                organisation_id=input.organisation_id, project_id=input.project_id, step=step
            )
            await report_step(input, step)
            await workflow.execute_activity(
                start_project_step,
                step_input,
                start_to_close_timeout=LONG,
                retry_policy=RetryPolicy(
                    maximum_attempts=8, initial_interval=timedelta(seconds=10)
                ),  # rate limits: back off and try again
            )
            while True:
                try:
                    await workflow.wait_condition(
                        lambda step=step: self.cancelled or step in self.done,  # type: ignore[misc]
                        timeout=STEP_WAIT,
                    )
                except TimeoutError:
                    await workflow.execute_activity(
                        expire_project, input, start_to_close_timeout=SHORT
                    )
                    await report_step(input, "expired", status="completed")
                    return "expired"
                if self.cancelled:
                    await report_step(input, "cancelled", status="completed")
                    return "cancelled"
                finished = await workflow.execute_activity(
                    step_finished, step_input, start_to_close_timeout=SHORT
                )
                if finished:
                    break
                self.done.remove(step)
        await report_step(input, "reconciling")
        await workflow.execute_activity(
            reconcile_project, input, start_to_close_timeout=LONG, retry_policy=RETRIES
        )
        await report_step(input, "completed", status="completed")
        return "completed"


@register_workflow(process=EXPORT_PROCESS, task_queue=QUEUE, cancel_permission=None)
@workflow.defn
class TenantExportWorkflow:
    def __init__(self) -> None:
        self.cancelled = False

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    async def _end(self, input: ExportInput, status: str, error: str = "") -> str:
        await workflow.execute_activity(
            end_export,
            ExportEndInput(
                organisation_id=input.organisation_id,
                export_id=input.export_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=SHORT,
        )
        await report_step(input, status, status="completed")
        return status

    @workflow.run
    async def run(self, input: ExportInput) -> str:
        entities = await workflow.execute_activity(plan_export, input, start_to_close_timeout=SHORT)
        await report_step(input, "exporting")
        try:
            for entity in entities:
                if self.cancelled:
                    return await self._end(input, "cancelled")
                await workflow.execute_activity(
                    export_entity,
                    EntityInput(
                        organisation_id=input.organisation_id,
                        export_id=input.export_id,
                        entity=entity,
                    ),
                    start_to_close_timeout=LONG,
                    retry_policy=RETRIES,
                )
            if self.cancelled:
                return await self._end(input, "cancelled")
            await report_step(input, "archiving")
            available = await workflow.execute_activity(
                build_export,
                input,
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RETRIES,
            )
        except ActivityError as exc:
            return await self._end(input, "failed", str(exc.cause or exc))
        await report_step(input, "ready")
        remaining = timedelta(seconds=available)
        if remaining > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.cancelled, timeout=remaining)
        return await self._end(input, "cancelled" if self.cancelled else "expired")
