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
    event_type: ClassVar[str] = "lesson.cancelled"
    subject_type: ClassVar[str] = "lesson"
    reason: str = ""
    chargeable: bool = False
    notify: bool = True


@dataclass(frozen=True, kw_only=True)
class LessonCompleted(DomainEvent):
    event_type: ClassVar[str] = "lesson.completed"
    subject_type: ClassVar[str] = "lesson"
    job_id: str | None = None


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
