"""Domain event types and the envelope delivered to subscribers.

Define an event by subclassing ``DomainEvent``:

    @dataclass(frozen=True, kw_only=True)
    class LessonCompleted(DomainEvent):
        event_type: ClassVar[str] = "lesson.completed"
        subject_type: ClassVar[str] = "lesson"

        tutor_id: UUID
        attendee_outcomes: dict[str, str]

The dataclass fields (other than ``subject_id``) become the event's ``data``. Bump
``version`` when the shape changes incompatibly.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.dateparse import parse_datetime

from ..money import Money

EVENT_TYPES: dict[str, type[DomainEvent]] = {}


class EventJSONEncoder(DjangoJSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Money):
            return o.to_dict()
        return super().default(o)


def to_json_safe(value: Any) -> Any:
    """Round-trip through the encoder so payloads only contain JSON primitives."""
    return json.loads(json.dumps(value, cls=EventJSONEncoder))


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    event_type: ClassVar[str]
    subject_type: ClassVar[str]
    version: ClassVar[int] = 1

    subject_id: uuid.UUID | str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        event_type = cls.__dict__.get("event_type")
        if event_type is None:
            return  # intermediate abstract base
        existing = EVENT_TYPES.get(event_type)
        if existing is not None and existing.__qualname__ != cls.__qualname__:
            raise ValueError(f"Duplicate domain event type {event_type!r}")
        EVENT_TYPES[event_type] = cls

    def data(self) -> dict[str, Any]:
        values = {
            f.name: getattr(self, f.name)
            for f in dataclasses.fields(self)
            if f.name != "subject_id"
        }
        result: dict[str, Any] = to_json_safe(values)
        return result


@dataclass(frozen=True)
class EventEnvelope:
    """What subscribers receive. Mirrors the outbox payload and the webhook body (E27)."""

    id: uuid.UUID
    type: str
    version: int
    occurred_at: datetime
    organisation_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    actor: dict[str, Any]
    subject: dict[str, Any]
    data: dict[str, Any]
    changes: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = to_json_safe(dataclasses.asdict(self))
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> EventEnvelope:
        occurred_at = parse_datetime(payload["occurred_at"])
        if occurred_at is None:
            raise ValueError(f"Invalid occurred_at in event {payload.get('id')}")
        return cls(
            id=uuid.UUID(payload["id"]),
            type=payload["type"],
            version=int(payload["version"]),
            occurred_at=occurred_at,
            organisation_id=_uuid_or_none(payload.get("organisation_id")),
            branch_id=_uuid_or_none(payload.get("branch_id")),
            actor=payload.get("actor") or {"type": "system"},
            subject=payload["subject"],
            data=payload.get("data") or {},
            changes=payload.get("changes") or {},
        )


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    return None if value in (None, "") else uuid.UUID(str(value))
