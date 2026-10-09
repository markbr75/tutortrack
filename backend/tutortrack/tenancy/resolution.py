"""Tenant resolution (FR-02-3).

Order: (1) verified custom domain (E24) → (2) ``<slug>.<TENANT_BASE_DOMAIN>`` (former slugs
redirect for 90 days) → (3) ``X-Organisation`` header, for members only → (4) the user's
last active organisation (on the root/app host).

An unknown tenant subdomain, or an ``X-Organisation`` the user cannot access, resolves to
``unknown=True`` and the middleware answers 404 (never 403, which would leak existence).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.http import HttpRequest

from tutortrack.core.time import now

from .models import Organisation, OrganisationDomain
from .slugs import is_reserved

SESSION_KEY = "organisation_id"
HEADER = "X-Organisation"


@dataclass(frozen=True)
class Resolution:
    organisation: Organisation | None = None
    via: str = ""  # custom_domain | subdomain | header | last_active
    redirect_to: str | None = None
    unknown: bool = False


def _host(request: HttpRequest) -> str:
    return request.get_host().split(":")[0].lower().rstrip(".")


def _subdomain_label(host: str) -> str | None:
    base = settings.TENANT_BASE_DOMAIN.lower()
    if not host.endswith(f".{base}"):
        return None
    label = host[: -(len(base) + 1)]
    return label if label and "." not in label else None


def _redirect_url(request: HttpRequest, organisation: Organisation) -> str:
    port = request.get_host().partition(":")[2]
    host = f"{organisation.slug}.{settings.TENANT_BASE_DOMAIN}" + (f":{port}" if port else "")
    scheme = "https" if request.is_secure() else "http"
    # A URL for HttpResponseRedirect, not an HTML response body.
    return f"{scheme}://{host}{request.get_full_path()}"  # nosemgrep


def _from_header(request: HttpRequest, user: Any) -> Resolution | None:
    raw = request.headers.get(HEADER, "").strip()
    if not raw:
        return None
    if not getattr(user, "is_authenticated", False):
        return Resolution(unknown=True)
    try:
        org = Organisation.objects.filter(pk=uuid.UUID(raw)).first()
    except ValueError:
        org = Organisation.objects.filter(slug=raw.lower()).first()
    if org is None or not _may_use(user, org):
        return Resolution(unknown=True)
    return Resolution(org, via="header")


def _may_use(user: Any, organisation: Organisation) -> bool:
    from tutortrack.identity.selectors import membership_for

    return bool(user.is_superuser) or membership_for(user, organisation.pk) is not None


def _last_active(request: HttpRequest, user: Any) -> Resolution:
    if not getattr(user, "is_authenticated", False):
        return Resolution()
    session = getattr(request, "session", None)
    remembered = session.get(SESSION_KEY) if session is not None else None
    if remembered:
        org = Organisation.objects.filter(pk=remembered).first()
        if org is not None and _may_use(user, org):
            return Resolution(org, via="last_active")
    from tutortrack.identity.selectors import memberships_for_user

    memberships = memberships_for_user(user)
    if memberships:
        return Resolution(memberships[0].organisation, via="last_active")
    return Resolution()


def resolve(request: HttpRequest) -> Resolution:
    host = _host(request)
    user = getattr(request, "user", None)

    custom = (
        OrganisationDomain.objects.filter(
            hostname=host, type=OrganisationDomain.Type.CUSTOM, verified_at__isnull=False
        )
        .select_related("organisation")
        .first()
    )
    if custom is not None:
        return Resolution(custom.organisation, via="custom_domain")

    label = _subdomain_label(host)
    if label is not None and not is_reserved(label):
        org = Organisation.objects.filter(slug=label).first()
        if org is not None:
            return Resolution(org, via="subdomain")
        former = (
            OrganisationDomain.objects.filter(
                hostname=label,
                type=OrganisationDomain.Type.SUBDOMAIN,
                redirect_until__gt=now(),
            )
            .select_related("organisation")
            .first()
        )
        if former is not None:
            return Resolution(redirect_to=_redirect_url(request, former.organisation))
        return Resolution(unknown=True)

    # Root/app host (or a reserved label such as app.tutortrack.app).
    return _from_header(request, user) or _last_active(request, user)
