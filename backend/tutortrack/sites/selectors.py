"""Reads for branding, widgets, the public directory and the website (E24).

Public reads (``directory``, ``public_*``) expose only what the organisation chose to
publish: approved profile text, approved subjects, the town (if the org allows it) and
delivery modes; never surnames, contact details, addresses, rates or ratings it hasn't
published. Staff reads go through ``scope_queryset``.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.permissions import scope_queryset
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from .models import (
    BrandKit,
    PublicProfile,
    Site,
    SitePage,
    SitePageVersion,
    Testimonial,
    WidgetConfig,
)

# Optional profile sections a tutor may choose to show (FR-24-4 "approved fields only").
OPTIONAL_SECTIONS = ("qualifications", "languages", "experience", "location")


# --- staff ---------------------------------------------------------------------------------------


def brand_kits(user: Any) -> QuerySet[BrandKit]:
    return scope_queryset(user, BrandKit.objects.select_related("branch"), "sites.view")


def widget_configs(user: Any) -> QuerySet[WidgetConfig]:
    return scope_queryset(user, WidgetConfig.objects.all(), "sites.view")


def testimonials(user: Any) -> QuerySet[Testimonial]:
    return scope_queryset(user, Testimonial.objects.select_related("tutor"), "sites.view")


def public_profiles(user: Any) -> QuerySet[PublicProfile]:
    return scope_queryset(
        user,
        PublicProfile.objects.select_related("tutor", "approved_by"),
        "sites.profile.moderate",
    )


def sites(user: Any) -> QuerySet[Site]:
    return scope_queryset(user, Site.objects.all(), "sites.view")


def site_pages(user: Any) -> QuerySet[SitePage]:
    return scope_queryset(user, SitePage.objects.select_related("site"), "sites.view")


def page_versions(page: SitePage) -> QuerySet[SitePageVersion]:
    return SitePageVersion.objects.filter(page=page).select_related("published_by")


def tutor_for_user(user: Any) -> Any:
    from tutortrack.people.models import TutorProfile

    if not getattr(user, "is_authenticated", False):
        return None
    return TutorProfile.objects.filter(membership__user=user).first()


# --- public tutor directory ----------------------------------------------------------------------


def directory(
    *, q: str = "", subject: str = "", level: str = "", online: bool | None = None,
    location: str = "", subjects: list[str] | None = None,
) -> QuerySet[PublicProfile]:  # fmt: skip
    qs = PublicProfile.objects.filter(
        listed=True,
        tutor__public_profile=True,
        tutor__status="active",
        tutor__archived_at__isnull=True,
    ).exclude(published={})
    if q:
        qs = qs.filter(
            Q(published__display_name__icontains=q)
            | Q(published__headline__icontains=q)
            | Q(tutor__subjects__subject__icontains=q, tutor__subjects__approved=True)
        )
    if subject:
        qs = qs.filter(tutor__subjects__approved=True, tutor__subjects__subject__iexact=subject)
    if subjects:
        cond = Q()
        for name in subjects:
            cond |= Q(tutor__subjects__subject__iexact=name)
        qs = qs.filter(cond, tutor__subjects__approved=True)
    if level:
        qs = qs.filter(tutor__subjects__approved=True, tutor__subjects__level__iexact=level)
    if online is True:
        qs = qs.filter(tutor__delivers_online=True)
    elif online is False:
        qs = qs.filter(tutor__delivers_in_person=True)
    if location and get_setting("sites.directory_show_location"):
        qs = qs.filter(tutor__address__city__iexact=location)
    return qs.select_related("tutor", "tutor__address").distinct().order_by("slug")


def _subjects_of(tutor: Any) -> list[dict[str, str]]:
    seen: list[dict[str, str]] = []
    for s in tutor.subjects.filter(approved=True).order_by("subject", "level"):
        row = {"subject": s.subject, "level": s.level}
        if row not in seen:
            seen.append(row)
    return seen


def _location(tutor: Any) -> str:
    if not get_setting("sites.directory_show_location"):
        return ""
    address = getattr(tutor, "address", None)
    return (address.city or "") if address is not None else ""


def public_tutor_card(profile: PublicProfile) -> dict[str, Any]:
    tutor = profile.tutor
    p = profile.published
    show = set(p.get("show") or [])
    return {
        "slug": profile.slug,
        "display_name": p.get("display_name", ""),
        "headline": p.get("headline", ""),
        "photo_url": f"/api/v1/public/assets/{profile.photo_id}" if profile.photo_id else "",
        "subjects": _subjects_of(tutor),
        "online": tutor.delivers_online,
        "in_person": tutor.delivers_in_person,
        "location": _location(tutor) if "location" in show else "",
        **_rating(tutor.pk),
    }


_rating_providers: list[Any] = []


def register_rating_provider(provider: Any) -> Any:
    """E25 publishes tutors' average review rating: ``provider(tutor_id)`` returns
    ``(average, count)`` or None (when the organisation doesn't show ratings)."""
    if provider not in _rating_providers:
        _rating_providers.append(provider)
    return provider


def _rating(tutor_id: Any) -> dict[str, Any]:
    for provider in _rating_providers:
        found = provider(tutor_id)
        if found is not None:
            return {"rating": found[0], "review_count": found[1]}
    return {"rating": None, "review_count": 0}


def public_tutor_detail(profile: PublicProfile) -> dict[str, Any]:
    tutor = profile.tutor
    p = profile.published
    show = set(p.get("show") or [])
    data = public_tutor_card(profile)
    data["bio"] = p.get("bio", "")
    data["qualifications"] = (
        [
            {"title": q.title, "institution": q.institution, "year": q.year}
            for q in tutor.qualifications.all().order_by("-year", "title")
        ]
        if "qualifications" in show
        else []
    )
    data["languages"] = list(tutor.languages or []) if "languages" in show else []
    data["years_experience"] = tutor.years_experience if "experience" in show else None
    return data


def public_subjects() -> list[str]:
    from tutortrack.catalogue.models import Subject

    return list(Subject.objects.order_by("position", "name").values_list("name", flat=True)[:100])


def public_services(ids: list[Any], *, prices: bool) -> list[dict[str, Any]]:
    """Active services the org chose (or those with a public description)."""
    from tutortrack.catalogue.models import Service
    from tutortrack.tenancy.models import Organisation

    qs = Service.objects.filter(active=True).select_related("subject", "level")
    qs = qs.filter(pk__in=ids) if ids else qs.exclude(public_description="")
    org = Organisation.objects.get(pk=_org_id())
    locale = str(org.locale or "en-GB").replace("-", "_")
    out = []
    for service in qs.order_by("name")[:30]:
        row: dict[str, Any] = {
            "id": str(service.pk),
            "name": service.name,
            "description": service.public_description,
            "subject": service.subject.name if service.subject else "",
            "level": service.level.name if service.level else "",
            "format": service.format,
            "delivery_mode": service.delivery_mode,
            "duration_minutes": service.default_duration_minutes,
            "price": "",
            "price_amount": None,
            "currency": service.currency,
            "pricing_unit": service.pricing_unit,
            "pricing_unit_label": str(service.get_pricing_unit_display()),
        }
        if prices and service.charge_rate is not None:
            rate = service.charge_rate.round_to_minor()
            row["price"] = rate.format(locale)
            row["price_amount"] = str(rate.amount)
        out.append(row)
    return out


def _org_id() -> Any:
    from tutortrack.core.context import require_organisation_id

    return require_organisation_id()


def public_testimonials(limit: int, min_rating: int | None = None) -> list[dict[str, Any]]:
    qs = Testimonial.objects.filter(published=True)
    if min_rating:
        qs = qs.filter(rating__gte=min_rating)
    return [
        {
            "id": str(t.pk),
            "quote": t.quote,
            "author": t.author,
            "role": t.role,
            "rating": t.rating,
            "stars": "\u2605" * (t.rating or 0),
        }
        for t in qs.order_by("position", "-created_at")[:limit]
    ]


_asset_providers: list[Any] = []


def register_public_assets(provider: Any) -> Any:
    """Other apps publish files too (E20: images of public courses). ``provider()``
    returns the ids of files anyone may fetch."""
    if provider not in _asset_providers:
        _asset_providers.append(provider)
    return provider


def public_asset_ids(organisation: Any) -> set[str]:
    """Files anyone may fetch: brand kit images, listed tutors' photos, published pages'
    images, the site's sharing image and files other apps publish (course images)."""
    from . import brand as brand_mod

    ids = set(brand_mod.resolve(organisation).asset_ids())
    for kit in BrandKit.objects.exclude(branch__isnull=True):
        ids.update(
            str(v) for v in (kit.logo_id, kit.logo_dark_id, kit.favicon_id, kit.app_icon_id) if v
        )
    ids.update(
        str(v) for v in directory().exclude(photo__isnull=True).values_list("photo_id", flat=True)
    )
    for assets in SitePage.objects.filter(live_version__isnull=False).values_list(
        "live_version__assets", flat=True
    ):
        ids.update(str(a) for a in assets or [])
    site = Site.objects.first()
    if site is not None and site.og_image_id:
        ids.add(str(site.og_image_id))
    if site is not None:  # G6: published blog posts' cover images
        ids.update(
            str(v)
            for v in live_posts(site)
            .exclude(cover_image__isnull=True)
            .values_list("cover_image_id", flat=True)
        )
    for provider in _asset_providers:
        ids.update(str(v) for v in provider())
    return ids


def site() -> Site | None:
    return Site.objects.first()


def live_pages(site_obj: Site) -> QuerySet[SitePage]:
    return SitePage.objects.filter(site=site_obj, live_version__isnull=False).select_related(
        "live_version"
    )


# --- blog (G6, FR-24-4) --------------------------------------------------------------------------


def blog_posts(user: Any) -> QuerySet[Any]:
    from .models import BlogPost

    return scope_queryset(user, BlogPost.objects.select_related("site"), "sites.view")


def live_posts(site_obj: Site) -> QuerySet[Any]:
    from .models import BlogPost

    return BlogPost.objects.filter(
        site=site_obj, status=BlogPost.Status.PUBLISHED, published_at__lte=now()
    ).order_by("-published_at")


def post_card(post: Any, organisation: Any) -> dict[str, Any]:
    from . import brand as brand_mod

    return {
        "title": post.title,
        "href": f"/blog/{post.slug}",
        "excerpt": post.excerpt or post.body[:200],
        "published_at": post.published_at,
        "author": post.author_name,
        "image_url": (
            brand_mod.asset_url(organisation, str(post.cover_image_id), absolute=False)
            if post.cover_image_id
            else ""
        ),
    }
