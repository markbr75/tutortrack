"""Subscribers to tenancy's own events: start the closure process (E02-TW1)."""

from __future__ import annotations

from tutortrack.core.workflows import bridge

from .closure import ClosureInput, OrganisationClosureWorkflow, closure_workflow_id

bridge.on(
    "organisation.closed",
    start=OrganisationClosureWorkflow,
    id=lambda e: closure_workflow_id(e.organisation_id),
    input=lambda e: ClosureInput(
        organisation_id=str(e.organisation_id),
        export_requested=bool(e.data.get("export_requested", True)),
    ),
    subject=lambda e: ("organisation", str(e.organisation_id)),
)
