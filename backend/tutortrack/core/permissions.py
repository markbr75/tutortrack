"""Permission checks. E01 provides the hook; E03 replaces ``has_perm`` with the RBAC engine
(roles, data scopes, field permissions). Code should always call ``has_perm`` here rather
than ``user.has_perm`` so the switch is transparent."""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


def has_perm(user: Any, codename: str, obj: Any = None) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return bool(user.has_perm(codename, obj))


class HasPermission(BasePermission):
    """DRF permission: ``permission_classes = [HasPermission.for_("audit.view")]``."""

    codename: str = ""

    @classmethod
    def for_(cls, codename: str) -> type[HasPermission]:
        return type(f"HasPermission_{codename.replace('.', '_')}", (cls,), {"codename": codename})

    def has_permission(self, request: Request, view: APIView) -> bool:
        return has_perm(request.user, self.codename)


class HasOrganisation(BasePermission):
    """Requires an organisation in context and an active membership in it (FR-02-7).

    Superusers (platform staff) pass without a membership; E30 adds reason capture and
    impersonation on top.
    """

    message = "No organisation selected, or you are not a member of it."

    def has_permission(self, request: Request, view: APIView) -> bool:
        # DRF's Request proxies unknown attributes to the underlying HttpRequest.
        if getattr(request, "organisation", None) is None:
            return False
        if getattr(request.user, "is_superuser", False):
            return True
        return getattr(request, "membership", None) is not None


class HasMethodPermission(BasePermission):
    """Per-HTTP-method codenames:
    ``HasMethodPermission.for_({"GET": "org.settings.view", "PATCH": "org.settings.manage"})``.
    Methods not listed fall back to the ``"*"`` entry, or are denied."""

    codenames: dict[str, str] = {}  # set per subclass by for_()

    @classmethod
    def for_(cls, codenames: dict[str, str]) -> type[HasMethodPermission]:
        name = "HasMethodPermission_" + "_".join(sorted(codenames)).replace("*", "any")
        return type(name, (cls,), {"codenames": dict(codenames)})

    def has_permission(self, request: Request, view: APIView) -> bool:
        method = request.method or "GET"
        if method in ("HEAD", "OPTIONS"):
            method = "GET"
        codename = self.codenames.get(method) or self.codenames.get("*")
        return codename is not None and has_perm(request.user, codename)
