"""Website, widgets and white-label branding (E24).

* ``BrandKit``: the organisation's brand (``branch`` null) and optional per-branch overrides.
* ``WidgetConfig``: an embeddable widget instance (kind from ``sites.widgets`` registry).
* ``PublicProfile``: a tutor's opt-in public directory profile, with moderated edits.
* ``Testimonial``: published quotes for the reviews widget and testimonials block.
* ``Site`` / ``SitePage`` / ``SitePageVersion``: the hosted website builder.

Custom domains live in ``tenancy.OrganisationDomain`` (a platform routing table).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class BrandKit(TenantModel):
    """Logos, colours, font, email/document styling, PWA identity and social links.

    Unset fields on a branch kit inherit the organisation kit; unset organisation fields
    fall back to ``Organisation.logo``/``primary_colour`` and the platform defaults.
    """

    branch = models.OneToOneField(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    logo = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    logo_dark = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    favicon = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    primary_colour = models.CharField(max_length=7, blank=True, default="")
    secondary_colour = models.CharField(max_length=7, blank=True, default="")
    font = models.CharField(max_length=40, blank=True, default="")
    email_header = models.CharField(max_length=300, blank=True, default="")
    email_footer = models.TextField(blank=True, default="")
    document_footer = models.TextField(blank=True, default="")  # invoices, statements
    app_name = models.CharField(max_length=60, blank=True, default="")  # PWA name
    app_icon = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    social_links = models.JSONField(default=dict, blank=True)  # {network: url}
    hide_powered_by = models.BooleanField(default=False)  # needs the white_label entitlement

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation"], condition=Q(branch__isnull=True), name="brandkit_one_org"
            )
        ]

    def __str__(self) -> str:
        return f"Brand kit ({self.branch_id or 'organisation'})"


class WidgetConfig(TenantModel):
    """An embeddable widget: ``<tt-widget key="...">`` or a kind-specific element."""

    key = models.SlugField(max_length=40)
    kind = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    options = models.JSONField(default=dict, blank=True)  # validated by the kind
    theme = models.JSONField(default=dict, blank=True)  # CSS custom-property overrides
    allowed_origins = models.JSONField(default=list, blank=True)  # CORS for this org
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="widget_key_unique")
        ]

    def __str__(self) -> str:
        return self.name


class PublicProfile(TenantModel):
    """A tutor's public directory profile (FR-24-3/FR-24-5).

    ``published`` holds the approved content shown publicly; edits go to ``draft`` and,
    when ``sites.profile_approval_required`` is on, wait for staff approval.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Published")
        REJECTED = "rejected", _("Changes rejected")
        HIDDEN = "hidden", _("Hidden")

    tutor = models.OneToOneField(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="public_listing"
    )
    slug = models.SlugField(max_length=80)
    draft = models.JSONField(default=dict, blank=True)
    published = models.JSONField(default=dict, blank=True)
    photo = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    draft_photo = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    listed = models.BooleanField(default=False)  # tutor opted in and approved at least once
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rejection_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["slug"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "slug"], name="public_profile_slug")
        ]

    def __str__(self) -> str:
        return self.slug

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor__membership__user_id=getattr(user, "pk", None))


class Testimonial(TenantModel):
    """A quote shown by ``<tt-reviews>`` and the testimonials block. E25 will add collected
    reviews; until then staff enter them (with the author's permission)."""

    quote = models.TextField()
    author = models.CharField(max_length=120)  # as the author agreed to be named
    role = models.CharField(max_length=120, blank=True, default="")  # "Parent of a Year 10"
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    published = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["position", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
                name="testimonial_rating_1_5",
            )
        ]

    def __str__(self) -> str:
        return self.author


class Site(TenantModel):
    """The organisation's hosted website (one per organisation)."""

    name = models.CharField(max_length=120)
    theme = models.CharField(max_length=30, default="classic")
    seo_title = models.CharField(max_length=120, blank=True, default="")
    meta_description = models.CharField(max_length=300, blank=True, default="")
    og_image = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    business_type = models.CharField(max_length=30, default="EducationalOrganization")
    analytics_id = models.CharField(max_length=30, blank=True, default="")  # GA4 G-XXXX
    tag_manager_id = models.CharField(max_length=30, blank=True, default="")  # GTM-XXXX
    cookie_banner = models.BooleanField(default=True)
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [models.UniqueConstraint(fields=["organisation"], name="site_one_per_org")]

    def __str__(self) -> str:
        return self.name


class SitePage(TenantModel):
    """A page with a draft (``blocks``) and the version that is live (``live_version``)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        CHANGED = "changed", _("Unpublished changes")

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="pages")
    path = models.SlugField(max_length=80, blank=True)  # "" is the home page
    title = models.CharField(max_length=120)
    nav_label = models.CharField(max_length=40, blank=True, default="")
    show_in_nav = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    seo_title = models.CharField(max_length=120, blank=True, default="")
    meta_description = models.CharField(max_length=300, blank=True, default="")
    blocks = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=0)  # latest published version number
    live_version = models.ForeignKey(
        "SitePageVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["position", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "path"], name="site_page_path_unique")
        ]

    def __str__(self) -> str:
        return self.title


class SitePageVersion(TenantModel):
    """An immutable published snapshot (restore copies one back into the draft)."""

    page = models.ForeignKey(SitePage, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=120)
    seo_title = models.CharField(max_length=120, blank=True, default="")
    meta_description = models.CharField(max_length=300, blank=True, default="")
    blocks = models.JSONField(default=list)
    assets = models.JSONField(default=list, blank=True)  # StoredFile ids used by the blocks
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["page", "number"], name="site_page_version_unique")
        ]

    def __str__(self) -> str:
        return f"{self.page_id} v{self.number}"


class BlogPost(TenantModel):
    """A blog or news post on the hosted website (G6, FR-24-4): ``/blog``, ``/blog/<slug>``
    and the RSS feed ``/blog/rss.xml``. The body is plain text (paragraphs separated by a
    blank line), shown escaped."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    excerpt = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField(blank=True, default="")
    cover_image = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    author_name = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    seo_title = models.CharField(max_length=120, blank=True, default="")
    meta_description = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-published_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="blog_post_slug_unique")
        ]

    def __str__(self) -> str:
        return self.title
