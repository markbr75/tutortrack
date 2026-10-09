"""Role-based access control with data scopes (FR-03-5).

``has_perm(user, codename, obj=None)`` and ``scope_queryset(user, qs, codename)`` are the
only entry points; they are reached through ``core.permissions`` so call sites never
import identity.

Data scopes on objects/querysets:
* ``all``: every record of the organisation.
* ``branch``: records whose ``branch_id`` is in the member's branches.
* ``own``: records linked to the user. Models opt in with
  ``@classmethod own_scope_q(cls, user) -> Q`` (querysets) and, optionally,
  ``is_owned_by(self, user) -> bool`` (single objects; defaults to the Q filter).
"""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.context import current_organisation_id
from tutortrack.core.permission_registry import matches

from .models import Membership
from .roles import ROLES, SCOPE_RANK, Grant

_CACHE_ATTR = "_tt_rbac"


def grants_for(membership: Membership) -> tuple[list[Grant], tuple[str, ...]]:
    """(grants, denies) for a membership: its role plus org-configured tutor toggles."""
    role = ROLES.get(membership.role)
    if role is None:
        return [], ()
    grants = list(role.grants)
    if membership.role == Membership.Role.TUTOR:
        from .tutor_access import toggle_grants

        grants.extend(toggle_grants())
    return grants, role.denies


def _context(user: Any) -> tuple[Membership | None, list[Grant], tuple[str, ...]] | None:
    org_id = current_organisation_id()
    if org_id is None or not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    cache: dict[uuid.UUID, Any] = user.__dict__.setdefault(_CACHE_ATTR, {})
    if org_id not in cache:
        from .selectors import membership_for

        membership = membership_for(user, org_id)
        grants, denies = grants_for(membership) if membership else ([], ())
        cache[org_id] = (membership, grants, denies)
    result: tuple[Membership | None, list[Grant], tuple[str, ...]] = cache[org_id]
    return result


def clear_cache(user: Any) -> None:
    user.__dict__.pop(_CACHE_ATTR, None)


def scope_for(user: Any, codename: str) -> str | None:
    """The broadest scope the user holds for ``codename`` here, or None."""
    ctx = _context(user)
    if ctx is None:
        return None
    membership, grants, denies = ctx
    if membership is None or any(matches(d, codename) for d in denies):
        return None
    best: str | None = None
    for grant in grants:
        if matches(grant.pattern, codename) and (
            best is None or SCOPE_RANK[grant.scope] > SCOPE_RANK[best]
        ):
            best = grant.scope
    return best


def _membership(user: Any) -> Membership:
    """The membership behind a granted scope (scope_for only grants with one)."""
    ctx = _context(user)
    if ctx is None or ctx[0] is None:
        raise RuntimeError("scope granted without a membership")
    return ctx[0]


def _branch_ids(membership: Membership) -> frozenset[uuid.UUID] | None:
    from .selectors import branch_ids_for

    return branch_ids_for(membership)


def has_perm(user: Any, codename: str, obj: Any = None) -> bool:
    scope = scope_for(user, codename)
    if scope is None:
        return False
    if obj is None or scope == "all":
        return True
    membership = _membership(user)
    if scope == "branch":
        ids = _branch_ids(membership)
        return ids is None or getattr(obj, "branch_id", None) in ids
    is_owned_by = getattr(obj, "is_owned_by", None)
    if callable(is_owned_by):
        return bool(is_owned_by(user))
    own_q = getattr(type(obj), "own_scope_q", None)
    if callable(own_q):
        return bool(type(obj)._default_manager.filter(own_q(user), pk=obj.pk).exists())
    return False


def scope_queryset(user: Any, queryset: QuerySet[Any], codename: str) -> QuerySet[Any]:
    """Restrict ``queryset`` to what ``user`` may see under ``codename``."""
    if getattr(user, "is_superuser", False) and user.is_active:
        return queryset
    scope = scope_for(user, codename)
    if scope is None:
        return queryset.none()
    if scope == "all":
        return queryset
    membership = _membership(user)
    if scope == "branch":
        ids = _branch_ids(membership)
        return queryset if ids is None else queryset.filter(branch_id__in=ids)
    own_q = getattr(queryset.model, "own_scope_q", None)
    return queryset.filter(own_q(user)) if callable(own_q) else queryset.none()


def permissions_for(user: Any) -> dict[str, str]:
    """``{codename: scope}`` for every registered codename the user holds here."""
    from tutortrack.core.permission_registry import all_permissions

    if getattr(user, "is_superuser", False) and user.is_active:
        return dict.fromkeys(all_permissions(), "all")  # platform staff (has_perm agrees)
    out = {}
    for codename in all_permissions():
        scope = scope_for(user, codename)
        if scope is not None:
            out[codename] = scope
    return out
