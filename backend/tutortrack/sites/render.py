"""Server-rendered website pages, sitemap and robots (FR-24-4).

Pages are rendered from the published version's blocks (or the draft, for the editor's
preview) with Django templates, so they are fast, crawlable and work without JavaScript;
only the enquiry form and the cookie banner use the widget script. Responses carry
``Cache-Control`` for the CDN and an ETag built from the site revision, which every
publish, brand or listing change bumps.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from . import blocks as block_registry
from . import brand as brand_mod
from . import selectors, themes
from .models import Site, SitePage

WIDGETS_ORIGIN_FALLBACK = "https://cdn.tutortrack.app"


def _json_ld(data: dict[str, Any]) -> SafeString:
    text = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    return mark_safe(text)  # noqa: S308 - JSON with <, > escaped, inside a script element


def _soft(hex_colour: str) -> str:
    """A very light tint of the brand colour for section backgrounds."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return "#{:02x}{:02x}{:02x}".format(*(round(v + (255 - v) * 0.9) for v in (r, g, b)))


def theme_css(brand: brand_mod.Brand, theme: themes.Theme) -> str:
    variables = {
        **theme.variables,
        "--tt-brand": brand.primary_colour,
        "--tt-on-brand": brand.on_primary,
        "--tt-link": brand.link_colour,
        "--tt-brand-soft": _soft(brand.primary_colour),
        "--tt-secondary": brand.secondary_colour,
        "--tt-font": brand_mod.font_stack(brand.font),
        "--tt-heading-font": brand_mod.font_stack(theme.heading_font or brand.font),
    }
    variables.setdefault("--tt-hero-text", "var(--tt-text)")
    body = "".join(f"{k}:{escape(v)};" for k, v in variables.items())
    return f":root{{{body}}}"


ANALYTICS_JS = (
    "(function(){var ga=%(ga)s,gtm=%(gtm)s;"
    "function allowed(){var m=document.cookie.match(/(?:^|; )tt_consent=([^;]*)/);"
    "if(!m)return false;"
    "try{return JSON.parse(decodeURIComponent(m[1])).analytics===true}catch(e){return false}}"
    "function load(){if(window.__ttAnalytics)return;window.__ttAnalytics=true;"
    "window.dataLayer=window.dataLayer||[];"
    "if(ga){var s=document.createElement('script');s.async=true;"
    "s.src='https://www.googletagmanager.com/gtag/js?id='+encodeURIComponent(ga);"
    "document.head.appendChild(s);window.gtag=function(){window.dataLayer.push(arguments)};"
    "window.gtag('js',new Date());window.gtag('config',ga);}"
    "if(gtm){window.dataLayer.push({'gtm.start':Date.now(),event:'gtm.js'});"
    "var t=document.createElement('script');t.async=true;"
    "t.src='https://www.googletagmanager.com/gtm.js?id='+encodeURIComponent(gtm);"
    "document.head.appendChild(t);}}"
    "if(allowed())load();"
    "window.addEventListener('tt-cookie-consent',function(e){if(e.detail&&e.detail.analytics)load()});"
    "window.addEventListener('tt:enquiry_submitted',function(e){"
    "if(window.gtag)window.gtag('event','generate_lead',{form:e.detail&&e.detail.form})});})();"
)


def analytics_script(site: Site) -> str:
    """Loads GA4/GTM only after analytics consent (E29 cookie banner). IDs are validated
    (``G-...``/``GTM-...``) and JSON-encoded. Allowed by a CSP hash, not a nonce, so cached
    pages stay valid."""
    if not (site.analytics_id or site.tag_manager_id):
        return ""
    return ANALYTICS_JS % {
        "ga": json.dumps(site.analytics_id or ""),
        "gtm": json.dumps(site.tag_manager_id or ""),
    }


def script_hash(script: str) -> str:
    import base64
    import hashlib

    digest = hashlib.sha256(script.encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def widgets_script_url() -> str:
    return str(getattr(settings, "WIDGETS_SCRIPT_URL", f"{WIDGETS_ORIGIN_FALLBACK}/widgets.js"))


def _schema(site: Site, organisation: Any, base: str, brand: brand_mod.Brand) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": site.business_type,
        "name": site.name or organisation.name,
        "url": base + "/",
    }
    if brand.logo_id:
        data["logo"] = f"{base}{brand_mod.asset_url(organisation, brand.logo_id, absolute=False)}"
    if organisation.contact_email:
        data["email"] = organisation.contact_email
    if organisation.contact_phone:
        data["telephone"] = organisation.contact_phone
    address = organisation.address or {}
    if address.get("city") or address.get("postcode"):
        data["address"] = {
            "@type": "PostalAddress",
            "addressLocality": address.get("city", ""),
            "postalCode": address.get("postcode", ""),
            "addressCountry": organisation.country,
        }
    links = [u for u in brand.social_links.values() if u]
    if links:
        data["sameAs"] = links
    return data


def render(
    *,
    request: Any,
    organisation: Any,
    site: Site,
    title: str,
    seo_title: str,
    meta_description: str,
    blocks: list[dict[str, Any]],
    path: str,
    preview: bool = False,
    extra: dict[str, Any] | None = None,
    template: str = "sites/page.html",
) -> str:
    brand = brand_mod.resolve(organisation)
    theme = themes.get(site.theme)
    base = f"{request.scheme}://{request.get_host()}" if request is not None else ""
    nav = [
        {"href": "/" + p.path, "label": p.nav_label or p.title, "current": p.path == path}
        for p in selectors.live_pages(site).filter(show_in_nav=True).order_by("position", "title")
    ]
    prepared = block_registry.prepare(blocks, organisation)
    fonts = {f for f in (brand.font, theme.heading_font) if f}
    context = {
        "org": organisation,
        "site": site,
        "brand": brand,
        "title": title,
        "page_title": seo_title
        or (f"{title} | {site.name}" if path else (site.seo_title or site.name)),
        "meta_description": meta_description or site.meta_description,
        "canonical": f"{base}/{path}" if path else f"{base}/",
        "og_image": (
            f"{base}{brand_mod.asset_url(organisation, str(site.og_image_id), absolute=False)}"
            if site.og_image_id
            else ""
        ),
        "logo_url": brand_mod.asset_url(organisation, brand.logo_id, absolute=False),
        "favicon_url": brand_mod.asset_url(organisation, brand.favicon_id, absolute=False),
        "theme_css": mark_safe(theme_css(brand, theme)),  # noqa: S308 - values escaped above
        "font_urls": [brand_mod.font_css_url(f) for f in sorted(fonts)],
        "nav": nav,
        "blocks": prepared,
        "needs_widgets": site.cookie_banner
        or any(b["type"] == "form" or b.get("widget") for b in prepared)
        or bool(extra and extra.get("needs_widgets")),
        "widgets_src": widgets_script_url(),
        "schema": _json_ld(_schema(site, organisation, base, brand)),
        "analytics_js": mark_safe(analytics_script(site)),  # noqa: S308 - fixed code, JSON ids
        "preview": preview,
        "year": organisation.created_at.year if organisation.created_at else "",
        "social": sorted(brand.social_links.items()),
        "og_type": "website",
        "rss_url": "/blog/rss.xml" if selectors.live_posts(site).exists() else "",
        **(extra or {}),
    }
    return render_to_string(template, context, request=request)


def content_security_policy(site: Site) -> str:
    from urllib.parse import urlsplit

    script = analytics_script(site)
    analytics = bool(script)
    inline = script_hash(script) if script else ""
    widgets = urlsplit(widgets_script_url())
    widget_origin = f"{widgets.scheme}://{widgets.netloc}" if widgets.netloc else ""
    gtm = "https://www.googletagmanager.com" if analytics else ""
    ga_connect = (
        "https://www.google-analytics.com https://*.google-analytics.com" if analytics else ""
    )
    directives = [
        "default-src 'self'",
        f"script-src 'self' {inline} {widget_origin} {gtm} https://challenges.cloudflare.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        "img-src 'self' data: https:",
        f"connect-src 'self' {widget_origin} {ga_connect}".strip(),
        "frame-src https://www.openstreetmap.org https://challenges.cloudflare.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ]
    return "; ".join(" ".join(d.split()) for d in directives)


def sitemap(base: str, site: Site) -> str:
    urls = [f"{base}/{p.path}" if p.path else f"{base}/" for p in selectors.live_pages(site)]
    urls += [f"{base}/tutors/{p.slug}" for p in selectors.directory()]
    posts = list(selectors.live_posts(site))
    if posts:  # G6: the blog
        urls += [f"{base}/blog", *(f"{base}/blog/{p.slug}" for p in posts)]
    body = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    )


def robots(base: str, site: Site | None) -> str:
    if site is None or not site.published:
        return "User-agent: *\nDisallow: /\n"
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {base}/sitemap.xml\n"


def rss(base: str, site: Site, organisation: Any, posts: list[Any]) -> str:
    """RSS 2.0 for ``/blog/rss.xml`` (G6, FR-24-4); text is escaped."""
    from email.utils import format_datetime

    items = "".join(
        "<item>"
        f"<title>{escape(p.title)}</title>"
        f"<link>{escape(f'{base}/blog/{p.slug}')}</link>"
        f'<guid isPermaLink="true">{escape(f"{base}/blog/{p.slug}")}</guid>'
        f"<pubDate>{format_datetime(p.published_at)}</pubDate>"
        f"<description>{escape(p.excerpt or p.body[:300])}</description>"
        "</item>"
        for p in posts
    )
    title = escape(site.name or organisation.name)
    description = escape(site.meta_description or site.name or organisation.name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{title}</title><link>{escape(base + '/blog')}</link>"
        f"<description>{description}</description>"
        f"<language>{escape(organisation.locale or 'en-GB')}</language>"
        f"{items}</channel></rss>"
    )


def page_for_path(site: Site, path: str) -> SitePage | None:
    return selectors.live_pages(site).filter(path=path).first()
