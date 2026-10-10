"""Outbox → webhooks (FR-27-3). The subscriber is registered for each public event type
explicitly (never ``"*"``). ``core`` autodiscovers handler modules before every app's
events are imported, so ``connect()`` runs from ``DeveloperConfig.ready`` (the last app),
once the event registry is complete."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from . import catalogue

SUBSCRIBER = "developer.webhooks"


def deliver_webhooks(event: EventEnvelope) -> None:
    from . import services

    services.enqueue_event(event)


def connect() -> None:
    subscribe(*catalogue.public_event_keys(), name=SUBSCRIBER)(deliver_webhooks)
