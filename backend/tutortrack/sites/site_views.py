"""Hosted website views (FR-24-4). Anonymous, tenant-resolved by host, cached by the CDN.

Unpublished sites answer 404 to the public. Pages render from their live version only.
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from . import render, selectors, services

CACHE = "public, max-age=300, s-maxage=3600, stale-while-revalidate=86400"


def _site(request: HttpRequest) -> Any:
    organisation = getattr(request, "organisation", None)
    if organisation is None:
        raise Http404()
    site = selectors.site()
    if site is None or not site.published:
        raise Http404()
    return organisation, site


def _respond(request: HttpRequest, html: str, organisation: Any, site: Any) -> HttpResponse:
    etag = hashlib.sha256(html.encode()).hexdigest()[:32]
    if request.headers.get("If-None-Match") == f'"{etag}"':
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["ETag"] = f'"{etag}"'
    response["Cache-Control"] = CACHE
    response["Cache-Tag"] = f"site-{organisation.pk}-r{services.site_revision(organisation.pk)}"
    response["Content-Security-Policy"] = render.content_security_policy(site)
    return response


@require_GET
def page(request: HttpRequest, path: str) -> HttpResponse:
    organisation, site = _site(request)
    found = render.page_for_path(site, path)
    if found is None or found.live_version is None:
        raise Http404()
    version = found.live_version
    html = render.render(
        request=request,
        organisation=organisation,
        site=site,
        title=version.title,
        seo_title=version.seo_title,
        meta_description=version.meta_description,
        blocks=version.blocks,
        path=path,
    )
    return _respond(request, html, organisation, site)


@require_GET
def tutor_page(request: HttpRequest, slug: str) -> HttpResponse:
    organisation, site = _site(request)
    profile = selectors.directory().filter(slug=slug).first()
    if profile is None:
        raise Http404()
    detail = selectors.public_tutor_detail(profile)
    contact = render.page_for_path(site, "contact")
    html = render.render(
        request=request,
        organisation=organisation,
        site=site,
        title=detail["display_name"],
        seo_title="",
        meta_description=detail["headline"],
        blocks=[],
        path=f"tutors/{slug}",
        extra={"tutor": detail, "contact_href": "/contact" if contact else ""},
        template="sites/tutor.html",
    )
    return _respond(request, html, organisation, site)


@require_GET
def sitemap(request: HttpRequest) -> HttpResponse:
    _organisation, site = _site(request)
    base = f"{request.scheme}://{request.get_host()}"
    response = HttpResponse(render.sitemap(base, site), content_type="application/xml")
    response["Cache-Control"] = CACHE
    return response


@require_GET
def robots(request: HttpRequest) -> HttpResponse:
    organisation = getattr(request, "organisation", None)
    site = selectors.site() if organisation is not None else None
    base = f"{request.scheme}://{request.get_host()}"
    response = HttpResponse(render.robots(base, site), content_type="text/plain")
    response["Cache-Control"] = CACHE
    return response
