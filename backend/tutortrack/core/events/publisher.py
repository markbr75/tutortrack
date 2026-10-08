from __future__ import annotations

import uuid
from typing import Any

from django.db import connection, transaction

from ..context import current_organisation_id, get_request_context
from ..models import OutboxEvent
from ..time import now
from .base import DomainEvent, EventEnvelope, to_json_safe


class PublishOutsideTransaction(RuntimeError):
    pass


def _default_actor() -> dict[str, Any]:
    ctx = get_request_context()
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
) -> OutboxEvent:
    """Record ``event`` in the transactional outbox.

    Must be called inside ``transaction.atomic()`` so the event commits (or rolls back)
    together with the state change it describes. Dispatch happens after commit.
    """
    if not connection.in_atomic_block:
        raise PublishOutsideTransaction(
            f"publish({event.event_type}) must be called inside transaction.atomic()"
        )
    org_id = organisation_id or current_organisation_id()
    occurred_at = now()
    outbox = OutboxEvent(
        organisation_id=org_id,
        event_type=event.event_type,
        event_version=event.version,
        occurred_at=occurred_at,
        available_at=occurred_at,
        payload={},
    )
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
