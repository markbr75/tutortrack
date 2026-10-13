"""Communications domain events (E16-T09). Push subscriptions are internal: they are not
offered as webhook event types (``developer.catalogue.PUBLIC_AGGREGATES``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _PushSubscriptionEvent(DomainEvent):
    subject_type: ClassVar[str] = "push_subscription"
    user_id: str
    push_service: str  # the host only; the endpoint is a secret


@dataclass(frozen=True, kw_only=True)
class PushSubscriptionAdded(_PushSubscriptionEvent):
    """A user turned on push notifications on a device."""

    event_type: ClassVar[str] = "push_subscription.added"


@dataclass(frozen=True, kw_only=True)
class PushSubscriptionRemoved(_PushSubscriptionEvent):
    """A device stopped receiving pushes (removed by the user, or expired at the service)."""

    event_type: ClassVar[str] = "push_subscription.removed"
    reason: str  # removed | expired | failing
