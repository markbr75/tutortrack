"""Domain events published by payments (E11 §6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _PaymentEvent(DomainEvent):
    subject_type: ClassVar[str] = "payment"
    client_id: str
    amount: dict[str, str]


@dataclass(frozen=True, kw_only=True)
class PaymentSucceeded(_PaymentEvent):
    event_type: ClassVar[str] = "payment.succeeded"
    method: str
    invoice_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PaymentPending(_PaymentEvent):
    event_type: ClassVar[str] = "payment.pending"


@dataclass(frozen=True, kw_only=True)
class PaymentFailed(DomainEvent):
    """E13 sends the client a pay-now link (``final`` also tells staff)."""

    event_type: ClassVar[str] = "payment.failed"
    subject_type: ClassVar[str] = "invoice"
    client_id: str
    attempt: int
    failure_code: str
    final: bool = False


@dataclass(frozen=True, kw_only=True)
class PaymentRefunded(_PaymentEvent):
    event_type: ClassVar[str] = "payment.refunded"
    refund_id: str


@dataclass(frozen=True, kw_only=True)
class PaymentDisputed(_PaymentEvent):
    event_type: ClassVar[str] = "payment.disputed"
    dispute_id: str
    evidence_due_by: str | None = None


@dataclass(frozen=True, kw_only=True)
class DisputeEvidenceDue(_PaymentEvent):
    """Reminder: the evidence deadline for a dispute is close (E13 tells staff)."""

    event_type: ClassVar[str] = "payment.dispute_evidence_due"
    dispute_id: str
    evidence_due_by: str | None = None


@dataclass(frozen=True, kw_only=True)
class PaymentDisputeClosed(_PaymentEvent):
    event_type: ClassVar[str] = "payment.dispute_closed"
    dispute_id: str
    outcome: str


@dataclass(frozen=True, kw_only=True)
class PaymentMethodAdded(DomainEvent):
    event_type: ClassVar[str] = "payment_method.added"
    subject_type: ClassVar[str] = "payment_method"
    client_id: str
    type: str


@dataclass(frozen=True, kw_only=True)
class PaymentMethodRemoved(DomainEvent):
    event_type: ClassVar[str] = "payment_method.removed"
    subject_type: ClassVar[str] = "payment_method"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class ProviderAccountConnected(DomainEvent):
    event_type: ClassVar[str] = "provider_account.connected"
    subject_type: ClassVar[str] = "provider_account"
    provider: str


@dataclass(frozen=True, kw_only=True)
class ProviderAccountDisconnected(DomainEvent):
    event_type: ClassVar[str] = "provider_account.disconnected"
    subject_type: ClassVar[str] = "provider_account"
    provider: str


@dataclass(frozen=True, kw_only=True)
class ProviderAccountRequirementsDue(DomainEvent):
    event_type: ClassVar[str] = "provider_account.requirements_due"
    subject_type: ClassVar[str] = "provider_account"
    requirements: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PayoutReceived(DomainEvent):
    event_type: ClassVar[str] = "payout.received"
    subject_type: ClassVar[str] = "payout"
    amount: dict[str, str]
