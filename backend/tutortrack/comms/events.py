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


# --- Phase 2: broadcasts, inbox and sender domains (E13-T10..T12) -------------------------------


@dataclass(frozen=True, kw_only=True)
class _BroadcastEvent(DomainEvent):
    subject_type: ClassVar[str] = "broadcast"
    channel: str
    purpose: str


@dataclass(frozen=True, kw_only=True)
class BroadcastScheduled(_BroadcastEvent):
    """Starts ``BroadcastWorkflow`` (wait, resolve the segment, send in batches)."""

    event_type: ClassVar[str] = "broadcast.scheduled"
    scheduled_for: str | None = None


@dataclass(frozen=True, kw_only=True)
class BroadcastSent(_BroadcastEvent):
    event_type: ClassVar[str] = "broadcast.sent"
    recipients: int
    queued: int
    skipped: int


@dataclass(frozen=True, kw_only=True)
class BroadcastCancelled(_BroadcastEvent):
    event_type: ClassVar[str] = "broadcast.cancelled"


@dataclass(frozen=True, kw_only=True)
class MessageReceived(DomainEvent):
    """A message arrived in the inbox (email, text, WhatsApp or portal chat)."""

    event_type: ClassVar[str] = "message.received"
    subject_type: ClassVar[str] = "thread_message"
    thread_id: str
    channel: str
    author_type: str
    flagged: bool = False


@dataclass(frozen=True, kw_only=True)
class ThreadAssigned(DomainEvent):
    event_type: ClassVar[str] = "thread.assigned"
    subject_type: ClassVar[str] = "thread"
    assignee_id: str | None


@dataclass(frozen=True, kw_only=True)
class ThreadClosed(DomainEvent):
    event_type: ClassVar[str] = "thread.closed"
    subject_type: ClassVar[str] = "thread"


@dataclass(frozen=True, kw_only=True)
class SenderDomainVerified(DomainEvent):
    event_type: ClassVar[str] = "sender_domain.verified"
    subject_type: ClassVar[str] = "sender_domain"
    domain: str
