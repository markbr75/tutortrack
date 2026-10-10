"""Developer platform reads (E27). Lists are scoped with ``scope_queryset``; models without a
``branch`` (connected apps, sandboxes) are visible only with an organisation-wide grant."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q, QuerySet

from tutortrack.core.context import require_organisation_id
from tutortrack.core.permissions import permission_scope, scope_queryset
from tutortrack.core.time import now

from .models import (
    ApiKey,
    OAuthApplication,
    OAuthGrant,
    Sandbox,
    WebhookDelivery,
    WebhookEndpoint,
)


def _org_wide(user: Any, qs: QuerySet[Any], codename: str) -> QuerySet[Any]:
    return qs if permission_scope(user, codename) == "all" else qs.none()


def api_keys(user: Any) -> QuerySet[ApiKey]:
    qs = ApiKey.objects.select_related("user", "branch")
    return scope_queryset(user, qs, "developer.apikey.manage")


def oauth_applications(user: Any) -> QuerySet[OAuthApplication]:
    """Apps this organisation registered (partner apps are listed in the marketplace)."""
    qs = OAuthApplication.objects.filter(
        owner_organisation_id=require_organisation_id(), revoked_at__isnull=True
    )
    return _org_wide(user, qs, "developer.app.manage")


def partner_applications() -> QuerySet[OAuthApplication]:
    return OAuthApplication.objects.filter(
        owner_organisation_id__isnull=True, published=True, revoked_at__isnull=True
    )


def connected_apps(user: Any) -> QuerySet[OAuthGrant]:
    qs = OAuthGrant.objects.filter(revoked_at__isnull=True).select_related("application", "user")
    return _org_wide(user, qs, "developer.app.connect")


def webhook_endpoints(user: Any) -> QuerySet[WebhookEndpoint]:
    return scope_queryset(
        user, WebhookEndpoint.objects.select_related("branch"), "developer.webhook.view"
    )


def webhook_deliveries(user: Any, *, endpoint: Any = None, status: str = "") -> QuerySet[Any]:
    days = int(getattr(settings, "DEVELOPER_API", {}).get("WEBHOOK_LOG_DAYS", 30))
    visible = webhook_endpoints(user).values("pk")
    qs = WebhookDelivery.objects.filter(
        endpoint__in=visible, created_at__gte=now() - timedelta(days=days)
    ).select_related("endpoint")
    if endpoint:
        qs = qs.filter(endpoint_id=endpoint)
    if status:
        qs = qs.filter(status=status)
    return qs


def latest_payload(event_type: str) -> dict[str, Any] | None:
    """The most recent real payload of a type (Zapier/Make trigger samples)."""
    row = (
        WebhookDelivery.objects.filter(event_type=event_type, is_test=False)
        .order_by("-created_at")
        .values_list("payload", flat=True)
        .first()
    )
    return row


def sandboxes(user: Any) -> QuerySet[Sandbox]:
    return _org_wide(user, Sandbox.objects.all(), "developer.sandbox.manage")


def sandbox_of() -> str:
    from tutortrack.tenancy.settings_service import get_setting

    return str(get_setting("developer.sandbox_of") or "")


def usage_summary(user: Any) -> dict[str, Any]:
    """Counts for the developer overview."""
    since = now() - timedelta(days=1)
    deliveries = webhook_deliveries(user)
    return {
        "api_keys": api_keys(user).filter(revoked_at__isnull=True).count(),
        "connected_apps": connected_apps(user).count(),
        "webhook_endpoints": webhook_endpoints(user).count(),
        "deliveries_24h": deliveries.filter(created_at__gte=since).count(),
        "failed_24h": deliveries.filter(
            Q(status=WebhookDelivery.Status.FAILED) | Q(status=WebhookDelivery.Status.RETRYING),
            created_at__gte=since,
        ).count(),
    }
