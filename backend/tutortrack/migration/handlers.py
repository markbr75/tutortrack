"""Reactions to domain events and the Temporal bridge (E28-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    BatchInput,
    ExportInput,
    ImportWorkflow,
    MigrationProjectWorkflow,
    ProjectInput,
    TenantExportWorkflow,
    export_workflow_id,
    import_workflow_id,
    project_workflow_id,
)


@subscribe("organisation.export_requested")
def export_for_organisation(event: EventEnvelope) -> None:
    """Account closure (E02) and the platform console (E30) ask for a full export."""
    from . import services

    services.request_export(reason=str(event.data.get("reason") or "requested")[:200])


bridge.on(
    "import.submitted",
    start=ImportWorkflow,
    id=lambda e: import_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: BatchInput(organisation_id=str(e.organisation_id), batch_id=e.subject["id"]),
    subject=lambda e: ("migration.importbatch", e.subject["id"]),
)
bridge.on(
    "migration_project.started",
    start=MigrationProjectWorkflow,
    id=lambda e: project_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ProjectInput(
        organisation_id=str(e.organisation_id), project_id=e.subject["id"]
    ),
    subject=lambda e: ("migration.migrationproject", e.subject["id"]),
)
bridge.on(
    "export.requested",
    start=TenantExportWorkflow,
    id=lambda e: export_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ExportInput(organisation_id=str(e.organisation_id), export_id=e.subject["id"]),
    subject=lambda e: ("migration.exportjob", e.subject["id"]),
)
