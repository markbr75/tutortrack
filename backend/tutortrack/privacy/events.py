from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ConsentGranted(DomainEvent):
    event_type: ClassVar[str] = "consent.granted"
    subject_type: ClassVar[str] = "consent"

    consent_type: str
    category: str
    consent_version: int
    person_type: str
    person_id: str


@dataclass(frozen=True, kw_only=True)
class ConsentWithdrawn(DomainEvent):
    """E13 suppresses marketing, E22 disables recording, ... on this event."""

    event_type: ClassVar[str] = "consent.withdrawn"
    subject_type: ClassVar[str] = "consent"

    consent_type: str
    category: str
    person_type: str
    person_id: str


# --- data subject requests and erasure (FR-29-4) ------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DataRequestReceived(DomainEvent):
    """A data subject request was logged (starts ``DataSubjectRequestWorkflow``)."""

    event_type: ClassVar[str] = "data_request.received"
    subject_type: ClassVar[str] = "data_request"

    kind: str
    due_at: str


@dataclass(frozen=True, kw_only=True)
class DataRequestVerified(DomainEvent):
    event_type: ClassVar[str] = "data_request.verified"
    subject_type: ClassVar[str] = "data_request"

    kind: str


@dataclass(frozen=True, kw_only=True)
class DataRequestDelivered(DomainEvent):
    """The export was sent to the requester as a secure, expiring link."""

    event_type: ClassVar[str] = "data_request.delivered"
    subject_type: ClassVar[str] = "data_request"

    link_expires_at: str


@dataclass(frozen=True, kw_only=True)
class DataRequestClosed(DomainEvent):
    """Completed, rejected, cancelled or blocked by a legal hold."""

    event_type: ClassVar[str] = "data_request.closed"
    subject_type: ClassVar[str] = "data_request"

    kind: str
    status: str


@dataclass(frozen=True, kw_only=True)
class DataSubjectErased(DomainEvent):
    """A person's data was erased or anonymised across the apps (ids only, no PII)."""

    event_type: ClassVar[str] = "data_subject.erased"
    subject_type: ClassVar[str] = "erasure"

    person_type: str
    person_id: str
    reason: str
    request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class LegalHoldPlaced(DomainEvent):
    event_type: ClassVar[str] = "legal_hold.placed"
    subject_type: ClassVar[str] = "legal_hold"

    person_type: str
    person_id: str


@dataclass(frozen=True, kw_only=True)
class LegalHoldReleased(DomainEvent):
    event_type: ClassVar[str] = "legal_hold.released"
    subject_type: ClassVar[str] = "legal_hold"

    person_type: str
    person_id: str


@dataclass(frozen=True, kw_only=True)
class RetentionRunCompleted(DomainEvent):
    event_type: ClassVar[str] = "retention.run_completed"
    subject_type: ClassVar[str] = "retention_run"

    dry_run: bool
    due: int
    done: int


# --- safeguarding (FR-29-6) ---------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SafeguardingConcernRaised(DomainEvent):
    """Internal only: carries no description or names (never a webhook event)."""

    event_type: ClassVar[str] = "safeguarding.concern_raised"
    subject_type: ClassVar[str] = "safeguarding_concern"

    category: str
    immediate_risk: bool


@dataclass(frozen=True, kw_only=True)
class SafeguardingConcernClosed(DomainEvent):
    event_type: ClassVar[str] = "safeguarding.concern_closed"
    subject_type: ClassVar[str] = "safeguarding_concern"


@dataclass(frozen=True, kw_only=True)
class SafeguardingMessageFlagged(DomainEvent):
    event_type: ClassVar[str] = "safeguarding.message_flagged"
    subject_type: ClassVar[str] = "safeguarding_flag"

    source_type: str
    blocked: bool


@dataclass(frozen=True, kw_only=True)
class LoneWorkingCheckedIn(DomainEvent):
    """Starts ``LoneWorkingWorkflow`` (the overdue timer)."""

    event_type: ClassVar[str] = "lone_working.checked_in"
    subject_type: ClassVar[str] = "lone_working_visit"

    lesson_id: str
    tutor_id: str
    expected_end: str


@dataclass(frozen=True, kw_only=True)
class LoneWorkingCheckedOut(DomainEvent):
    event_type: ClassVar[str] = "lone_working.checked_out"
    subject_type: ClassVar[str] = "lone_working_visit"

    lesson_id: str
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class LoneWorkingOverdue(DomainEvent):
    event_type: ClassVar[str] = "lone_working.overdue"
    subject_type: ClassVar[str] = "lone_working_visit"

    lesson_id: str
    tutor_id: str
    escalated: bool


# --- data processing agreement (FR-29-8) --------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DPAAccepted(DomainEvent):
    event_type: ClassVar[str] = "dpa.accepted"
    subject_type: ClassVar[str] = "dpa_acceptance"

    dpa_version: str
