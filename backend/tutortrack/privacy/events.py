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
