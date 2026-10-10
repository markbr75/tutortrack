"""Domain events published by calendar sync and online meetings (E22 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class CalendarBusyUpdated(DomainEvent):
    """Busy blocks of a connected calendar changed (subject: the connection)."""

    event_type: ClassVar[str] = "calendar.busy_updated"
    subject_type: ClassVar[str] = "integration_connection"
    user_id: str
    changed: int = 0


@dataclass(frozen=True, kw_only=True)
class CalendarSettingsChanged(DomainEvent):
    """A user changed which calendars sync: signals ``changed`` to the workflow."""

    event_type: ClassVar[str] = "calendar.settings_changed"
    subject_type: ClassVar[str] = "integration_connection"


@dataclass(frozen=True, kw_only=True)
class RescheduleProposed(DomainEvent):
    """A tutor moved a lesson in their own calendar (two-way sync) and may not edit it."""

    event_type: ClassVar[str] = "calendar.reschedule_proposed"
    subject_type: ClassVar[str] = "lesson"
    user_id: str
    proposed_start: str
    proposed_end: str
    provider: str


@dataclass(frozen=True, kw_only=True)
class _MeetingEvent(DomainEvent):
    subject_type: ClassVar[str] = "lesson"
    provider: str
    meeting_id: str


@dataclass(frozen=True, kw_only=True)
class OnlineMeetingCreated(_MeetingEvent):
    event_type: ClassVar[str] = "online_meeting.created"


@dataclass(frozen=True, kw_only=True)
class OnlineMeetingUpdated(_MeetingEvent):
    event_type: ClassVar[str] = "online_meeting.updated"


@dataclass(frozen=True, kw_only=True)
class OnlineMeetingDeleted(_MeetingEvent):
    event_type: ClassVar[str] = "online_meeting.deleted"


@dataclass(frozen=True, kw_only=True)
class OnlineMeetingFailed(_MeetingEvent):
    """Provisioning failed after retries; staff were told."""

    event_type: ClassVar[str] = "online_meeting.failed"
    error: str = ""
