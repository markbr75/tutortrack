"""Website, widgets and branding writes (E24). Every mutation is audited and publishes its
domain event inside the transaction. Custom-domain writes live in ``tenancy.custom_domains``.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.utils.text import slugify
from django.utils.translation import gettext as _
from rest_framework import serializers

from tutortrack.core import audit, entitlements
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, UpgradeRequired
from tutortrack.core.models import StoredFile
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import blocks as block_registry
from . import brand, cors, events, moderation, themes
from . import widgets as widget_registry
from .models import (
    BlogPost,
    BrandKit,
    PublicProfile,
    Site,
    SitePage,
    SitePageVersion,
    Testimonial,
    WidgetConfig,
)
from .selectors import OPTIONAL_SECTIONS

IMAGE_TYPES = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/svg+xml",
    "image/gif",
    "image/x-icon",
)
KIT_FILE_FIELDS = ("logo", "logo_dark", "favicon", "app_icon")
KIT_TEXT_FIELDS = (
    "primary_colour",
    "secondary_colour",
    "font",
    "email_header",
    "email_footer",
    "document_footer",
    "app_name",
)
THEME_VARIABLES = (
    "--tt-brand-color",
    "--tt-text",
    "--tt-surface",
    "--tt-border",
    "--tt-muted-color",
    "--tt-radius",
    "--tt-font",
)
_THEME_VALUE = re.compile(r"^[#\w\s,.'\"()%/+-]{1,80}$")
_GA = re.compile(r"^G-[A-Z0-9]{4,20}$")
_GTM = re.compile(r"^GTM-[A-Z0-9]{4,12}$")


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def bump_site_revision(organisation_id: Any = None) -> None:
    """Invalidate cached website pages (CDN keys include the revision)."""
    key = f"sites:rev:{organisation_id or require_organisation_id()}"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 2, None)


def _bump_after_commit() -> None:
    """Bump once the transaction commits. The organisation is captured now: the commit can
    happen after the tenant context has closed (e.g. seeding in one outer transaction)."""
    organisation_id = require_organisation_id()
    transaction.on_commit(lambda: bump_site_revision(organisation_id))


def site_revision(organisation_id: Any) -> int:
    return int(cache.get(f"sites:rev:{organisation_id}") or 1)


def _image(file_id: Any, field: str) -> StoredFile | None:
    if file_id in (None, ""):
        return None
    stored = StoredFile.objects.filter(pk=file_id).first()
    if stored is None:
        raise _invalid(field, _("Upload the file first."))
    if stored.content_type not in IMAGE_TYPES:
        raise _invalid(field, _("Choose an image (PNG, JPEG, WebP, SVG, GIF or ICO)."))
    return stored


# --- brand kit -----------------------------------------------------------------------------------


def _clean_social(links: Any) -> dict[str, str]:
    if not isinstance(links, dict):
        raise _invalid("social_links", _("Social links must be an object."))
    out: dict[str, str] = {}
    for network, url in links.items():
        if network not in brand.SOCIAL_NETWORKS:
            raise _invalid("social_links", _("Unknown social network: %(n)s") % {"n": network})
        url = str(url or "").strip()
        if not url:
            continue
        if not url.startswith("https://") or len(url) > 300 or any(c in url for c in "<>\"' "):
            raise _invalid("social_links", _("Social links must be https:// addresses."))
        out[network] = url
    return out


@transaction.atomic
def save_brand_kit(*, branch: Any = None, **changes: Any) -> BrandKit:
    """Create or update the organisation kit (``branch=None``) or a branch override."""
    kit = BrandKit.objects.select_for_update().filter(branch=branch).first()
    created = kit is None
    changed = sorted(
        set(changes) & {*KIT_FILE_FIELDS, *KIT_TEXT_FIELDS, "social_links", "hide_powered_by"}
    )
    if kit is None:
        kit = BrandKit(branch=branch)
    for name in ("primary_colour", "secondary_colour"):
        if name in changes and changes[name] and not brand.HEX.match(changes[name]):
            raise _invalid(name, _("Use a colour like #2563eb."))
        if name in changes:
            changes[name] = (changes[name] or "").lower()
    if changes.get("font") and changes["font"] not in brand.FONTS:
        raise _invalid("font", _("Choose one of the listed fonts."))
    if "social_links" in changes:
        changes["social_links"] = _clean_social(changes["social_links"])
    if changes.get("hide_powered_by"):
        entitlements.require("white_label")
    with audit.track(kit, "create" if created else "update"):
        for name in KIT_FILE_FIELDS:
            if name in changes:
                setattr(kit, name, _image(changes.pop(name), name))
        for name in (*KIT_TEXT_FIELDS, "social_links", "hide_powered_by"):
            if name in changes:
                setattr(kit, name, changes.pop(name))
        kit.save()
    publish(
        events.BrandKitUpdated(
            subject_id=kit.pk,
            branch=str(branch.pk) if branch is not None else None,
            fields=changed,
        ),
        branch_id=branch.pk if branch is not None else None,
    )
    _bump_after_commit()
    return kit


@transaction.atomic
def delete_brand_kit(kit: BrandKit) -> None:
    if kit.branch_id is None:
        raise BusinessRuleViolation(
            _("The organisation brand kit can't be deleted; edit it instead.")
        )
    audit.record(kit, "delete", {"branch": [str(kit.branch_id), None]})
    kit.delete()
    _bump_after_commit()


# --- widgets -------------------------------------------------------------------------------------


def _clean_theme(theme: Any) -> dict[str, str]:
    if not isinstance(theme, dict):
        raise _invalid("theme", _("Theme must be an object."))
    out = {}
    for key, value in theme.items():
        if key not in THEME_VARIABLES:
            raise _invalid("theme", _("Unknown theme setting: %(k)s") % {"k": key})
        value = str(value).strip()
        if not _THEME_VALUE.match(value):
            raise _invalid("theme", _("That theme value isn't allowed."))
        out[key] = value
    return out


def _clean_origins(origins: Any) -> list[str]:
    if not isinstance(origins, list) or len(origins) > 20:
        raise _invalid("allowed_origins", _("List up to 20 website addresses."))
    out = []
    for raw in origins:
        origin = cors.normalise_origin(str(raw))
        if not origin:
            raise _invalid(
                "allowed_origins",
                _("%(o)s isn't a website address like https://www.example.com.") % {"o": raw},
            )
        if origin not in out:
            out.append(origin)
    return out


def _kind(key: str) -> widget_registry.WidgetKind:
    kind = widget_registry.get(key)
    if kind is None:
        raise _invalid("kind", _("Unknown widget type."))
    if not kind.is_available():
        raise UpgradeRequired(
            _("Your plan doesn't include this widget."), extra={"feature": kind.feature}
        )
    return kind


def _options(kind: widget_registry.WidgetKind, raw: Any) -> dict[str, Any]:
    try:
        return widget_registry.clean_options(kind, raw)
    except serializers.ValidationError as exc:
        raise BusinessRuleViolation(
            _("Check the widget settings."), extra={"errors": {"options": exc.detail}}
        ) from exc


@transaction.atomic
def create_widget(
    *, kind: str, name: str, options: Any = None, theme: Any = None,
    allowed_origins: Any = None,
) -> WidgetConfig:  # fmt: skip
    k = _kind(kind)
    widget = WidgetConfig.objects.create(
        key=f"w-{secrets.token_hex(5)}",
        kind=k.key,
        name=name.strip()[:120] or str(k.label),
        options=_options(k, options),
        theme=_clean_theme(theme or {}),
        allowed_origins=_clean_origins(allowed_origins or []),
    )
    audit.record_create(widget)
    publish(
        events.WidgetSaved(subject_id=widget.pk, key=widget.key, kind=widget.kind, created=True)
    )
    org = require_organisation_id()
    transaction.on_commit(lambda: cors.forget(org))
    return widget


@transaction.atomic
def update_widget(widget: WidgetConfig, **changes: Any) -> WidgetConfig:
    kind = _kind(widget.kind)
    with audit.track(widget):
        if "name" in changes:
            widget.name = str(changes["name"]).strip()[:120] or widget.name
        if "options" in changes:
            widget.options = _options(kind, changes["options"])
        if "theme" in changes:
            widget.theme = _clean_theme(changes["theme"])
        if "allowed_origins" in changes:
            widget.allowed_origins = _clean_origins(changes["allowed_origins"])
        if "active" in changes:
            widget.active = bool(changes["active"])
        widget.save()
    publish(
        events.WidgetSaved(subject_id=widget.pk, key=widget.key, kind=widget.kind, created=False)
    )
    org = require_organisation_id()
    transaction.on_commit(lambda: cors.forget(org))
    return widget


@transaction.atomic
def delete_widget(widget: WidgetConfig) -> None:
    audit.record(widget, "delete", {"key": [widget.key, None]})
    widget.delete()
    org = require_organisation_id()
    transaction.on_commit(lambda: cors.forget(org))


# --- testimonials --------------------------------------------------------------------------------


@transaction.atomic
def save_testimonial(testimonial: Testimonial | None = None, **changes: Any) -> Testimonial:
    created = testimonial is None
    obj = testimonial or Testimonial()
    rating = changes.get("rating")
    if rating is not None and not 1 <= int(rating) <= 5:
        raise _invalid("rating", _("Ratings go from 1 to 5."))
    for field in ("quote", "author", "role"):
        if field in changes and moderation.issues(str(changes[field]), contact_filter=False):
            raise _invalid(field, _("Please remove offensive language."))
    with audit.track(obj, "create" if created else "update"):
        for field in ("quote", "author", "role", "rating", "tutor", "published", "position"):
            if field in changes:
                setattr(obj, field, changes[field])
        obj.full_clean(exclude=["organisation", "created_by", "updated_by"])
        obj.save()
    _bump_after_commit()
    return obj


@transaction.atomic
def delete_testimonial(testimonial: Testimonial) -> None:
    audit.record(testimonial, "delete", {"author": [testimonial.author, None]})
    testimonial.delete()
    _bump_after_commit()


# --- public tutor profiles (FR-24-3/5) -----------------------------------------------------------


def _unique_slug(base: str, exclude: Any = None) -> str:
    base = slugify(base)[:60] or "tutor"
    slug, n = base, 1
    qs = PublicProfile.objects.all()
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    while qs.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def default_display_name(tutor: Any) -> str:
    """First name and last initial: enough to recognise, not enough to find off-platform."""
    if tutor.display_name:
        return tutor.display_name
    initial = f" {tutor.last_name[:1]}." if tutor.last_name else ""
    return f"{tutor.first_name}{initial}".strip()


@transaction.atomic
def ensure_profile(tutor: Any) -> PublicProfile:
    profile = PublicProfile.objects.filter(tutor=tutor).first()
    if profile is not None:
        return profile
    name = default_display_name(tutor)
    profile = PublicProfile.objects.create(
        tutor=tutor,
        slug=_unique_slug(name),
        draft={
            "display_name": name,
            "headline": tutor.headline,
            "bio": tutor.bio_public,
            "show": ["qualifications", "experience"],
        },
    )
    audit.record_create(profile)
    return profile


def _clean_draft(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        "display_name": str(data.get("display_name", "")).strip()[:80],
        "headline": str(data.get("headline", "")).strip()[:200],
        "bio": str(data.get("bio", "")).strip()[:3000],
        "show": [s for s in (data.get("show") or []) if s in OPTIONAL_SECTIONS],
    }
    if not cleaned["display_name"]:
        raise _invalid("display_name", _("Add the name families will see."))
    contact_filter = bool(get_setting("sites.profile_contact_filter"))
    errors = {
        field: found
        for field in ("display_name", "headline", "bio")
        if (found := moderation.issues(str(cleaned[field]), contact_filter=contact_filter))
    }
    if errors:
        raise BusinessRuleViolation(
            _("Some of the profile text can't be published."), extra={"errors": errors}
        )
    return cleaned


def _set_listing(tutor: Any, listed: bool) -> None:
    from tutortrack.people.services import update_tutor

    if tutor.public_profile != listed:
        update_tutor(tutor, public_profile=listed)


@transaction.atomic
def save_profile(
    profile: PublicProfile, *, data: dict[str, Any], user: Any, moderator: bool,
) -> PublicProfile:  # fmt: skip
    """Save the tutor's (or staff's) edits. ``listed=False`` hides at once; otherwise the
    edits publish immediately for moderators, or when approval isn't required, and wait
    for approval otherwise."""
    if data.get("listed") is False:
        return hide_profile(profile)
    draft = _clean_draft({**profile.draft, **data})
    photo_given = "photo" in data
    photo = _image(data.get("photo"), "photo") if photo_given else profile.draft_photo
    if data.get("slug") and moderator:
        slug = slugify(str(data["slug"]))[:80]
        if PublicProfile.objects.exclude(pk=profile.pk).filter(slug=slug).exists():
            raise Conflict(_("Another tutor already uses that address."))
        profile.slug = slug or profile.slug
    with audit.track(profile):
        profile.draft = draft
        profile.draft_photo = photo
        profile.save()
    if moderator or not get_setting("sites.profile_approval_required"):
        return approve_profile(profile, user)
    profile.status = PublicProfile.Status.PENDING
    profile.submitted_at = now()
    profile.rejection_reason = ""
    profile.save(update_fields=["status", "submitted_at", "rejection_reason", "updated_at"])
    publish(events.PublicProfileSubmitted(subject_id=profile.pk, tutor_id=str(profile.tutor_id)))
    return profile


@transaction.atomic
def approve_profile(profile: PublicProfile, user: Any) -> PublicProfile:
    _clean_draft(profile.draft)  # re-check: settings may have tightened since submission
    with audit.track(profile, "approve"):
        profile.published = dict(profile.draft)
        profile.photo = profile.draft_photo
        profile.status = PublicProfile.Status.APPROVED
        profile.listed = True
        profile.approved_at = now()
        profile.approved_by = user if getattr(user, "is_authenticated", False) else None
        profile.rejection_reason = ""
        profile.save()
    _set_listing(profile.tutor, True)
    publish(
        events.PublicProfileApproved(
            subject_id=profile.pk, tutor_id=str(profile.tutor_id), slug=profile.slug
        )
    )
    _bump_after_commit()
    return profile


@transaction.atomic
def reject_profile(profile: PublicProfile, user: Any, reason: str) -> PublicProfile:
    if profile.status != PublicProfile.Status.PENDING:
        raise BusinessRuleViolation(_("Only profiles waiting for approval can be rejected."))
    reason = reason.strip()[:500]
    if not reason:
        raise _invalid("reason", _("Tell the tutor what to change."))
    with audit.track(profile, "reject"):
        profile.status = PublicProfile.Status.REJECTED
        profile.rejection_reason = reason
        profile.save()
    publish(
        events.PublicProfileRejected(
            subject_id=profile.pk, tutor_id=str(profile.tutor_id), reason=reason
        )
    )
    return profile


@transaction.atomic
def hide_profile(profile: PublicProfile) -> PublicProfile:
    with audit.track(profile, "hide"):
        profile.listed = False
        profile.status = PublicProfile.Status.HIDDEN
        profile.save()
    _set_listing(profile.tutor, False)
    publish(events.PublicProfileHidden(subject_id=profile.pk, tutor_id=str(profile.tutor_id)))
    _bump_after_commit()
    return profile


# --- website builder (FR-24-4) -------------------------------------------------------------------


def _clean_blocks(raw: Any) -> list[dict[str, Any]]:
    try:
        return block_registry.validate(raw)
    except serializers.ValidationError as exc:
        raise BusinessRuleViolation(
            _("Some blocks need attention."), extra={"errors": exc.detail}
        ) from exc


def _site_fields(site: Site, changes: dict[str, Any]) -> None:
    if "theme" in changes:
        if changes["theme"] not in themes.THEMES:
            raise _invalid("theme", _("Choose one of the themes."))
        site.theme = changes["theme"]
    if changes.get("analytics_id") and not _GA.match(changes["analytics_id"]):
        raise _invalid("analytics_id", _("Use a Google Analytics 4 ID like G-ABC123XYZ."))
    if changes.get("tag_manager_id") and not _GTM.match(changes["tag_manager_id"]):
        raise _invalid("tag_manager_id", _("Use a Tag Manager ID like GTM-ABC1234."))
    for name in (
        "name",
        "seo_title",
        "meta_description",
        "business_type",
        "analytics_id",
        "tag_manager_id",
        "cookie_banner",
    ):
        if name in changes:
            setattr(site, name, changes[name])
    if site.business_type not in ("EducationalOrganization", "LocalBusiness"):
        raise _invalid("business_type", _("Choose a business type."))
    if "og_image" in changes:
        site.og_image = _image(changes["og_image"], "og_image")


def _starter_pages(site: Site) -> None:
    from tutortrack.leads.models import Form

    form = Form.objects.filter(published=True).order_by("created_at").first()
    contact: list[dict[str, Any]] = [
        {
            "id": "intro",
            "type": "text",
            "props": {"heading": _("Get in touch"), "body": _("Tell us what you need.")},
        }
    ]
    if form is not None:
        contact.append({"id": "form", "type": "form", "props": {"heading": "", "form": form.slug}})
    starter = [
        (
            "",
            _("Home"),
            [
                {
                    "id": "hero",
                    "type": "hero",
                    "props": {
                        "heading": site.name,
                        "subheading": _("Expert tutors, matched to your child."),
                        "cta_label": _("Contact us"),
                        "cta_href": "/contact",
                    },
                },
                {
                    "id": "tutors",
                    "type": "tutor_grid",
                    "props": {"heading": _("Our tutors"), "limit": 6},
                },
                {
                    "id": "reviews",
                    "type": "testimonials",
                    "props": {"heading": _("What families say"), "limit": 3},
                },
            ],
        ),
        (
            "about",
            _("About"),
            [{"id": "about", "type": "text", "props": {"heading": _("About us"), "body": ""}}],
        ),
        (
            "tutors",
            _("Tutors"),
            [
                {
                    "id": "grid",
                    "type": "tutor_grid",
                    "props": {"heading": _("Our tutors"), "limit": 24},
                }
            ],
        ),
        ("contact", _("Contact"), contact),
    ]
    for position, (path, title, page_blocks) in enumerate(starter):
        SitePage.objects.create(
            site=site, path=path, title=title, position=position, blocks=_clean_blocks(page_blocks)
        )


@transaction.atomic
def create_site(*, name: str = "", **changes: Any) -> Site:
    if Site.objects.exists():
        raise Conflict(_("This organisation already has a website."))
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    site = Site(name=(name or org.name).strip()[:120])
    _site_fields(site, changes)
    site.save()
    audit.record_create(site)
    _starter_pages(site)
    return site


@transaction.atomic
def update_site(site: Site, **changes: Any) -> Site:
    publish_flag = changes.pop("published", None)
    with audit.track(site):
        _site_fields(site, changes)
        if publish_flag is not None and bool(publish_flag) != site.published:
            site.published = bool(publish_flag)
            site.published_at = now() if site.published else None
            publish(events.SitePublished(subject_id=site.pk, published=site.published))
        site.save()
    _bump_after_commit()
    return site


def _clean_path(path: Any) -> str:
    value = slugify(str(path or ""))[:80]
    if value in ("api", "tutors", "sitemap", "robots", "internal", "widgets", "static", "blog"):
        raise _invalid("path", _("That address is reserved."))
    return value


@transaction.atomic
def create_page(site: Site, *, title: str, path: str = "", **changes: Any) -> SitePage:
    clean = _clean_path(path or title)
    if SitePage.objects.filter(site=site, path=clean).exists():
        raise _invalid("path", _("Another page already uses that address."))
    page = SitePage(
        site=site,
        path=clean,
        title=title.strip()[:120],
        position=changes.get("position", SitePage.objects.filter(site=site).count()),
        blocks=_clean_blocks(changes.get("blocks", [])),
    )
    for name in ("nav_label", "show_in_nav", "seo_title", "meta_description"):
        if name in changes:
            setattr(page, name, changes[name])
    page.save()
    audit.record_create(page)
    return page


@transaction.atomic
def update_page(page: SitePage, **changes: Any) -> SitePage:
    with audit.track(page):
        if "path" in changes:
            clean = _clean_path(changes["path"]) if page.path != "" else ""
            if SitePage.objects.filter(site=page.site, path=clean).exclude(pk=page.pk).exists():
                raise _invalid("path", _("Another page already uses that address."))
            page.path = clean
        if "blocks" in changes:
            page.blocks = _clean_blocks(changes["blocks"])
        for name in (
            "title",
            "nav_label",
            "show_in_nav",
            "position",
            "seo_title",
            "meta_description",
        ):
            if name in changes:
                setattr(page, name, changes[name])
        if page.live_version_id is not None:
            page.status = SitePage.Status.CHANGED
        page.save()
    if "path" in changes or "show_in_nav" in changes or "position" in changes:
        _bump_after_commit()
    return page


@transaction.atomic
def delete_page(page: SitePage) -> None:
    if page.path == "":
        raise BusinessRuleViolation(_("The home page can't be deleted."))
    audit.record(page, "delete", {"path": [page.path, None]})
    page.delete()
    _bump_after_commit()


@transaction.atomic
def publish_page(page: SitePage, user: Any) -> SitePageVersion:
    """Snapshot the draft as the next version and make it live (FR-24-4)."""
    page = SitePage.objects.select_for_update().get(pk=page.pk)
    blocks = _clean_blocks(page.blocks)
    number = page.version + 1
    version = SitePageVersion.objects.create(
        page=page,
        number=number,
        title=page.title,
        seo_title=page.seo_title,
        meta_description=page.meta_description,
        blocks=blocks,
        assets=block_registry.asset_ids(blocks),
        published_by=user if getattr(user, "is_authenticated", False) else None,
    )
    with audit.track(page, "publish"):
        page.version = number
        page.live_version = version
        page.status = SitePage.Status.PUBLISHED
        page.save()
    publish(events.SitePagePublished(subject_id=page.pk, path=page.path, number=number))
    _bump_after_commit()
    return version


@transaction.atomic
def unpublish_page(page: SitePage) -> SitePage:
    if page.path == "":
        raise BusinessRuleViolation(_("Unpublish the whole website instead of its home page."))
    with audit.track(page, "unpublish"):
        page.live_version = None
        page.status = SitePage.Status.DRAFT
        page.save()
    _bump_after_commit()
    return page


@transaction.atomic
def restore_version(page: SitePage, number: int) -> SitePage:
    version = SitePageVersion.objects.filter(page=page, number=number).first()
    if version is None:
        raise _invalid("version", _("That version doesn't exist."))
    with audit.track(page, "restore"):
        page.blocks = list(version.blocks)
        page.title = version.title
        page.seo_title = version.seo_title
        page.meta_description = version.meta_description
        page.status = SitePage.Status.CHANGED if page.live_version_id else SitePage.Status.DRAFT
        page.save()
    return page


# --- blog and news (G6, FR-24-4) -----------------------------------------------------------------

POST_FIELDS = ("title", "excerpt", "body", "author_name", "seo_title", "meta_description")
MAX_BODY = 50_000


def _post_slug(site: Site, raw: Any, exclude: Any = None) -> str:
    value = slugify(str(raw or ""))[:120]
    if not value:
        raise _invalid("slug", _("Give the post an address."))
    clash = BlogPost.objects.filter(site=site, slug=value)
    if exclude is not None:
        clash = clash.exclude(pk=exclude)
    if clash.exists():
        raise _invalid("slug", _("Another post already uses that address."))
    return value


def _post_fields(post: BlogPost, changes: dict[str, Any]) -> None:
    for name in POST_FIELDS:
        if name in changes:
            setattr(post, name, str(changes[name] or "").strip())
    if len(post.body) > MAX_BODY:
        raise _invalid("body", _("Posts can be up to 50,000 characters."))
    if not post.title:
        raise _invalid("title", _("Give the post a title."))
    if "cover_image" in changes:
        post.cover_image = _image(changes["cover_image"], "cover_image")


@transaction.atomic
def create_post(site: Site, *, title: str, slug: str = "", **changes: Any) -> BlogPost:
    post = BlogPost(site=site, slug=_post_slug(site, slug or title))
    _post_fields(post, {"title": title, **changes})
    post.save()
    audit.record_create(post)
    return post


@transaction.atomic
def update_post(post: BlogPost, **changes: Any) -> BlogPost:
    with audit.track(post):
        if "slug" in changes and changes["slug"] != post.slug:
            post.slug = _post_slug(post.site, changes["slug"], exclude=post.pk)
        _post_fields(post, changes)
        post.save()
    if post.status == BlogPost.Status.PUBLISHED:
        _bump_after_commit()
    return post


@transaction.atomic
def publish_post(post: BlogPost, *, at: Any = None) -> BlogPost:
    """Make the post live now (or at ``at``, a scheduled date)."""
    post = BlogPost.objects.select_for_update().get(pk=post.pk)
    with audit.track(post, "publish"):
        post.status = BlogPost.Status.PUBLISHED
        post.published_at = at or post.published_at or now()
        post.save(update_fields=["status", "published_at", "updated_at"])
    publish(events.BlogPostPublished(subject_id=post.pk, slug=post.slug))
    _bump_after_commit()
    return post


@transaction.atomic
def unpublish_post(post: BlogPost) -> BlogPost:
    with audit.track(post, "unpublish"):
        post.status = BlogPost.Status.DRAFT
        post.save(update_fields=["status", "updated_at"])
    _bump_after_commit()
    return post


@transaction.atomic
def delete_post(post: BlogPost) -> None:
    audit.record(post, "delete", {"slug": [post.slug, None]})
    live = post.status == BlogPost.Status.PUBLISHED
    post.delete()
    if live:
        _bump_after_commit()
