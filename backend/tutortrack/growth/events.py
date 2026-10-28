"""Domain events published by growth (E25 §4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ReviewRequested(DomainEvent):
    """Starts the Review request built-in workflow (send, remind, close)."""

    event_type: ClassVar[str] = "review.requested"
    subject_type: ClassVar[str] = "review_request"
    client_id: str
    tutor_id: str | None = None
    trigger: str


@dataclass(frozen=True, kw_only=True)
class _ReviewEvent(DomainEvent):
    subject_type: ClassVar[str] = "review"
    client_id: str
    tutor_id: str | None = None
    rating: int


@dataclass(frozen=True, kw_only=True)
class ReviewSubmitted(_ReviewEvent):
    event_type: ClassVar[str] = "review.submitted"
    request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ReviewPublished(_ReviewEvent):
    event_type: ClassVar[str] = "review.published"


@dataclass(frozen=True, kw_only=True)
class _ReferralEvent(DomainEvent):
    subject_type: ClassVar[str] = "referral"
    referrer_id: str
    referee_id: str


@dataclass(frozen=True, kw_only=True)
class ReferralCreated(_ReferralEvent):
    """Starts ``ReferralRewardWorkflow``."""

    event_type: ClassVar[str] = "referral.created"
    source: str


@dataclass(frozen=True, kw_only=True)
class ReferralConverted(_ReferralEvent):
    event_type: ClassVar[str] = "referral.converted"


@dataclass(frozen=True, kw_only=True)
class ReferralRewarded(_ReferralEvent):
    event_type: ClassVar[str] = "referral.rewarded"
    credit: dict[str, str] | None = None
    referee_discount: bool = False


@dataclass(frozen=True, kw_only=True)
class _CommissionEvent(DomainEvent):
    subject_type: ClassVar[str] = "commission_item"
    affiliate_id: str
    client_id: str | None
    amount: dict[str, str]
    kind: str


@dataclass(frozen=True, kw_only=True)
class CommissionEarned(_CommissionEvent):
    event_type: ClassVar[str] = "commission.earned"


@dataclass(frozen=True, kw_only=True)
class CommissionClawedBack(_CommissionEvent):
    event_type: ClassVar[str] = "commission.clawed_back"


@dataclass(frozen=True, kw_only=True)
class AffiliateStatementIssued(DomainEvent):
    event_type: ClassVar[str] = "affiliate_statement.issued"
    subject_type: ClassVar[str] = "affiliate_statement"
    affiliate_id: str
    number: str
    total: dict[str, str]
