from __future__ import annotations

import uuid
from typing import Any

from django.db import connection, transaction

from ..context import current_organisation_id, get_request_context
from ..models import OutboxEvent
from ..time import now
from .base import DomainEvent, EventEnvelope, to_json_safe

_DEDUPE_NAMESPACE = uuid.UUID("6f2b8a52-6d0c-4c55-9b5c-0e9a6f1c2d31")


class PublishOutsideTransaction(RuntimeError):
    pass


def _default_actor() -> dict[str, Any]:
    ctx = get_request_context()
    if ctx.workflow_id is not None:
        return {"type": "workflow", "id": ctx.workflow_id}
    if ctx.user_id is None:
        return {"type": "system", "id": None}
    actor: dict[str, Any] = {"type": "user", "id": str(ctx.user_id)}
    if ctx.impersonator_id is not None:
        actor["impersonator_id"] = str(ctx.impersonator_id)
    return actor


def publish(
    event: DomainEvent,
    *,
    organisation_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    actor: dict[str, Any] | None = None,
    changes: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> OutboxEvent:
    """Record ``event`` in the transactional outbox.

    Must be called inside ``transaction.atomic()`` so the event commits (or rolls back)
    together with the state change it describes. Dispatch happens after commit.

    ``dedupe_key`` makes publishing idempotent: the event id is derived from it, so a
    retried caller (e.g. a Temporal activity) publishes the event once.
    """
    if not connection.in_atomic_block:
        raise PublishOutsideTransaction(
            f"publish({event.event_type}) must be called inside transaction.atomic()"
        )
    org_id = organisation_id or current_organisation_id()
    occurred_at = now()
    if dedupe_key is not None:
        event_id = uuid.uuid5(_DEDUPE_NAMESPACE, dedupe_key)
        existing = OutboxEvent.objects.filter(pk=event_id).first()
        if existing is not None:
            return existing
    outbox = OutboxEvent(
        organisation_id=org_id,
        event_type=event.event_type,
        event_version=event.version,
        occurred_at=occurred_at,
        available_at=occurred_at,
        payload={},
    )
    if dedupe_key is not None:
        outbox.id = event_id
    envelope = EventEnvelope(
        id=outbox.id,
        type=event.event_type,
        version=event.version,
        occurred_at=occurred_at,
        organisation_id=org_id,
        branch_id=branch_id,
        actor=actor or _default_actor(),
        subject={"type": event.subject_type, "id": str(event.subject_id)},
        data=event.data(),
        changes=to_json_safe(changes or {}),
    )
    outbox.payload = envelope.to_payload()
    outbox.save(force_insert=True)
    transaction.on_commit(_kick_dispatcher)
    return outbox


def _kick_dispatcher() -> None:
    """Dispatch soon after commit. Beat also sweeps every few seconds as a fallback."""
    from .tasks import dispatch_outbox

    try:
        dispatch_outbox.delay()
    except Exception:
        import structlog

        structlog.get_logger(__name__).warning("outbox.kick_failed")
