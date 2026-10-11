"""Custom domains and hosted websites at the HTTP layer (E24 FR-24-2, FR-24-4).

``CustomDomainMiddleware`` (before sessions/CSRF): auth cookies are scoped per domain. A
shared ``SESSION_COOKIE_DOMAIN`` (``.tutortrack.app``) can't be set from
``portal.brightminds.co.uk``, so cookies whose domain doesn't cover the request host are
made host-only. In strict mode (production) it also refuses hosts that are neither
platform hosts nor connected custom domains, so ``ALLOWED_HOSTS`` can be ``*``.

``SiteHostMiddleware`` (after the tenant is resolved): requests to the hosted website
(``<slug>.<SITE_BASE_DOMAIN>`` or a custom domain whose purpose is ``site``) use the site
URLconf: pages, ``/tutors/<slug>``, ``sitemap.xml`` and ``robots.txt``, plus the API.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest

GetResponse = Callable[[HttpRequest], HttpResponse]
EXEMPT = ("/healthz", "/readyz")


def _host(request: HttpRequest) -> str:
    return request.get_host().split(":")[0].lower().rstrip(".")


def _config() -> dict[str, Any]:
    return dict(getattr(settings, "CUSTOM_DOMAINS", {}))


def _custom(host: str) -> tuple[str, str] | None:
    """(purpose, organisation id) of a verified custom domain, cached briefly."""
    key = f"sites:host:{host}"
    cached = cache.get(key)
    if cached is not None:
        return (str(cached[0]), str(cached[1])) if cached else None
    from tutortrack.tenancy.models import OrganisationDomain

    row = (
        OrganisationDomain.objects.filter(
            hostname=host, type=OrganisationDomain.Type.CUSTOM, verified_at__isnull=False
        )
        .values_list("purpose", "organisation_id")
        .first()
    )
    value = (row[0], str(row[1])) if row else None
    cache.set(key, list(value) if value else [], 60)
    return value


def platform_host(host: str) -> bool:
    config = _config()
    suffixes = [
        str(settings.TENANT_BASE_DOMAIN),
        str(config.get("SITE_BASE_DOMAIN", "")),
        str(config.get("CNAME_TARGET", "")),
    ]
    for url in (getattr(settings, "APP_URL", ""), getattr(settings, "PLATFORM_BASE_URL", "")):
        if url:
            suffixes.append(urlsplit(str(url)).hostname or "")
    suffixes += [str(h) for h in config.get("PLATFORM_HOSTS", []) or []]
    suffixes += ["localhost", "127.0.0.1"]
    return any(s and (host == s.lower() or host.endswith("." + s.lower())) for s in suffixes)


def cookie_domain_covers(domain: str, host: str) -> bool:
    domain = domain.lstrip(".").lower()
    return host == domain or host.endswith("." + domain)


class CustomDomainMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        host = _host(request)
        if (
            _config().get("STRICT_HOSTS")
            and request.path not in EXEMPT
            and not platform_host(host)
            and _custom(host) is None
        ):
            return HttpResponseBadRequest("Unknown host")
        response = self.get_response(request)
        for morsel in response.cookies.values():
            domain = morsel["domain"]
            if domain and not cookie_domain_covers(str(domain), host):
                morsel["domain"] = ""
        return response


def is_site_host(host: str) -> bool:
    from tutortrack.tenancy.resolution import site_subdomain_label

    if site_subdomain_label(host) is not None:
        return True
    custom = _custom(host)
    return custom is not None and custom[0] == "site"


class SiteHostMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if getattr(request, "organisation", None) is not None and is_site_host(_host(request)):
            request.urlconf = "tutortrack.sites.site_urls"
        return self.get_response(request)
