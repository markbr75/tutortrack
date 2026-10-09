"""Domain events published by jobs (E07 §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class JobCreated(DomainEvent):
    event_type: ClassVar[str] = "job.created"
    subject_type: ClassVar[str] = "job"
    reference: str
    client_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class JobUpdated(DomainEvent):
    event_type: ClassVar[str] = "job.updated"
    subject_type: ClassVar[str] = "job"
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class JobStatusChanged(DomainEvent):
    """``future_lessons`` is ``keep`` or ``cancel``; E08 acts on it (FR-07-4)."""

    event_type: ClassVar[str] = "job.status_changed"
    subject_type: ClassVar[str] = "job"
    from_status: str
    to_status: str
    reason: str = ""
    future_lessons: str = "keep"


@dataclass(frozen=True, kw_only=True)
class JobTutorAssigned(DomainEvent):
    event_type: ClassVar[str] = "job.tutor_assigned"
    subject_type: ClassVar[str] = "job"
    tutor_id: str
    role: str
    offered: bool = False


@dataclass(frozen=True, kw_only=True)
class JobTutorRemoved(DomainEvent):
    event_type: ClassVar[str] = "job.tutor_removed"
    subject_type: ClassVar[str] = "job"
    tutor_id: str
    end_date: str | None = None


@dataclass(frozen=True, kw_only=True)
class JobTutorReplaced(DomainEvent):
    """E08 moves future unlocked lessons from ``old_tutor_id`` to ``new_tutor_id`` from
    ``effective_date`` and re-resolves pay."""

    event_type: ClassVar[str] = "job.tutor_replaced"
    subject_type: ClassVar[str] = "job"
    old_tutor_id: str
    new_tutor_id: str
    effective_date: str


@dataclass(frozen=True, kw_only=True)
class JobHoursCapReached(DomainEvent):
    event_type: ClassVar[str] = "job.hours_cap_reached"
    subject_type: ClassVar[str] = "job"
    used_hours: str
    cap_hours: str
    level: str  # "warning" (80%) or "reached"
