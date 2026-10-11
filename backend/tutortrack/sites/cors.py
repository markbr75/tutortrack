"""CORS for embedded widgets (FR-24-3): ``/api/v1/public/...`` answers cross-origin requests
only from the organisation's own sites: origins listed on its active widgets, its connected
custom domains and its hosted website. The tenant comes from the request host (the widget
calls ``https://<slug>.tutortrack.app`` or a custom domain), resolved here because
``CorsMiddleware`` runs before ``TenantMiddleware``. Origins are cached per organisation and
forgotten when widgets or domains change.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

PUBLIC_PREFIX = "/api/v1/public/"
CACHE_SECONDS = 300


def _key(organisation_id: Any) -> str:
    return f"sites:cors:{organisation_id}"


def normalise_origin(raw: str) -> str:
    """``https://www.example.com`` (scheme + host [+ port]) or ``""`` if invalid."""
    try:
        parts = urlsplit((raw or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return ""
    if (
        parts.scheme == "http"
        and parts.hostname not in ("localhost", "127.0.0.1")
        and not (parts.hostname.endswith(".localhost"))
    ):
        return ""
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        return ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


def allowed_origins(organisation: Any) -> frozenset[str]:
    cached = cache.get(_key(organisation.pk))
    if cached is not None:
        return frozenset(cached)
    from tutortrack.core.context import tenant_context
    from tutortrack.tenancy.models import OrganisationDomain

    from .models import WidgetConfig

    origins: set[str] = set()
    with tenant_context(organisation):
        for values in WidgetConfig.objects.filter(active=True).values_list(
            "allowed_origins", flat=True
        ):
            origins.update(o for o in (normalise_origin(v) for v in values or []) if o)
    for host in OrganisationDomain.objects.filter(
        organisation_id=organisation.pk,
        type=OrganisationDomain.Type.CUSTOM,
        verified_at__isnull=False,
    ).values_list("hostname", flat=True):
        origins.add(f"https://{host}")
    site_base = getattr(settings, "CUSTOM_DOMAINS", {}).get("SITE_BASE_DOMAIN", "")
    if site_base:
        origins.add(f"https://{organisation.slug}.{site_base}")
    cache.set(_key(organisation.pk), sorted(origins), CACHE_SECONDS)
    return frozenset(origins)


def forget(organisation_id: uuid.UUID | str | None) -> None:
    if organisation_id:
        cache.delete(_key(organisation_id))


def allow_widget_origin(sender: Any, request: HttpRequest, **kwargs: Any) -> bool:
    if not request.path_info.startswith(PUBLIC_PREFIX):
        return False
    origin = normalise_origin(request.headers.get("Origin", ""))
    if not origin:
        return False
    from tutortrack.tenancy.resolution import resolve

    try:
        organisation = resolve(request).organisation
    except Exception:  # an unresolvable host is simply not allowed
        return False
    if organisation is None:
        return False
    return origin in allowed_origins(organisation)


def connect() -> None:
    from corsheaders.signals import check_request_enabled

    check_request_enabled.connect(allow_widget_origin, dispatch_uid="sites.widget_cors")
