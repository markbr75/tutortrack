from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class SensitiveUpdated(DomainEvent):
    """A family changed a student's support needs in the portal; staff are alerted."""

    event_type: ClassVar[str] = "portal.sensitive_updated"
    subject_type: ClassVar[str] = "student"
    name: str


@dataclass(frozen=True, kw_only=True)
class GuardianInvited(DomainEvent):
    """A parent invited another guardian to the household from the portal (FR-15-8)."""

    event_type: ClassVar[str] = "portal.guardian_invited"
    subject_type: ClassVar[str] = "contact"
    client_id: str
    invited_by: str


@dataclass(frozen=True, kw_only=True)
class StudentLoginChanged(DomainEvent):
    """A guardian created, re-PINned or removed a managed student login (FR-15-1)."""

    event_type: ClassVar[str] = "portal.student_login_changed"
    subject_type: ClassVar[str] = "student"
    action: str  # created | pin_changed | removed
