"""Domain events and the transactional outbox (docs/02-architecture.md §5)."""

from .base import EVENT_TYPES, DomainEvent, EventEnvelope
from .publisher import PublishOutsideTransaction, publish
from .registry import WILDCARD, subscribe, subscribers_for, unsubscribe

__all__ = [
    "EVENT_TYPES",
    "WILDCARD",
    "DomainEvent",
    "EventEnvelope",
    "PublishOutsideTransaction",
    "publish",
    "subscribe",
    "subscribers_for",
    "unsubscribe",
]
