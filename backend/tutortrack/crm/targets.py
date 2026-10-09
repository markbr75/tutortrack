"""Records that CRM items (tags, notes, tasks, documents, timeline) can attach to.

Apps register their models: ``register("people.client", Client, "people.client.view")``.
Access to a target follows the record's own permission and data scope, so a tutor can only
see notes on records they can see.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import models

from tutortrack.core.permissions import scope_queryset


@dataclass(frozen=True)
class Target:
    name: str
    model: type[models.Model]
    view_permission: str
    label: str


_targets: dict[str, Target] = {}


def register(
    target_type: str, model: type[models.Model], view_permission: str, label: str = ""
) -> None:
    _targets[target_type] = Target(target_type, model, view_permission, label or target_type)


def get(target_type: str) -> Target | None:
    return _targets.get(target_type)


def all_targets() -> list[Target]:
    return list(_targets.values())


def visible_ids(user: Any, target_type: str, ids: list[str]) -> set[str]:
    target = _targets.get(target_type)
    if target is None:
        return set()
    qs = scope_queryset(
        user, target.model._default_manager.filter(pk__in=ids), target.view_permission
    )
    return {str(pk) for pk in qs.values_list("pk", flat=True)}


def can_see(user: Any, target_type: str, target_id: str) -> bool:
    try:
        return str(target_id) in visible_ids(user, target_type, [str(target_id)])
    except (ValueError, TypeError):
        return False


def describe(target_type: str, target_id: str) -> str:
    target = _targets.get(target_type)
    if target is None:
        return ""
    obj = target.model._default_manager.filter(pk=target_id).first()
    return str(obj) if obj is not None else ""
