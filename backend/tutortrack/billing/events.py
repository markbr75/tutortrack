"""Domain events published by client billing (E10 §6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ChargeCreated(DomainEvent):
    event_type: ClassVar[str] = "charge.created"
    subject_type: ClassVar[str] = "charge"
    client_id: str
    kind: str
    gross: dict[str, str]
    lesson_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChargeVoided(DomainEvent):
    event_type: ClassVar[str] = "charge.voided"
    subject_type: ClassVar[str] = "charge"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class _InvoiceEvent(DomainEvent):
    subject_type: ClassVar[str] = "invoice"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class InvoiceDrafted(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.drafted"
    run_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class InvoiceIssued(_InvoiceEvent):
    """E11 starts auto-pay collection; billing starts the dunning workflow."""

    event_type: ClassVar[str] = "invoice.issued"
    number: str
    total: dict[str, str]
    balance_due: dict[str, str]
    due_date: str


@dataclass(frozen=True, kw_only=True)
class InvoiceSent(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.sent"
    to: list[str]


@dataclass(frozen=True, kw_only=True)
class InvoicePaid(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.paid"


@dataclass(frozen=True, kw_only=True)
class InvoicePartiallyPaid(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.partially_paid"
    balance_due: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class InvoiceReminder(_InvoiceEvent):
    """E13 sends the reminder (template per offset)."""

    event_type: ClassVar[str] = "invoice.reminder"
    offset_days: int
    balance_due: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class InvoiceOverdue(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.overdue"


@dataclass(frozen=True, kw_only=True)
class InvoiceVoided(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.voided"
    reason: str


@dataclass(frozen=True, kw_only=True)
class InvoiceWrittenOff(_InvoiceEvent):
    event_type: ClassVar[str] = "invoice.written_off"
    reason: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class CreditNoteIssued(DomainEvent):
    event_type: ClassVar[str] = "credit_note.issued"
    subject_type: ClassVar[str] = "credit_note"
    client_id: str
    invoice_id: str
    total: dict[str, str]
    application: str


@dataclass(frozen=True, kw_only=True)
class _RequestEvent(DomainEvent):
    subject_type: ClassVar[str] = "payment_request"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class PaymentRequestCreated(_RequestEvent):
    event_type: ClassVar[str] = "payment_request.created"
    amount: dict[str, str]
    source: str


@dataclass(frozen=True, kw_only=True)
class PaymentRequestSent(_RequestEvent):
    event_type: ClassVar[str] = "payment_request.sent"


@dataclass(frozen=True, kw_only=True)
class PaymentRequestPaid(_RequestEvent):
    event_type: ClassVar[str] = "payment_request.paid"
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PaymentRequestCancelled(_RequestEvent):
    event_type: ClassVar[str] = "payment_request.cancelled"


@dataclass(frozen=True, kw_only=True)
class ClientBalanceLow(DomainEvent):
    event_type: ClassVar[str] = "client.balance_low"
    subject_type: ClassVar[str] = "client"
    available: dict[str, str]
