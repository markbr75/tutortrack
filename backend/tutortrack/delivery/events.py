"""Domain events published by lesson delivery (E09 §5).

``lesson.completed``, ``lesson.cancelled`` and ``attendance.recorded`` are published by
scheduling (it owns the lesson); E09 fills in the attendee outcomes and policy result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class LessonCompletionBlocked(DomainEvent):
    """A tutor could not complete a lesson: a prepaid client needs to top up."""

    event_type: ClassVar[str] = "lesson.completion_blocked"
    subject_type: ClassVar[str] = "lesson"
    client_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class LessonUnconfirmed(DomainEvent):
    """A past lesson is still planned: E13 nudges the tutor."""

    event_type: ClassVar[str] = "lesson.unconfirmed"
    subject_type: ClassVar[str] = "lesson"
    tutor_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class _ReportEvent(DomainEvent):
    subject_type: ClassVar[str] = "lesson_report"
    lesson_id: str
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class LessonReportRequested(_ReportEvent):
    """A completed lesson needs a report; starts the SLA workflow."""

    event_type: ClassVar[str] = "lesson_report.requested"
    due_at: str


@dataclass(frozen=True, kw_only=True)
class LessonReportDue(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.due"
    due_at: str


@dataclass(frozen=True, kw_only=True)
class LessonReportOverdue(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.overdue"
    pay_held: bool = False


@dataclass(frozen=True, kw_only=True)
class LessonReportEscalated(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.escalated"


@dataclass(frozen=True, kw_only=True)
class LessonReportSubmitted(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.submitted"


@dataclass(frozen=True, kw_only=True)
class LessonReportReturned(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.returned"
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class LessonReportApproved(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.approved"


@dataclass(frozen=True, kw_only=True)
class LessonReportShared(_ReportEvent):
    """E13 emails the rendered report to the client (and E15 shows it in the portal)."""

    event_type: ClassVar[str] = "lesson_report.shared"
    client_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class LessonReportCommented(_ReportEvent):
    event_type: ClassVar[str] = "lesson_report.commented"
    comment_id: str
    visibility: str


@dataclass(frozen=True, kw_only=True)
class MakeupCreditIssued(DomainEvent):
    event_type: ClassVar[str] = "makeup_credit.issued"
    subject_type: ClassVar[str] = "makeup_credit"
    student_id: str
    source_lesson_id: str
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class MakeupCreditConsumed(DomainEvent):
    event_type: ClassVar[str] = "makeup_credit.consumed"
    subject_type: ClassVar[str] = "makeup_credit"
    student_id: str
    lesson_id: str


@dataclass(frozen=True, kw_only=True)
class MakeupCreditVoided(DomainEvent):
    event_type: ClassVar[str] = "makeup_credit.voided"
    subject_type: ClassVar[str] = "makeup_credit"
    student_id: str
