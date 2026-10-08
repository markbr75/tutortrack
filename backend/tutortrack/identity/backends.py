"""Interim permission backend: built-in membership roles → permission codenames.

E02 needs owners and admins to manage their organisation before E03 delivers RBAC
(Role/RolePermission, data scopes, custom roles). E03 replaces this backend; call sites
use ``core.permissions.has_perm`` and do not change.
"""

from __future__ import annotations

from typing import Any

from tutortrack.core.context import current_organisation_id

from .models import Membership

OWNER_ONLY = frozenset({"org.close"})
BRANCH_MANAGER = frozenset({"org.settings.view"})
FINANCE = frozenset({"org.settings.view"})


def role_grants(role: str, codename: str) -> bool:
    if role == Membership.Role.OWNER:
        return True
    if role == Membership.Role.ADMIN:
        return codename not in OWNER_ONLY
    if role == Membership.Role.BRANCH_MANAGER:
        return codename in BRANCH_MANAGER
    if role == Membership.Role.FINANCE:
        return codename in FINANCE
    return False


class MembershipRoleBackend:
    """Authorisation only (never authenticates)."""

    def authenticate(self, request: Any, **credentials: Any) -> None:
        return None

    def has_perm(self, user: Any, perm: str, obj: Any = None) -> bool:
        org_id = current_organisation_id()
        if org_id is None or not getattr(user, "is_active", False):
            return False
        cache: dict[Any, str | None] = user.__dict__.setdefault("_tt_role_cache", {})
        if org_id not in cache:
            from .selectors import membership_for

            membership = membership_for(user, org_id)
            cache[org_id] = membership.role if membership else None
        role = cache[org_id]
        return role is not None and role_grants(role, perm)
