"""Permission checks used everywhere (CLAUDE.md rule 7).

* ``has_perm(user, codename, obj=None)``: role grants with data scopes (E03 RBAC, via the
  ``identity.backends.RBACBackend`` auth backend). Always call this, not ``user.has_perm``.
* ``scope_queryset(user, qs, codename)``: restrict a queryset to the user's data scope
  (all / branch / own). Selectors call it so lists and details agree.
* DRF classes: ``HasPermission.for_("x.y")``, ``HasMethodPermission.for_({...})``,
  ``HasOrganisation``.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.utils.module_loading import import_string
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

# Codenames owned by core (see core.permission_registry).
PERMISSIONS = {
    "audit.view": "View the audit log",
    "audit.export": "Export the audit log (each export is audited)",
}


def has_perm(user: Any, codename: str, obj: Any = None) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return bool(user.has_perm(codename, obj))


def scope_queryset(user: Any, queryset: QuerySet[Any], codename: str) -> QuerySet[Any]:
    """Records of ``queryset`` the user may access under ``codename`` (none if no grant)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return queryset.none()
    scoper: Any = import_string(
        getattr(settings, "PERMISSION_SCOPER", "tutortrack.identity.rbac.scope_queryset")
    )
    result: QuerySet[Any] = scoper(user, queryset, codename)
    return result


def permission_scope(user: Any, codename: str) -> str | None:
    """The broadest data scope (``all``/``branch``/``own``) the user holds for ``codename``,
    or None. For queries ``scope_queryset`` cannot scope directly (aggregates over models
    without a ``branch`` field)."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return None
    if user.is_superuser:
        return "all"
    resolver: Any = import_string(
        getattr(settings, "PERMISSION_SCOPE_RESOLVER", "tutortrack.identity.rbac.scope_for")
    )
    scope: str | None = resolver(user, codename)
    return scope


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
