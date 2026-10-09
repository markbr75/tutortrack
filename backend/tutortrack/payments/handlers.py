"""Payments reactions to domain events and the Temporal bridge (E11-TW1)."""

from __future__ import annotations

from tutortrack.core.workflows import bridge

from .processes import (
    CollectInput,
    DisputeInput,
    DisputeWorkflow,
    PaymentCollectionWorkflow,
    collect_workflow_id,
    dispute_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


def _autopay(invoice_id: str) -> bool:
    from . import services

    return services.should_autopay(invoice_id)


bridge.on(
    "invoice.issued",
    start=PaymentCollectionWorkflow,
    id=lambda e: collect_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: CollectInput(
        organisation_id=str(e.organisation_id), invoice_id=e.subject["id"]
    ),
    when=lambda e: _autopay(e.subject["id"]),
)
for _closing in ("invoice.paid", "invoice.voided", "invoice.written_off"):
    bridge.on(
        _closing,
        signal="paid",
        id=lambda e: collect_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(collect_workflow_id(e.organisation_id, e.subject["id"])),
    )
bridge.on(
    "payment.disputed",
    start=DisputeWorkflow,
    id=lambda e: dispute_workflow_id(e.organisation_id, e.data["dispute_id"]),
    input=lambda e: DisputeInput(
        organisation_id=str(e.organisation_id),
        dispute_id=e.data["dispute_id"],
        evidence_due_by=e.data.get("evidence_due_by") or "",
    ),
    subject=lambda e: ("payment", e.subject["id"]),
)
