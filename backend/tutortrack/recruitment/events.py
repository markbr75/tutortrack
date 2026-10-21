"""Domain events published by recruitment and compliance (E18 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _ApplicationEvent(DomainEvent):
    subject_type: ClassVar[str] = "tutor_application"


@dataclass(frozen=True, kw_only=True)
class ApplicationSubmitted(_ApplicationEvent):
    """Starts ``TutorApplicationWorkflow``."""

    event_type: ClassVar[str] = "application.submitted"
    opening_id: str | None


@dataclass(frozen=True, kw_only=True)
class ApplicationStageChanged(_ApplicationEvent):
    event_type: ClassVar[str] = "application.stage_changed"
    to_stage: str


@dataclass(frozen=True, kw_only=True)
class ApplicationApproved(_ApplicationEvent):
    event_type: ClassVar[str] = "application.approved"
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class ApplicationRejected(_ApplicationEvent):
    event_type: ClassVar[str] = "application.rejected"
    reason: str


@dataclass(frozen=True, kw_only=True)
class InterviewBooked(_ApplicationEvent):
    event_type: ClassVar[str] = "application.interview_booked"
    interview_id: str


@dataclass(frozen=True, kw_only=True)
class ReferenceRequested(DomainEvent):
    """Starts ``ReferenceRequestWorkflow``."""

    event_type: ClassVar[str] = "reference.requested"
    subject_type: ClassVar[str] = "reference_request"
    application_id: str


@dataclass(frozen=True, kw_only=True)
class ReferenceReceived(DomainEvent):
    event_type: ClassVar[str] = "reference.received"
    subject_type: ClassVar[str] = "reference_request"
    application_id: str
    concerns: bool


@dataclass(frozen=True, kw_only=True)
class OnboardingStarted(DomainEvent):
    """Starts ``TutorOnboardingWorkflow``."""

    event_type: ClassVar[str] = "onboarding.started"
    subject_type: ClassVar[str] = "tutor"


@dataclass(frozen=True, kw_only=True)
class OnboardingItemDone(DomainEvent):
    event_type: ClassVar[str] = "onboarding.item_done"
    subject_type: ClassVar[str] = "tutor"
    item: str


@dataclass(frozen=True, kw_only=True)
class OnboardingCompleted(DomainEvent):
    event_type: ClassVar[str] = "onboarding.completed"
    subject_type: ClassVar[str] = "tutor"


@dataclass(frozen=True, kw_only=True)
class _RecordEvent(DomainEvent):
    subject_type: ClassVar[str] = "compliance_record"
    tutor_id: str
    requirement: str


@dataclass(frozen=True, kw_only=True)
class ComplianceSubmitted(_RecordEvent):
    event_type: ClassVar[str] = "compliance.record_submitted"


@dataclass(frozen=True, kw_only=True)
class ComplianceVerified(_RecordEvent):
    """With an expiry date, starts ``ComplianceRecordWorkflow``."""

    event_type: ClassVar[str] = "compliance.record_verified"
    expiry_date: str | None


@dataclass(frozen=True, kw_only=True)
class ComplianceRejected(_RecordEvent):
    event_type: ClassVar[str] = "compliance.record_rejected"
    reason: str


@dataclass(frozen=True, kw_only=True)
class ComplianceExpiring(_RecordEvent):
    event_type: ClassVar[str] = "compliance.expiring"
    days: int


@dataclass(frozen=True, kw_only=True)
class ComplianceExpired(_RecordEvent):
    event_type: ClassVar[str] = "compliance.expired"


@dataclass(frozen=True, kw_only=True)
class TutorRestricted(DomainEvent):
    event_type: ClassVar[str] = "tutor.restricted"
    subject_type: ClassVar[str] = "tutor"
    problems: list[str]


@dataclass(frozen=True, kw_only=True)
class TutorUnrestricted(DomainEvent):
    event_type: ClassVar[str] = "tutor.unrestricted"
    subject_type: ClassVar[str] = "tutor"


# --- E18-T11 background checks (no results or numbers in payloads) -----------------------------


@dataclass(frozen=True, kw_only=True)
class _CheckEvent(DomainEvent):
    subject_type: ClassVar[str] = "background_check"
    tutor_id: str
    provider: str


@dataclass(frozen=True, kw_only=True)
class BackgroundCheckRequested(_CheckEvent):
    """Starts ``BackgroundCheckWorkflow``."""

    event_type: ClassVar[str] = "background_check.requested"


@dataclass(frozen=True, kw_only=True)
class BackgroundCheckCompleted(_CheckEvent):
    event_type: ClassVar[str] = "background_check.completed"
    result: str


@dataclass(frozen=True, kw_only=True)
class BackgroundCheckFailed(_CheckEvent):
    """Couldn't start, expired before the tutor finished, or was cancelled."""

    event_type: ClassVar[str] = "background_check.failed"
    status: str


# --- gap batch G5a ------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ComplianceDocumentsRequested(DomainEvent):
    """Staff asked a tutor for missing, rejected or expired documents (FR-18-8)."""

    event_type: ClassVar[str] = "compliance.documents_requested"
    subject_type: ClassVar[str] = "tutor"
    requirements: list[str]


@dataclass(frozen=True, kw_only=True)
class InterviewMeetingCreated(_ApplicationEvent):
    """The video link for a booked interview was created (FR-18-2, E22)."""

    event_type: ClassVar[str] = "application.interview_meeting_created"
    interview_id: str
    provider: str


@dataclass(frozen=True, kw_only=True)
class ProbationScheduled(DomainEvent):
    """Starts ``ProbationReviewWorkflow`` (FR-18-9)."""

    event_type: ClassVar[str] = "probation.scheduled"
    subject_type: ClassVar[str] = "probation_review"
    tutor_id: str
    due_on: str


@dataclass(frozen=True, kw_only=True)
class ProbationCompleted(DomainEvent):
    event_type: ClassVar[str] = "probation.completed"
    subject_type: ClassVar[str] = "probation_review"
    tutor_id: str
    outcome: str


@dataclass(frozen=True, kw_only=True)
class PerformanceNoteAdded(DomainEvent):
    event_type: ClassVar[str] = "performance.note_added"
    subject_type: ClassVar[str] = "tutor"
    note_id: str
    kind: str


@dataclass(frozen=True, kw_only=True)
class OffboardingStarted(DomainEvent):
    event_type: ClassVar[str] = "offboarding.started"
    subject_type: ClassVar[str] = "tutor"
    leaving_on: str | None


@dataclass(frozen=True, kw_only=True)
class OffboardingCompleted(DomainEvent):
    event_type: ClassVar[str] = "offboarding.completed"
    subject_type: ClassVar[str] = "tutor"
