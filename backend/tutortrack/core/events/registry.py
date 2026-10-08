"""Subscriber registry. Apps register handlers in their ``handlers.py``:

    from tutortrack.core.events import EventEnvelope, subscribe

    @subscribe("lesson.completed")
    def create_charges(event: EventEnvelope) -> None: ...

``"*"`` subscribes to every event (notifications, automations, webhooks).
Handlers must be idempotent: the dispatcher records each (subscriber, event) pair once
it succeeds, but a handler can run again if it fails after doing partial work.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .base import EventEnvelope

Handler = Callable[[EventEnvelope], None]
WILDCARD = "*"


@dataclass(frozen=True)
class Subscriber:
    name: str
    event_type: str
    handler: Handler


_subscribers: dict[str, dict[str, Subscriber]] = {}


def _name_of(handler: Handler) -> str:
    return f"{handler.__module__}.{handler.__qualname__}"


def subscribe(*event_types: str, name: str | None = None) -> Callable[[Handler], Handler]:
    if not event_types:
        raise ValueError("subscribe() needs at least one event type")

    def decorator(handler: Handler) -> Handler:
        sub_name = name or _name_of(handler)
        for event_type in event_types:
            _subscribers.setdefault(event_type, {})[sub_name] = Subscriber(
                sub_name, event_type, handler
            )
        return handler

    return decorator


def unsubscribe(handler_or_name: Handler | str) -> None:
    name = handler_or_name if isinstance(handler_or_name, str) else _name_of(handler_or_name)
    for subs in _subscribers.values():
        subs.pop(name, None)


def subscribers_for(event_type: str) -> list[Subscriber]:
    specific = list(_subscribers.get(event_type, {}).values())
    names = {s.name for s in specific}
    wildcard = [s for s in _subscribers.get(WILDCARD, {}).values() if s.name not in names]
    return specific + wildcard
