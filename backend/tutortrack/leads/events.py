"""Domain events published by leads (E17 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _EnquiryEvent(DomainEvent):
    subject_type: ClassVar[str] = "enquiry"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class EnquiryReceived(_EnquiryEvent):
    """Starts ``EnquiryFollowUpWorkflow`` (auto-acknowledgement, SLA timers)."""

    event_type: ClassVar[str] = "enquiry.received"
    source: str
    owner_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class EnquiryAssigned(_EnquiryEvent):
    event_type: ClassVar[str] = "enquiry.assigned"
    owner_id: str | None


@dataclass(frozen=True, kw_only=True)
class EnquiryStageChanged(_EnquiryEvent):
    event_type: ClassVar[str] = "enquiry.stage_changed"
    from_stage: str | None
    to_stage: str


@dataclass(frozen=True, kw_only=True)
class EnquiryWon(_EnquiryEvent):
    event_type: ClassVar[str] = "enquiry.won"
    job_ids: list[str]


@dataclass(frozen=True, kw_only=True)
class EnquiryLost(_EnquiryEvent):
    event_type: ClassVar[str] = "enquiry.lost"
    reason: str


@dataclass(frozen=True, kw_only=True)
class EnquirySlaBreached(_EnquiryEvent):
    event_type: ClassVar[str] = "enquiry.sla_breached"
    stage: str


@dataclass(frozen=True, kw_only=True)
class TrialLessonBooked(DomainEvent):
    event_type: ClassVar[str] = "trial_lesson.booked"
    subject_type: ClassVar[str] = "enquiry"
    lesson_id: str


@dataclass(frozen=True, kw_only=True)
class TrialLessonCompleted(DomainEvent):
    event_type: ClassVar[str] = "trial_lesson.completed"
    subject_type: ClassVar[str] = "enquiry"
    outcome: str


@dataclass(frozen=True, kw_only=True)
class _WaitlistEvent(DomainEvent):
    subject_type: ClassVar[str] = "waitlist_entry"
    student_id: str
    group_class_id: str | None = None  # E20 class waitlists


@dataclass(frozen=True, kw_only=True)
class WaitlistPlaceOffered(_WaitlistEvent):
    """Starts ``WaitlistOfferWorkflow``."""

    event_type: ClassVar[str] = "waitlist.place_offered"
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class WaitlistPlaceAccepted(_WaitlistEvent):
    event_type: ClassVar[str] = "waitlist.place_accepted"


@dataclass(frozen=True, kw_only=True)
class WaitlistPlaceDeclined(_WaitlistEvent):
    event_type: ClassVar[str] = "waitlist.place_declined"


@dataclass(frozen=True, kw_only=True)
class WaitlistOfferExpired(_WaitlistEvent):
    event_type: ClassVar[str] = "waitlist.expired"


@dataclass(frozen=True, kw_only=True)
class WaitlistSuggestionCreated(DomainEvent):
    """A tutor now has room for a waiting student; the payload carries ids only.

    Gap G5c (FR-17-6)."""

    event_type: ClassVar[str] = "waitlist.suggestion_created"
    subject_type: ClassVar[str] = "waitlist_suggestion"
    entry_id: str
    student_id: str
    tutor_id: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class FormSubmitted(DomainEvent):
    event_type: ClassVar[str] = "form.submitted"
    subject_type: ClassVar[str] = "form_submission"
    form_id: str | None
    form_type: str


@dataclass(frozen=True, kw_only=True)
class _ProposalEvent(DomainEvent):
    subject_type: ClassVar[str] = "proposal"
    enquiry_id: str


@dataclass(frozen=True, kw_only=True)
class ProposalSent(_ProposalEvent):
    """Starts ``ProposalWorkflow`` (reminder, expiry)."""

    event_type: ClassVar[str] = "proposal.sent"
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class ProposalAccepted(_ProposalEvent):
    event_type: ClassVar[str] = "proposal.accepted"
    client_id: str
    job_ids: list[str]
    tutor_id: str | None = None
    payment_request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProposalDeclined(_ProposalEvent):
    event_type: ClassVar[str] = "proposal.declined"


@dataclass(frozen=True, kw_only=True)
class ProposalExpired(_ProposalEvent):
    event_type: ClassVar[str] = "proposal.expired"


@dataclass(frozen=True, kw_only=True)
class ProposalWithdrawn(_ProposalEvent):
    event_type: ClassVar[str] = "proposal.withdrawn"
