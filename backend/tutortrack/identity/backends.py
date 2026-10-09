"""Django authorisation backend that plugs RBAC (``identity.rbac``) into ``user.has_perm``,
which ``core.permissions.has_perm`` calls. Never authenticates."""

from __future__ import annotations

from typing import Any

from . import rbac


class RBACBackend:
    def authenticate(self, request: Any, **credentials: Any) -> None:
        return None

    def has_perm(self, user: Any, perm: str, obj: Any = None) -> bool:
        return rbac.has_perm(user, perm, obj)
