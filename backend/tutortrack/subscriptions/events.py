"""Domain events published by subscriptions (E04 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _SubscriptionEvent(DomainEvent):
    subject_type: ClassVar[str] = "subscription"
    plan: str
    status: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionStarted(_SubscriptionEvent):
    """A trial (or a subscription without one) began; starts ``TrialLifecycleWorkflow``."""

    event_type: ClassVar[str] = "subscription.started"
    trial_ends_at: str | None = None


@dataclass(frozen=True, kw_only=True)
class SubscriptionChanged(_SubscriptionEvent):
    """``change``: plan | interval | scheduled | cancel_scheduled | cancel_undone | converted
    | activated | payment_recovered | trial_extended."""

    event_type: ClassVar[str] = "subscription.changed"
    change: str
    invoice_id: str = ""


@dataclass(frozen=True, kw_only=True)
class SubscriptionTrialEnding(_SubscriptionEvent):
    event_type: ClassVar[str] = "subscription.trial_ending"
    trial_ends_at: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionPastDue(_SubscriptionEvent):
    """A renewal payment failed; starts ``SubscriptionDunningWorkflow``."""

    event_type: ClassVar[str] = "subscription.past_due"
    invoice_id: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionSuspended(_SubscriptionEvent):
    """Read-only: the trial ended without a payment method, or dunning ran out."""

    event_type: ClassVar[str] = "subscription.suspended"
    reason: str


@dataclass(frozen=True, kw_only=True)
class SubscriptionCancelled(_SubscriptionEvent):
    event_type: ClassVar[str] = "subscription.cancelled"


@dataclass(frozen=True, kw_only=True)
class CreditsLow(DomainEvent):
    event_type: ClassVar[str] = "credits.low"
    subject_type: ClassVar[str] = "credit_account"
    credit_type: str
    balance: int
