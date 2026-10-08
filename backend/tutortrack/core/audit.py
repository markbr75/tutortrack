"""Audit logging used by services for every mutation (docs/02-architecture.md §6).

with audit.track(client) as tracker:      # snapshots before
    client.name = "New name"
    client.save()
# -> AuditEntry(action="update", changes={"name": ["Old", "New name"]})

audit.record(invoice, "issue")            # explicit action, no diff
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from django.db import models

from .context import current_organisation_id, get_request_context
from .events.base import to_json_safe
from .models import AuditEntry

REDACTED = "[REDACTED]"
_IGNORED_FIELDS = frozenset({"updated_at", "updated_by"})


def object_type_of(instance: models.Model) -> str:
    return instance._meta.label_lower


def _sensitive_fields(instance: models.Model) -> frozenset[str]:
    return frozenset(getattr(instance, "audit_sensitive_fields", ()))


def snapshot(instance: models.Model, fields: Iterable[str] | None = None) -> dict[str, Any]:
    """JSON-safe dict of concrete field values keyed by field name."""
    wanted = set(fields) if fields is not None else None
    values: dict[str, Any] = {}
    for f in instance._meta.concrete_fields:
        if f.name in _IGNORED_FIELDS or (wanted is not None and f.name not in wanted):
            continue
        values[f.name] = getattr(instance, f.attname)
    result: dict[str, Any] = to_json_safe(values)
    return result


def diff(
    before: dict[str, Any], after: dict[str, Any], *, sensitive: Iterable[str] = ()
) -> dict[str, list[Any]]:
    """``{field: [old, new]}`` for changed fields; sensitive values are redacted."""
    hidden = set(sensitive)
    changes: dict[str, list[Any]] = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changes[key] = [REDACTED, REDACTED] if key in hidden else [old, new]
    return changes


def record(
    instance: models.Model,
    action: str,
    changes: dict[str, Any] | None = None,
    *,
    object_repr: str | None = None,
    organisation_id: Any = None,
) -> AuditEntry:
    """Write an audit entry for ``instance`` using the current request context."""
    ctx = get_request_context()
    org_id = (
        organisation_id or getattr(instance, "organisation_id", None) or current_organisation_id()
    )
    return AuditEntry.objects.create(
        organisation_id=org_id,
        actor_id=ctx.user_id,
        impersonator_id=ctx.impersonator_id,
        action=action,
        object_type=object_type_of(instance),
        object_id=str(instance.pk),
        object_repr=(object_repr if object_repr is not None else str(instance))[:200],
        changes=to_json_safe(changes or {}),
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:500],
        request_id=ctx.request_id or "",
    )


def record_create(instance: models.Model) -> AuditEntry:
    sensitive = _sensitive_fields(instance)
    after = snapshot(instance)
    return record(
        instance,
        "create",
        {k: [None, REDACTED if k in sensitive else v] for k, v in after.items()},
    )


def record_read(instance: models.Model, reason: str = "") -> AuditEntry:
    """Log access to sensitive data (E29: safeguarding notes, bank details, exports)."""
    return record(instance, "read", {"reason": reason} if reason else {})


@dataclass
class Tracker:
    instance: models.Model
    action: str
    before: dict[str, Any]
    entry: AuditEntry | None = field(default=None)


@contextmanager
def track(instance: models.Model, action: str = "update") -> Iterator[Tracker]:
    """Snapshot ``instance`` and record a diff on exit (only if something changed)."""
    tracker = Tracker(instance=instance, action=action, before=snapshot(instance))
    yield tracker
    changes = diff(tracker.before, snapshot(instance), sensitive=_sensitive_fields(instance))
    if changes:
        tracker.entry = record(instance, action, changes)
