"""Domain events published by scheduling (E08 §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class LessonScheduled(DomainEvent):
    event_type: ClassVar[str] = "lesson.scheduled"
    subject_type: ClassVar[str] = "lesson"
    start: str
    end: str
    job_id: str | None = None
    series_id: str | None = None
    tutor_ids: list[str] = field(default_factory=list)
    student_ids: list[str] = field(default_factory=list)
    notify: bool = True  # False for imported lessons (E28)


@dataclass(frozen=True, kw_only=True)
class LessonUpdated(DomainEvent):
    event_type: ClassVar[str] = "lesson.updated"
    subject_type: ClassVar[str] = "lesson"
    fields: list[str] = field(default_factory=list)
    notify: bool = False


@dataclass(frozen=True, kw_only=True)
class LessonRescheduled(DomainEvent):
    """E13 notifies participants (with an updated ICS) when ``notify``."""

    event_type: ClassVar[str] = "lesson.rescheduled"
    subject_type: ClassVar[str] = "lesson"
    old_start: str
    new_start: str
    new_end: str
    reason: str = ""
    notify: bool = True


@dataclass(frozen=True, kw_only=True)
class LessonCancelled(DomainEvent):
    """``attendees``/``tutors`` carry the policy outcome (E09): per attendee
    ``{"id", "student_id", "client_id", "outcome", "charge_percent", "chargeable"}`` and per
    tutor ``{"id", "tutor_id", "pay_percent", "payable"}``. ``policy_kind`` is ``free``,
    ``late``, ``tutor`` or ``admin``; E10 raises a "Late cancellation fee" for chargeable
    attendees."""

    event_type: ClassVar[str] = "lesson.cancelled"
    subject_type: ClassVar[str] = "lesson"
    reason: str = ""
    chargeable: bool = False
    notify: bool = True
    cancelled_by: str = "admin"
    policy_kind: str = ""
    attendees: list[dict[str, object]] = field(default_factory=list)
    tutors: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class LessonCompleted(DomainEvent):
    """E10 charges chargeable attendees and E12 pays payable tutors (idempotently, keyed by
    attendee/tutor link). Shapes as in ``LessonCancelled``."""

    event_type: ClassVar[str] = "lesson.completed"
    subject_type: ClassVar[str] = "lesson"
    job_id: str | None = None
    auto: bool = False
    attendees: list[dict[str, object]] = field(default_factory=list)
    tutors: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class AttendanceRecorded(DomainEvent):
    """Attendance changed after completion; E10 updates uninvoiced charges."""

    event_type: ClassVar[str] = "attendance.recorded"
    subject_type: ClassVar[str] = "lesson"
    attendees: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class LessonMissed(DomainEvent):
    event_type: ClassVar[str] = "lesson.missed"
    subject_type: ClassVar[str] = "lesson"


@dataclass(frozen=True, kw_only=True)
class LockedLessonEdited(DomainEvent):
    """A locked (invoiced or paid) lesson changed: E10/E12 raise credit notes or pay
    adjustments from the before/after amounts."""

    event_type: ClassVar[str] = "lesson.locked_edited"
    subject_type: ClassVar[str] = "lesson"
    lock_state: str
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SeriesCreated(DomainEvent):
    event_type: ClassVar[str] = "lesson_series.created"
    subject_type: ClassVar[str] = "lesson_series"
    job_id: str | None = None
    lessons_created: int = 0
    notify: bool = True  # False for imported series (E28)


@dataclass(frozen=True, kw_only=True)
class SeriesUpdated(DomainEvent):
    event_type: ClassVar[str] = "lesson_series.updated"
    subject_type: ClassVar[str] = "lesson_series"
    scope: str = "all"
    lessons_changed: int = 0


@dataclass(frozen=True, kw_only=True)
class SeriesEnded(DomainEvent):
    event_type: ClassVar[str] = "lesson_series.ended"
    subject_type: ClassVar[str] = "lesson_series"


@dataclass(frozen=True, kw_only=True)
class AvailabilityUpdated(DomainEvent):
    event_type: ClassVar[str] = "availability.updated"
    subject_type: ClassVar[str] = "tutor"


@dataclass(frozen=True, kw_only=True)
class AbsenceNotified(DomainEvent):
    """A family told us a student will miss a (group) lesson; the tutor is told (E13)."""

    event_type: ClassVar[str] = "attendance.absence_notified"
    subject_type: ClassVar[str] = "lesson"
    student_id: str
    note: str = ""


# --- Phase 2: time off (T15), reschedule requests (T13), self-booking (T14) ---------------------


@dataclass(frozen=True, kw_only=True)
class TimeOffRequested(DomainEvent):
    """Starts ``TimeOffApprovalWorkflow``."""

    event_type: ClassVar[str] = "time_off.requested"
    subject_type: ClassVar[str] = "time_off"
    tutor_id: str
    start: str
    end: str
    clashes: int = 0


@dataclass(frozen=True, kw_only=True)
class TimeOffApproved(DomainEvent):
    event_type: ClassVar[str] = "time_off.approved"
    subject_type: ClassVar[str] = "time_off"
    tutor_id: str
    automatic: bool = False  # approved when created (no approval needed)


@dataclass(frozen=True, kw_only=True)
class TimeOffDeclined(DomainEvent):
    event_type: ClassVar[str] = "time_off.declined"
    subject_type: ClassVar[str] = "time_off"
    tutor_id: str
    expired: bool = False  # nobody decided before it started


@dataclass(frozen=True, kw_only=True)
class CoverFlagged(DomainEvent):
    """Approved time off clashes with these lessons; ``cover_request_id`` is E19's request."""

    event_type: ClassVar[str] = "time_off.cover_flagged"
    subject_type: ClassVar[str] = "time_off"
    tutor_id: str
    lesson_ids: list[str] = field(default_factory=list)
    cover_request_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class RescheduleRequested(DomainEvent):
    """Starts ``RescheduleRequestWorkflow``."""

    event_type: ClassVar[str] = "reschedule.requested"
    subject_type: ClassVar[str] = "reschedule_request"
    lesson_id: str
    requester: str
    deadline: str
    options: int = 1


@dataclass(frozen=True, kw_only=True)
class RescheduleApproved(DomainEvent):
    event_type: ClassVar[str] = "reschedule.approved"
    subject_type: ClassVar[str] = "reschedule_request"
    lesson_id: str
    new_start: str


@dataclass(frozen=True, kw_only=True)
class RescheduleDeclined(DomainEvent):
    event_type: ClassVar[str] = "reschedule.declined"
    subject_type: ClassVar[str] = "reschedule_request"
    lesson_id: str
    reason: str = "declined"  # declined | expired | cancelled


@dataclass(frozen=True, kw_only=True)
class BookingHeld(DomainEvent):
    """A slot is held for an online booking; starts ``BookingHoldWorkflow``."""

    event_type: ClassVar[str] = "booking.held"
    subject_type: ClassVar[str] = "booking"
    tutor_id: str
    start: str
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class BookingSubmitted(DomainEvent):
    """The person pressed Book: ``status`` is awaiting_payment, awaiting_approval or
    confirmed."""

    event_type: ClassVar[str] = "booking.submitted"
    subject_type: ClassVar[str] = "booking"
    status: str


@dataclass(frozen=True, kw_only=True)
class BookingRequested(DomainEvent):
    """An online booking waits for staff approval (FR-08-9)."""

    event_type: ClassVar[str] = "booking.requested"
    subject_type: ClassVar[str] = "booking"
    tutor_id: str
    start: str


@dataclass(frozen=True, kw_only=True)
class BookingConfirmed(DomainEvent):
    event_type: ClassVar[str] = "booking.confirmed"
    subject_type: ClassVar[str] = "booking"
    lesson_id: str
    client_id: str
    new_client: bool = False


@dataclass(frozen=True, kw_only=True)
class BookingDeclined(DomainEvent):
    event_type: ClassVar[str] = "booking.declined"
    subject_type: ClassVar[str] = "booking"
    reason: str = "declined"  # declined | expired | cancelled
