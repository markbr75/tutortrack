"""Outbox dispatcher: delivers committed events to registered subscribers.

* Rows are claimed with ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent workers never
  process the same event at the same time.
* Each subscriber runs in its own savepoint inside the event's tenant context; success is
  recorded in ``ProcessedEvent`` so a retry only re-runs the subscribers that failed.
* Failures back off exponentially; after ``OUTBOX["MAX_ATTEMPTS"]`` the event is
  dead-lettered (visible in the platform console, E30) and can be replayed.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta

import structlog
from django.conf import settings
from django.db import transaction

from ..context import tenant_context
from ..models import OutboxEvent, ProcessedEvent
from ..time import now
from .base import EventEnvelope
from .registry import subscribers_for

logger = structlog.get_logger(__name__)


def _backoff(attempts: int) -> timedelta:
    base = settings.OUTBOX["BACKOFF_BASE_SECONDS"]
    return timedelta(seconds=min(base * (2 ** (attempts - 1)), 3600))


def dispatch_event(event: OutboxEvent) -> bool:
    """Deliver one (locked) event to its subscribers. Returns True if fully dispatched."""
    envelope = EventEnvelope.from_payload(event.payload)
    already_done = set(
        ProcessedEvent.objects.filter(event=event).values_list("subscriber", flat=True)
    )
    errors: list[str] = []

    for subscriber in subscribers_for(event.event_type):
        if subscriber.name in already_done:
            continue
        scope = tenant_context(event.organisation_id) if event.organisation_id else nullcontext()
        try:
            with transaction.atomic(), scope:
                subscriber.handler(envelope)
                ProcessedEvent.objects.create(subscriber=subscriber.name, event=event)
        except Exception as exc:
            logger.exception(
                "outbox.subscriber_failed",
                event_id=str(event.id),
                event_type=event.event_type,
                subscriber=subscriber.name,
            )
            errors.append(f"{subscriber.name}: {exc!r}")

    current = now()
    if errors:
        event.attempts += 1
        event.last_error = "\n".join(errors)[:4000]
        if event.attempts >= settings.OUTBOX["MAX_ATTEMPTS"]:
            event.dead_lettered_at = current
            logger.error("outbox.dead_lettered", event_id=str(event.id), type=event.event_type)
        else:
            event.available_at = current + _backoff(event.attempts)
        event.save(update_fields=["attempts", "last_error", "dead_lettered_at", "available_at"])
        return False

    event.dispatched_at = current
    event.save(update_fields=["dispatched_at"])
    return True


def dispatch_batch(batch_size: int | None = None) -> int:
    """Claim and dispatch up to ``batch_size`` due events. Returns how many were handled."""
    batch_size = batch_size or settings.OUTBOX["BATCH_SIZE"]
    with transaction.atomic():
        events = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                dispatched_at__isnull=True,
                dead_lettered_at__isnull=True,
                available_at__lte=now(),
            )
            .order_by("available_at", "id")[:batch_size]
        )
        for event in events:
            dispatch_event(event)
    return len(events)


def replay_dead_letter(event: OutboxEvent) -> None:
    """Put a dead-lettered event back in the queue (platform console action)."""
    event.dead_lettered_at = None
    event.attempts = 0
    event.available_at = now()
    event.save(update_fields=["dead_lettered_at", "attempts", "available_at"])
