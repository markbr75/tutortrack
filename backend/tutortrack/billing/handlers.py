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


@subscribe("invoice.issued", "invoice.paid")
def activate_packages(event: EventEnvelope) -> None:
    """A package can be used once its invoice is paid (or issued, setting) (E10-T12)."""
    from . import packages

    packages.activate_for_invoice(event.subject["id"])


@subscribe("package.depleted")
def renew_package(event: EventEnvelope) -> None:
    if event.data.get("auto_renew"):
        from . import packages

        packages.renew(event.subject["id"])


@subscribe("invoice.paid", "invoice.voided", "invoice.written_off")
def leave_collections(event: EventEnvelope) -> None:
    """Nothing overdue on the invoice any more: its collections case closes (E10-T14)."""
    from . import dunning

    dunning.close_collections(event.subject["id"], reason=event.type)


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
