"""Billing reactions to domain events (idempotent) and the Temporal bridge (E10-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    DunningInput,
    InvoiceDunningWorkflow,
    PaymentRequestWorkflow,
    RequestInput,
    dunning_workflow_id,
    request_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe(
    "lesson.completed",
    "lesson.cancelled",
    "attendance.recorded",
    "lesson.updated",
    "lesson.locked_edited",
)
def sync_charges(event: EventEnvelope) -> None:
    """Charges follow what happened to the lesson (FR-10-2)."""
    from . import services

    services.sync_lesson_charges(event.subject["id"])


@subscribe("organisation.settings_updated")
def follow_invoice_schedule(event: EventEnvelope) -> None:
    keys = set(event.data.get("keys") or [])
    if event.data.get("area") == "billing" and keys & {
        "billing.invoice_schedule",
        "billing.invoice_day",
    }:
        from .schedules import sync_invoice_schedules

        sync_invoice_schedules()


bridge.on(
    "invoice.issued",
    start=InvoiceDunningWorkflow,
    id=lambda e: dunning_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: DunningInput(
        organisation_id=str(e.organisation_id),
        invoice_id=e.subject["id"],
        due_date=e.data["due_date"],
    ),
)
for _closing in ("invoice.paid", "invoice.voided", "invoice.written_off"):
    bridge.on(
        _closing,
        signal="closed",
        id=lambda e: dunning_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(dunning_workflow_id(e.organisation_id, e.subject["id"])),
    )

bridge.on(
    "payment_request.created",
    start=PaymentRequestWorkflow,
    id=lambda e: request_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: RequestInput(
        organisation_id=str(e.organisation_id), request_id=e.subject["id"]
    ),
)
for _closing in ("payment_request.paid", "payment_request.cancelled"):
    bridge.on(
        _closing,
        signal="closed",
        id=lambda e: request_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(request_workflow_id(e.organisation_id, e.subject["id"])),
    )
