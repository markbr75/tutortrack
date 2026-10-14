from __future__ import annotations

from typing import Any

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.tenancy.custom_domains import challenge_name
from tutortrack.tenancy.models import OrganisationDomain

from .. import brand
from ..models import (
    BlogPost,
    BrandKit,
    PublicProfile,
    Site,
    SitePage,
    SitePageVersion,
    Testimonial,
    WidgetConfig,
)
from ..selectors import OPTIONAL_SECTIONS

# --- branding ------------------------------------------------------------------------------------


class ContrastSerializer(serializers.Serializer):
    primary_on_white = serializers.FloatField()
    text_on_primary = serializers.FloatField()
    on_primary = serializers.CharField()
    link_colour = serializers.CharField()
    secondary_on_white = serializers.FloatField(required=False)
    on_secondary = serializers.CharField(required=False)
    warnings = serializers.ListField(child=serializers.CharField())
    passes_aa = serializers.BooleanField()


class BrandKitSerializer(serializers.ModelSerializer):
    social_links = serializers.DictField(child=serializers.CharField(), read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    contrast = serializers.SerializerMethodField()

    class Meta:
        model = BrandKit
        fields = [
            "id",
            "branch",
            "branch_name",
            "logo",
            "logo_dark",
            "favicon",
            "app_icon",
            "primary_colour",
            "secondary_colour",
            "font",
            "email_header",
            "email_footer",
            "document_footer",
            "app_name",
            "social_links",
            "hide_powered_by",
            "contrast",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(ContrastSerializer)
    def get_contrast(self, obj: BrandKit) -> dict[str, Any]:
        return brand.contrast_report(
            obj.primary_colour or brand.DEFAULT_PRIMARY, obj.secondary_colour
        )


class BrandKitWriteSerializer(serializers.Serializer):
    branch = serializers.UUIDField(required=False, allow_null=True)
    logo = serializers.UUIDField(required=False, allow_null=True)
    logo_dark = serializers.UUIDField(required=False, allow_null=True)
    favicon = serializers.UUIDField(required=False, allow_null=True)
    app_icon = serializers.UUIDField(required=False, allow_null=True)
    primary_colour = serializers.CharField(max_length=7, required=False, allow_blank=True)
    secondary_colour = serializers.CharField(max_length=7, required=False, allow_blank=True)
    font = serializers.CharField(max_length=40, required=False, allow_blank=True)
    email_header = serializers.CharField(max_length=300, required=False, allow_blank=True)
    email_footer = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    document_footer = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    app_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    social_links = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False
    )
    hide_powered_by = serializers.BooleanField(required=False)


class BrandingOptionsSerializer(serializers.Serializer):
    fonts = serializers.ListField(child=serializers.CharField())
    social_networks = serializers.ListField(child=serializers.CharField())
    white_label = serializers.BooleanField()
    custom_domain = serializers.BooleanField()
    cname_target = serializers.CharField()
    site_base_domain = serializers.CharField()
    widgets_script_url = serializers.CharField()
    site_url = serializers.CharField()


# --- domains -------------------------------------------------------------------------------------


class DnsRecordSerializer(serializers.Serializer):
    record_type = serializers.CharField()
    name = serializers.CharField()
    value = serializers.CharField()
    purpose = serializers.CharField()


class DomainSerializer(serializers.ModelSerializer):
    dns_records = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = OrganisationDomain
        fields = [
            "id",
            "hostname",
            "purpose",
            "verification_status",
            "ssl_status",
            "verified_at",
            "cert_expires_at",
            "last_checked_at",
            "status_detail",
            "dns_records",
            "url",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(DnsRecordSerializer(many=True))
    def get_dns_records(self, obj: OrganisationDomain) -> list[dict[str, str]]:
        target = str(getattr(settings, "CUSTOM_DOMAINS", {}).get("CNAME_TARGET", ""))
        return [
            {
                "record_type": "CNAME",
                "name": obj.hostname,
                "value": target,
                "purpose": "routing",
            },
            {
                "record_type": "TXT",
                "name": challenge_name(obj.hostname),
                "value": obj.verification_token,
                "purpose": "verification",
            },
        ]

    @extend_schema_field(OpenApiTypes.STR)
    def get_url(self, obj: OrganisationDomain) -> str:
        return f"https://{obj.hostname}"


class DomainCreateSerializer(serializers.Serializer):
    hostname = serializers.CharField(max_length=253)
    purpose = serializers.ChoiceField(choices=OrganisationDomain.Purpose.choices)


# --- widgets -------------------------------------------------------------------------------------


class WidgetKindSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    element = serializers.CharField()
    description = serializers.CharField()
    available = serializers.BooleanField()


class WidgetSerializer(serializers.ModelSerializer):
    options = serializers.DictField(read_only=True)
    theme = serializers.DictField(child=serializers.CharField(), read_only=True)
    allowed_origins = serializers.ListField(child=serializers.CharField(), read_only=True)
    element = serializers.SerializerMethodField()
    embed_code = serializers.SerializerMethodField()
    wordpress_shortcode = serializers.SerializerMethodField()

    class Meta:
        model = WidgetConfig
        fields = [
            "id",
            "key",
            "kind",
            "name",
            "options",
            "theme",
            "allowed_origins",
            "active",
            "element",
            "embed_code",
            "wordpress_shortcode",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_element(self, obj: WidgetConfig) -> str:
        from .. import widgets

        kind = widgets.get(obj.kind)
        return kind.element if kind else ""

    @extend_schema_field(OpenApiTypes.STR)
    def get_embed_code(self, obj: WidgetConfig) -> str:
        from .. import embed

        return embed.snippet(obj, self.context.get("organisation"))

    @extend_schema_field(OpenApiTypes.STR)
    def get_wordpress_shortcode(self, obj: WidgetConfig) -> str:
        from .. import embed

        return embed.shortcode(obj)


class WidgetWriteSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    options = serializers.DictField(required=False)
    theme = serializers.DictField(child=serializers.CharField(), required=False)
    allowed_origins = serializers.ListField(
        child=serializers.CharField(max_length=200), required=False, max_length=20
    )
    active = serializers.BooleanField(required=False)


class WidgetUpdateSerializer(WidgetWriteSerializer):
    kind = serializers.CharField(max_length=40, required=False)


# --- testimonials --------------------------------------------------------------------------------


class TestimonialSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True, default="")

    class Meta:
        model = Testimonial
        fields = [
            "id",
            "quote",
            "author",
            "role",
            "rating",
            "tutor",
            "tutor_name",
            "published",
            "position",
            "created_at",
        ]
        read_only_fields = ["id", "tutor_name", "created_at"]
        extra_kwargs = {"rating": {"min_value": 1, "max_value": 5}}


# --- public profiles -----------------------------------------------------------------------------


class ProfileContentSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    headline = serializers.CharField(max_length=200, required=False, allow_blank=True)
    bio = serializers.CharField(max_length=3000, required=False, allow_blank=True)
    show = serializers.ListField(
        child=serializers.ChoiceField(choices=OPTIONAL_SECTIONS), required=False
    )


class PublicProfileSerializer(serializers.ModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    draft = ProfileContentSerializer(read_only=True)
    published = ProfileContentSerializer(read_only=True)
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PublicProfile
        fields = [
            "id",
            "tutor",
            "tutor_name",
            "slug",
            "status",
            "listed",
            "draft",
            "published",
            "photo",
            "draft_photo",
            "submitted_at",
            "approved_at",
            "approved_by_name",
            "rejection_reason",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_approved_by_name(self, obj: PublicProfile) -> str:
        user = obj.approved_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.email


class PublicProfileCreateSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()


class PublicProfileWriteSerializer(ProfileContentSerializer):
    photo = serializers.UUIDField(required=False, allow_null=True)
    listed = serializers.BooleanField(required=False)
    slug = serializers.SlugField(max_length=80, required=False)


class ProfileRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


# --- website -------------------------------------------------------------------------------------


class SiteSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "theme",
            "seo_title",
            "meta_description",
            "og_image",
            "business_type",
            "analytics_id",
            "tag_manager_id",
            "cookie_banner",
            "published",
            "published_at",
            "url",
            "updated_at",
        ]
        read_only_fields = ["id", "published_at", "url", "updated_at"]
        extra_kwargs = {"name": {"required": False}}

    @extend_schema_field(OpenApiTypes.STR)
    def get_url(self, obj: Site) -> str:
        from .. import embed

        return embed.site_url(self.context.get("organisation"))


class ThemeSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()


class BlockFieldSerializer(serializers.Serializer):
    name = serializers.CharField()
    kind = serializers.CharField()
    is_required = serializers.BooleanField()
    max_length = serializers.IntegerField(allow_null=True)


class BlockTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    fields = BlockFieldSerializer(many=True)  # type: ignore[assignment]


class SitePageSerializer(serializers.ModelSerializer):
    blocks = serializers.ListField(child=serializers.DictField(), required=False)
    live_version_number = serializers.IntegerField(
        source="live_version.number", read_only=True, default=None
    )

    class Meta:
        model = SitePage
        fields = [
            "id",
            "site",
            "path",
            "title",
            "nav_label",
            "show_in_nav",
            "position",
            "seo_title",
            "meta_description",
            "blocks",
            "status",
            "version",
            "live_version_number",
            "updated_at",
        ]
        read_only_fields = ["id", "site", "status", "version", "live_version_number", "updated_at"]
        extra_kwargs = {"path": {"required": False, "allow_blank": True}}


class SitePageVersionSerializer(serializers.ModelSerializer):
    published_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SitePageVersion
        fields = ["id", "number", "title", "created_at", "published_by_name"]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_published_by_name(self, obj: SitePageVersion) -> str:
        user = obj.published_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or user.email


class PageRestoreSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class PagePreviewSerializer(serializers.Serializer):
    html = serializers.CharField()


# --- public --------------------------------------------------------------------------------------


class PublicBrandingSerializer(serializers.Serializer):
    name = serializers.CharField()
    logo_url = serializers.CharField()
    logo_dark_url = serializers.CharField()
    favicon_url = serializers.CharField()
    app_icon_url = serializers.CharField()
    app_name = serializers.CharField()
    primary_colour = serializers.CharField()
    on_primary = serializers.CharField()
    link_colour = serializers.CharField()
    secondary_colour = serializers.CharField()
    font = serializers.CharField()
    font_family = serializers.CharField()
    font_css_url = serializers.CharField()
    social_links = serializers.DictField(child=serializers.CharField())
    show_powered_by = serializers.BooleanField()
    portal_url = serializers.CharField()
    login_url = serializers.CharField()


class SubjectLevelSerializer(serializers.Serializer):
    subject = serializers.CharField()
    level = serializers.CharField()


class PublicTutorSerializer(serializers.Serializer):
    slug = serializers.CharField()
    display_name = serializers.CharField()
    headline = serializers.CharField()
    photo_url = serializers.CharField()
    subjects = SubjectLevelSerializer(many=True)
    online = serializers.BooleanField()
    in_person = serializers.BooleanField()
    location = serializers.CharField()
    rating = serializers.FloatField(allow_null=True)  # E25, when shown publicly
    review_count = serializers.IntegerField()


class QualificationSerializer(serializers.Serializer):
    title = serializers.CharField()
    institution = serializers.CharField()
    year = serializers.IntegerField(allow_null=True)


class PublicTutorDetailSerializer(PublicTutorSerializer):
    bio = serializers.CharField()
    qualifications = QualificationSerializer(many=True)
    languages = serializers.ListField(child=serializers.CharField())
    years_experience = serializers.IntegerField(allow_null=True)


class PublicServiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    subject = serializers.CharField()
    level = serializers.CharField()
    format = serializers.CharField()
    delivery_mode = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    price = serializers.CharField()
    price_amount = serializers.CharField(allow_null=True)
    currency = serializers.CharField()
    pricing_unit = serializers.CharField()
    pricing_unit_label = serializers.CharField()


class PublicReviewSerializer(serializers.Serializer):
    id = serializers.CharField()
    quote = serializers.CharField()
    author = serializers.CharField()
    role = serializers.CharField()
    rating = serializers.IntegerField(allow_null=True)
    stars = serializers.CharField()


class PublicWidgetSerializer(serializers.Serializer):
    key = serializers.CharField()
    kind = serializers.CharField()
    element = serializers.CharField()
    options = serializers.DictField()
    theme = serializers.DictField(child=serializers.CharField())
    branding = PublicBrandingSerializer()


class ManifestIconSerializer(serializers.Serializer):
    src = serializers.CharField()
    sizes = serializers.CharField()
    type = serializers.CharField()
    purpose = serializers.CharField()


class ManifestShortcutSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.CharField()


class ManifestSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    lang = serializers.CharField()
    categories = serializers.ListField(child=serializers.CharField())
    shortcuts = ManifestShortcutSerializer(many=True)
    short_name = serializers.CharField()
    start_url = serializers.CharField()
    scope = serializers.CharField()
    display = serializers.CharField()
    theme_color = serializers.CharField()
    background_color = serializers.CharField()
    icons = ManifestIconSerializer(many=True)


class BlogPostSerializer(serializers.ModelSerializer):
    """A blog or news post (G6). ``body`` is plain text: paragraphs separated by a blank
    line."""

    cover_image = serializers.UUIDField(source="cover_image_id", required=False, allow_null=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = BlogPost
        fields = [
            "id", "site", "title", "slug", "excerpt", "body", "cover_image", "author_name",
            "status", "published_at", "seo_title", "meta_description", "url", "updated_at",
        ]  # fmt: skip
        read_only_fields = ["id", "site", "status", "published_at", "url", "updated_at"]
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    @extend_schema_field(serializers.CharField())
    def get_url(self, obj: BlogPost) -> str:
        return f"/blog/{obj.slug}"


class BlogPublishSerializer(serializers.Serializer):
    published_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Schedule for later; default now."
    )
