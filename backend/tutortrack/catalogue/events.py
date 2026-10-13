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


@dataclass(frozen=True, kw_only=True)
class PricingChanged(DomainEvent):
    """A Phase 2 pricing input changed (tier or tutor rate, premium, discount, price list,
    holiday). Existing lessons keep their prices; admins re-price unlocked future lessons
    with ``POST /lessons/reprice`` (E08)."""

    event_type: ClassVar[str] = "pricing.changed"
    subject_type: ClassVar[str] = "pricing_rule"
    kind: str
    service_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class TutorTierAssigned(DomainEvent):
    """A tutor moved to a pay tier from ``effective_from``. With ``recalculate``, E08
    re-prices the tutor's unlocked lessons from that date."""

    event_type: ClassVar[str] = "tutor.tier_assigned"
    subject_type: ClassVar[str] = "tutor_tier_assignment"
    tutor_id: str
    tier_id: str
    effective_from: str
    recalculate: bool = False
