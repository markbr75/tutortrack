"""Domain events published by matching (E19 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class OfferBatchStarted(DomainEvent):
    """Starts ``JobOfferCascadeWorkflow``."""

    event_type: ClassVar[str] = "job_offer.batch_started"
    subject_type: ClassVar[str] = "offer_batch"
    job_id: str
    mode: str
    tutors: int


@dataclass(frozen=True, kw_only=True)
class OfferBatchClosed(DomainEvent):
    event_type: ClassVar[str] = "job_offer.batch_closed"
    subject_type: ClassVar[str] = "offer_batch"
    job_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class OfferDecided(DomainEvent):
    """A coordinator confirmed or rejected an accepted offer (signals the cascade)."""

    event_type: ClassVar[str] = "job_offer.decided"
    subject_type: ClassVar[str] = "job_offer"
    batch_id: str
    approved: bool


@dataclass(frozen=True, kw_only=True)
class _OfferEvent(DomainEvent):
    subject_type: ClassVar[str] = "job_offer"
    batch_id: str
    job_id: str
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class JobOfferSent(_OfferEvent):
    event_type: ClassVar[str] = "job_offer.sent"


@dataclass(frozen=True, kw_only=True)
class JobOfferAccepted(_OfferEvent):
    event_type: ClassVar[str] = "job_offer.accepted"


@dataclass(frozen=True, kw_only=True)
class JobOfferDeclined(_OfferEvent):
    event_type: ClassVar[str] = "job_offer.declined"
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class JobOfferExpired(_OfferEvent):
    event_type: ClassVar[str] = "job_offer.expired"


@dataclass(frozen=True, kw_only=True)
class JobOfferWithdrawn(_OfferEvent):
    event_type: ClassVar[str] = "job_offer.withdrawn"


@dataclass(frozen=True, kw_only=True)
class JobPostingPublished(DomainEvent):
    event_type: ClassVar[str] = "job_posting.published"
    subject_type: ClassVar[str] = "job_posting"
    job_id: str
    eligible: int


@dataclass(frozen=True, kw_only=True)
class JobPostingApplicationReceived(DomainEvent):
    event_type: ClassVar[str] = "job_posting.application_received"
    subject_type: ClassVar[str] = "job_posting"
    tutor_id: str
    application_id: str


@dataclass(frozen=True, kw_only=True)
class JobPostingFilled(DomainEvent):
    event_type: ClassVar[str] = "job_posting.filled"
    subject_type: ClassVar[str] = "job_posting"
    job_id: str
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class CoverRequestCreated(DomainEvent):
    """Starts ``CoverRequestWorkflow``."""

    event_type: ClassVar[str] = "cover_request.created"
    subject_type: ClassVar[str] = "cover_request"
    tutor_id: str
    lessons: int
    deadline: str


@dataclass(frozen=True, kw_only=True)
class CoverRequestAccepted(DomainEvent):
    event_type: ClassVar[str] = "cover_request.accepted"
    subject_type: ClassVar[str] = "cover_request"
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class CoverRequestFilled(DomainEvent):
    event_type: ClassVar[str] = "cover_request.filled"
    subject_type: ClassVar[str] = "cover_request"
    tutor_id: str
    lessons: int


@dataclass(frozen=True, kw_only=True)
class CoverRequestUnfilled(DomainEvent):
    event_type: ClassVar[str] = "cover_request.unfilled"
    subject_type: ClassVar[str] = "cover_request"


@dataclass(frozen=True, kw_only=True)
class CoverRequestCancelled(DomainEvent):
    event_type: ClassVar[str] = "cover_request.cancelled"
    subject_type: ClassVar[str] = "cover_request"
