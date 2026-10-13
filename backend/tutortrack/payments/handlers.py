"""Payments reactions to domain events and the Temporal bridge (E11-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
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


# --- Phase 2 ------------------------------------------------------------------------------------


@subscribe("payment_method.added")
def migration_method_added(event: EventEnvelope) -> None:
    """A client being moved to another provider added a method there (FR-11-2)."""
    from . import provider_migration

    provider_migration.on_method_added(
        str(event.data.get("client_id") or ""),
        event.subject["id"],
        str(event.data.get("provider") or ""),
    )


def _bank_feed(event: EventEnvelope) -> bool:
    from .bank_feeds import CAPABILITY, PROVIDER

    return event.data.get("provider") == PROVIDER or CAPABILITY in (
        event.data.get("capabilities") or []
    )


@subscribe("integration.connected", name="payments.bank_feed_connected")
def bank_feed_connected(event: EventEnvelope) -> None:
    """A daily Temporal Schedule pulls the connected bank account's transactions."""
    if not _bank_feed(event):
        return
    from tutortrack.core.workflows.schedules import ensure_schedule
    from tutortrack.tenancy.models import Organisation

    from .processes import BANK_FEED_PROCESS, BankFeedInput, BankFeedSyncWorkflow

    org = Organisation.objects.get(pk=str(event.organisation_id))
    ensure_schedule(
        process=BANK_FEED_PROCESS,
        workflow=BankFeedSyncWorkflow,
        input=BankFeedInput(
            organisation_id=str(event.organisation_id), connection_id=str(event.subject["id"])
        ),
        cron=["0 7 * * *"],
        timezone=str(org.timezone),
        parts=(event.subject["id"],),
    )


@subscribe("integration.disconnected", name="payments.bank_feed_disconnected")
def bank_feed_disconnected(event: EventEnvelope) -> None:
    if not _bank_feed(event):
        return
    from tutortrack.core.workflows.schedules import delete_schedule, schedule_id

    from .processes import BANK_FEED_PROCESS

    delete_schedule(
        event.organisation_id,
        schedule_id(BANK_FEED_PROCESS, event.organisation_id, event.subject["id"]),
    )
