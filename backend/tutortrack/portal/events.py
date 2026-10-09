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
