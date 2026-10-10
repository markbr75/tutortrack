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
