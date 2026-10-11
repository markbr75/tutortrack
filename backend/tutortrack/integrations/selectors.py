"""Integration reads (E22-T01)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import has_perm, scope_queryset

from . import providers
from .models import IntegrationConnection

Status = IntegrationConnection.Status


def visible_connections(user: Any, *, include_disconnected: bool = False) -> QuerySet[Any]:
    """Admins (``integrations.view``) see every connection; anyone else their own."""
    qs = IntegrationConnection.objects.select_related("user")
    if not include_disconnected:
        qs = qs.exclude(status=Status.DISCONNECTED)
    if has_perm(user, "integrations.view"):
        return scope_queryset(user, qs, "integrations.view")
    return qs.filter(user=user)


def can_manage(user: Any, connection: IntegrationConnection) -> bool:
    if connection.user_id is not None and connection.user_id == user.pk:
        return has_perm(user, "integrations.personal") or has_perm(user, "integrations.manage")
    if connection.user_id is None:
        return may_manage_provider(user, connection.provider)
    return has_perm(user, "integrations.manage")


def may_manage_provider(user: Any, provider: str) -> bool:
    """Organisation-level connections: ``integrations.manage`` or the provider's own
    permission (``ProviderSpec.manage_permission``)."""
    if has_perm(user, "integrations.manage"):
        return True
    try:
        extra = providers.get_spec(provider).manage_permission
    except providers.ProviderError:
        return False
    return bool(extra) and has_perm(user, extra)


def live(qs: QuerySet[Any]) -> QuerySet[Any]:
    return qs.filter(status__in=[Status.ACTIVE, Status.ERROR])


def user_connection(user_id: Any, provider: str) -> IntegrationConnection | None:
    return live(IntegrationConnection.objects.filter(user_id=user_id, provider=provider)).first()


def org_connection(provider: str) -> IntegrationConnection | None:
    return live(IntegrationConnection.objects.filter(user__isnull=True, provider=provider)).first()


def with_capability(capability: str, *, user_ids: Iterable[Any] | None = None) -> QuerySet[Any]:
    keys = [s.key for s in providers.all_specs() if capability in s.capabilities]
    qs = live(IntegrationConnection.objects.filter(provider__in=keys))
    if user_ids is not None:
        qs = qs.filter(user_id__in=list(user_ids))
    return qs
