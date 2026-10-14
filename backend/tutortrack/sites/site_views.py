"""Hosted website views (FR-24-4). Anonymous, tenant-resolved by host, cached by the CDN.

Unpublished sites answer 404 to the public. Pages render from their live version only.
"""

from __future__ import annotations

import hashlib
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.utils.translation import gettext as _
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


# --- blog (G6, FR-24-4) --------------------------------------------------------------------------

POSTS_PER_PAGE = 10


@require_GET
def blog_index(request: HttpRequest) -> HttpResponse:
    organisation, site = _site(request)
    try:
        number = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        number = 1
    posts = list(
        selectors.live_posts(site)[(number - 1) * POSTS_PER_PAGE : number * POSTS_PER_PAGE + 1]
    )
    if number > 1 and not posts:
        raise Http404()
    has_next = len(posts) > POSTS_PER_PAGE
    html = render.render(
        request=request,
        organisation=organisation,
        site=site,
        title=str(_("Blog")),
        seo_title="",
        meta_description="",
        blocks=[],
        path="blog",
        extra={
            "posts": [selectors.post_card(p, organisation) for p in posts[:POSTS_PER_PAGE]],
            "page_number": number,
            "next_page": number + 1 if has_next else None,
            "previous_page": number - 1 if number > 1 else None,
        },
        template="sites/blog_list.html",
    )
    return _respond(request, html, organisation, site)


@require_GET
def blog_post(request: HttpRequest, slug: str) -> HttpResponse:
    organisation, site = _site(request)
    post = selectors.live_posts(site).filter(slug=slug).first()
    if post is None:
        raise Http404()
    card = selectors.post_card(post, organisation)
    base = f"{request.scheme}://{request.get_host()}"
    article = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "datePublished": post.published_at.isoformat() if post.published_at else "",
        "url": f"{base}/blog/{post.slug}",
        "publisher": {"@type": site.business_type, "name": site.name or organisation.name},
    }
    if post.author_name:
        article["author"] = {"@type": "Person", "name": post.author_name}
    if card["image_url"]:
        article["image"] = base + card["image_url"]
    html = render.render(
        request=request,
        organisation=organisation,
        site=site,
        title=post.title,
        seo_title=post.seo_title,
        meta_description=post.meta_description or post.excerpt,
        blocks=[],
        path=f"blog/{post.slug}",
        extra={
            "post": card,
            "paragraphs": [p for p in post.body.split("\n\n") if p.strip()],
            "og_type": "article",
            "article_schema": render._json_ld(article),
            **({"og_image": base + card["image_url"]} if card["image_url"] else {}),
        },
        template="sites/blog_post.html",
    )
    return _respond(request, html, organisation, site)


@require_GET
def blog_rss(request: HttpRequest) -> HttpResponse:
    organisation, site = _site(request)
    base = f"{request.scheme}://{request.get_host()}"
    posts = list(selectors.live_posts(site)[:20])
    response = HttpResponse(
        render.rss(base, site, organisation, posts), content_type="application/rss+xml"
    )
    response["Cache-Control"] = CACHE
    return response


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
