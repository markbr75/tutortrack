"""Outbox subscribers (E23): financial events start ``AccountingSyncWorkflow`` for the
record they are about; integration events create or switch off our side of a ledger
connection. Idempotent: workflow ids include the event id, and the push itself compares a
content hash, so a duplicate event changes nothing in the ledger."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge, workflow_id

from .processes import SYNC_PROCESS, AccountingSyncWorkflow, SyncInput
from .providers import CAPABILITY

BILLS = {"bill", "bill_payment", "pay_run", "pay_statement"}


def _wanted(object_type: str, object_id: Any) -> bool:
    from .builders import SALES_SIDE
    from .models import AccountingConnection
    from .routing import route

    if object_type == "contact":  # a client may be in several ledgers (gap G5)
        from .routing import enabled_connections

        return any(c.mode == AccountingConnection.Mode.INDIVIDUAL for c in enabled_connections())
    # The ledger the record goes to (gap G5: per-branch ledgers).
    conn = route(object_type, str(object_id))
    if conn is None:
        return False
    if conn.mode == AccountingConnection.Mode.SUMMARY and object_type in SALES_SIDE:
        return False
    return not (object_type in BILLS and not conn.sync_bills)


def _already_synced(object_type: str) -> Callable[[EventEnvelope], bool]:
    """Updates only matter for records already in the ledger."""

    def check(e: EventEnvelope) -> bool:
        from .models import ExternalRecordLink

        return ExternalRecordLink.objects.filter(
            object_type=object_type, object_id=str(e.subject["id"]), status="synced"
        ).exists()

    return check


def sync_on(
    event_type: str,
    object_type: str,
    *,
    object_id: Callable[[EventEnvelope], Any] = lambda e: e.subject["id"],
    when: Callable[[EventEnvelope], bool] | None = None,
) -> None:
    bridge.on(
        event_type,
        start=AccountingSyncWorkflow,
        id=lambda e: workflow_id(SYNC_PROCESS, e.organisation_id, object_type, object_id(e), e.id),
        input=lambda e: SyncInput(
            organisation_id=str(e.organisation_id),
            object_type=object_type,
            object_id=str(object_id(e)),
        ),
        subject=lambda e: (object_type, str(object_id(e))),
        when=lambda e: _wanted(object_type, object_id(e)) and (when is None or when(e)),
    )


sync_on("invoice.issued", "invoice")
sync_on("invoice.voided", "invoice", when=_already_synced("invoice"))
sync_on("invoice.paid", "invoice", when=_already_synced("invoice"))  # client credit applied
sync_on("invoice.partially_paid", "invoice", when=_already_synced("invoice"))
sync_on("invoice.written_off", "write_off")
sync_on("credit_note.issued", "credit_note")
sync_on("payment.succeeded", "payment")
sync_on("payment.refunded", "refund", object_id=lambda e: e.data["refund_id"])
sync_on("client.updated", "contact", when=_already_synced("contact"))
sync_on("payout.received", "provider_payout")
sync_on("pay_run.approved", "pay_run")
sync_on("self_billing_statement.issued", "pay_statement")
sync_on("payout.paid", "bill_payment")
# Gap G5: changes after a payment is in the ledger.
sync_on("payment.reallocated", "reallocation")
sync_on(
    "payment.dispute_closed",
    "chargeback",
    object_id=lambda e: e.data["dispute_id"],
    when=lambda e: e.data.get("outcome") == "lost",
)


@subscribe("payment.reallocated", name="accounting.payment_reallocated")
def payment_reallocated(event: EventEnvelope) -> None:
    from . import services

    services.note_reallocated(str(event.subject["id"]))


# --- the ledger connection -----------------------------------------------------------------------


def _accounting(e: EventEnvelope) -> bool:
    return e.data.get("level") in ("organisation", "branch") and CAPABILITY in (
        e.data.get("capabilities") or []
    )


@subscribe("integration.connected", name="accounting.connection_connected")
def connected(event: EventEnvelope) -> None:
    if _accounting(event):
        from . import services

        services.on_connected(event.subject["id"])


@subscribe("integration.disconnected", name="accounting.connection_disconnected")
def disconnected(event: EventEnvelope) -> None:
    if _accounting(event):
        from . import services

        services.on_disconnected(event.subject["id"])


@subscribe("integration.error", name="accounting.connection_error")
def connection_error(event: EventEnvelope) -> None:
    if _accounting(event):
        from . import services

        services.on_connection_error(
            event.subject["id"], str(event.data.get("status", "")), str(event.data.get("error", ""))
        )


# --- E23-T10: Xero Payroll timesheets for employed tutors --------------------------------------


def _payroll_wanted(e: EventEnvelope) -> bool:
    from .payroll_sync import should_sync

    return should_sync(e.subject["id"])


def _payroll_bridge() -> None:
    from .payroll_processes import (
        PayrollSyncInput,
        XeroPayrollSyncWorkflow,
        payroll_sync_workflow_id,
    )

    bridge.on(
        "pay_run.approved",
        start=XeroPayrollSyncWorkflow,
        id=lambda e: payroll_sync_workflow_id(e.organisation_id, e.subject["id"]),
        input=lambda e: PayrollSyncInput(
            organisation_id=str(e.organisation_id), pay_run_id=e.subject["id"]
        ),
        subject=lambda e: ("pay_run", e.subject["id"]),
        when=_payroll_wanted,
    )


_payroll_bridge()
