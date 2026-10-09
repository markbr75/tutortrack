"""Domain events published by catalogue (E06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ServiceCreated(DomainEvent):
    event_type: ClassVar[str] = "service.created"
    subject_type: ClassVar[str] = "service"


@dataclass(frozen=True, kw_only=True)
class ServiceUpdated(DomainEvent):
    """``rate_changed`` is true when a default charge or pay rate changed. E08 then offers
    to re-price unlocked future lessons (FR-06-4)."""

    event_type: ClassVar[str] = "service.updated"
    subject_type: ClassVar[str] = "service"
    fields: list[str] = field(default_factory=list)
    rate_changed: bool = False
