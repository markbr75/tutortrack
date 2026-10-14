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


@dataclass(frozen=True, kw_only=True)
class InvoiceImported(_InvoiceEvent):
    """A historic invoice brought over by an import (E28): no ledger entry, no dunning."""

    event_type: ClassVar[str] = "invoice.imported"
    number: str
    status: str
    total: dict[str, str]


# --- Phase 2: packages (T12) ------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _PackageEvent(DomainEvent):
    subject_type: ClassVar[str] = "package"
    client_id: str
    units_remaining: str


@dataclass(frozen=True, kw_only=True)
class PackagePurchased(_PackageEvent):
    event_type: ClassVar[str] = "package.purchased"
    name: str
    price: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PackageActivated(_PackageEvent):
    event_type: ClassVar[str] = "package.activated"
    expires_at: str | None = None


@dataclass(frozen=True, kw_only=True)
class PackageLow(_PackageEvent):
    event_type: ClassVar[str] = "package.low"


@dataclass(frozen=True, kw_only=True)
class PackageDepleted(_PackageEvent):
    """Auto-renewing packages are sold again (``auto_renew``)."""

    event_type: ClassVar[str] = "package.depleted"
    auto_renew: bool = False


@dataclass(frozen=True, kw_only=True)
class PackageExpiring(_PackageEvent):
    event_type: ClassVar[str] = "package.expiring"
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class PackageExpired(_PackageEvent):
    """Unused units written off; ``value`` is the revenue released (recognised)."""

    event_type: ClassVar[str] = "package.expired"
    units_expired: str
    value: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PackageExtended(_PackageEvent):
    event_type: ClassVar[str] = "package.extended"
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class PackageCancelled(_PackageEvent):
    event_type: ClassVar[str] = "package.cancelled"
    reason: str
    credit_note_id: str | None = None


# --- Phase 2: recurring fees (T13) ------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BillingPlanCreated(DomainEvent):
    event_type: ClassVar[str] = "billing_plan.created"
    subject_type: ClassVar[str] = "billing_plan"
    client_id: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class BillingPlanStatusChanged(DomainEvent):
    event_type: ClassVar[str] = "billing_plan.status_changed"
    subject_type: ClassVar[str] = "billing_plan"
    client_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class BillingPlanPeriodSkipped(DomainEvent):
    """A period with no lessons on a plan that isn't attendance-independent."""

    event_type: ClassVar[str] = "billing_plan.period_skipped"
    subject_type: ClassVar[str] = "billing_plan"
    client_id: str
    start: str


# --- Phase 2: late fees and collections (T14) -------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class LateFeeApplied(_InvoiceEvent):
    event_type: ClassVar[str] = "late_fee.applied"
    charge_id: str
    amount: dict[str, str]
    number: int


@dataclass(frozen=True, kw_only=True)
class LateFeeWaived(DomainEvent):
    event_type: ClassVar[str] = "late_fee.waived"
    subject_type: ClassVar[str] = "charge"
    client_id: str
    reason: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class CollectionsOpened(DomainEvent):
    event_type: ClassVar[str] = "client.collections_opened"
    subject_type: ClassVar[str] = "client"
    invoice_id: str
    case_id: str
    block: str
    balance_due: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class CollectionsClosed(DomainEvent):
    event_type: ClassVar[str] = "client.collections_closed"
    subject_type: ClassVar[str] = "client"
    invoice_id: str
    case_id: str


# --- Phase 2: split billing (T15) -------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class BillingSplitChanged(DomainEvent):
    event_type: ClassVar[str] = "billing_split.changed"
    subject_type: ClassVar[str] = "billing_split"
    target: str  # job | student
    shares: list[dict[str, str]]


# --- gap G3: tutor pre-review of drafts, statements ---------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TutorReviewRequested(DomainEvent):
    """Tutors are asked to check their lessons on an invoice run's drafts (FR-10-3)."""

    event_type: ClassVar[str] = "invoice_run.tutor_review_requested"
    subject_type: ClassVar[str] = "invoice_run"
    tutor_ids: list[str]
    review_until: str | None = None


@dataclass(frozen=True, kw_only=True)
class TutorReviewAnswered(DomainEvent):
    """A tutor confirmed their lessons or reported a problem (drafts held for staff)."""

    event_type: ClassVar[str] = "invoice_run.tutor_reviewed"
    subject_type: ClassVar[str] = "invoice_run"
    review_id: str
    tutor_id: str
    status: str  # confirmed | flagged
    held_invoice_ids: list[str]


@dataclass(frozen=True, kw_only=True)
class StatementSent(DomainEvent):
    """A scheduled monthly statement was emailed to a client (FR-10-9)."""

    event_type: ClassVar[str] = "client.statement_sent"
    subject_type: ClassVar[str] = "client"
    currency: str
    period_start: str
    period_end: str
