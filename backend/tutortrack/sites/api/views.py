"""Website, widgets and branding API (E24).

Staff: ``/branding/options``, ``/brand-kits``, ``/domains`` (+ verify), ``/widgets``
(+ kinds), ``/testimonials``, ``/public-profiles`` (+ approve/reject/hide, ``mine`` for
tutors), ``/sites`` (+ themes, blocks), ``/sites/pages`` (+ publish, unpublish, preview,
versions, restore).

Public (anonymous, tenant from the host, rate-limited, CORS limited to the organisation's
sites by ``sites.cors``): ``/public/branding``, ``/public/manifest``, ``/public/tutors``,
``/public/tutors/{slug}``, ``/public/services``, ``/public/reviews``, ``/public/widgets/{key}``
and ``/public/assets/{id}``. They expose only what the organisation published. Enquiry
widgets post to the E17 form endpoint, which carries the CAPTCHA and its own rate limit.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core import entitlements
from tutortrack.core.api.pagination import CursorPagination
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.tenancy import custom_domains
from tutortrack.tenancy.models import Branch, OrganisationDomain

from .. import blocks, brand, embed, render, selectors, services, themes, widgets
from ..models import BrandKit, PublicProfile, Site, SitePage, Testimonial, WidgetConfig
from . import serializers as s

AUTH: list[Any] = [IsAuthenticated, HasOrganisation]
UUID = r"[0-9a-f-]{36}"


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _org(request: Request) -> Any:
    org = getattr(request, "organisation", None)
    if org is None:
        raise NotFound()
    return org


VIEW_MANAGE = {"GET": "sites.view"}

# --- branding ------------------------------------------------------------------------------------


@extend_schema(tags=["website"])
class BrandingOptionsView(APIView):
    permission_classes = perms({"GET": "sites.view"})

    @extend_schema(responses=s.BrandingOptionsSerializer)
    def get(self, request: Request) -> Response:
        org = _org(request)
        config = getattr(settings, "CUSTOM_DOMAINS", {})
        return Response(
            {
                "fonts": list(brand.FONTS),
                "social_networks": list(brand.SOCIAL_NETWORKS),
                "white_label": entitlements.has("white_label"),
                "custom_domain": entitlements.has("custom_domain"),
                "cname_target": config.get("CNAME_TARGET", ""),
                "site_base_domain": config.get("SITE_BASE_DOMAIN", ""),
                "widgets_script_url": settings.WIDGETS_SCRIPT_URL,
                "site_url": embed.site_url(org),
            }
        )


@extend_schema(tags=["website"])
class BrandKitViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The organisation's brand kit (``branch`` null) and per-branch overrides."""

    model = BrandKit
    serializer_class = s.BrandKitSerializer
    pagination_class = None
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "PATCH", "DELETE"), "sites.branding.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return selectors.brand_kits(self.request.user)

    def _branch(self, value: Any) -> Branch | None:
        if not value:
            return None
        return get_object_or_404(Branch.objects.all(), pk=value)

    @extend_schema(request=s.BrandKitWriteSerializer, responses={201: s.BrandKitSerializer})
    def create(self, request: Request) -> Response:
        """Create or update the kit for ``branch`` (null: the organisation kit)."""
        payload = s.BrandKitWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        branch = self._branch(data.pop("branch", None))
        kit = services.save_brand_kit(branch=branch, **data)
        return Response(s.BrandKitSerializer(kit).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.BrandKitWriteSerializer, responses=s.BrandKitSerializer)
    def partial_update(self, request: Request, pk: str) -> Response:
        kit = self.get_object()
        payload = s.BrandKitWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("branch", None)
        kit = services.save_brand_kit(branch=kit.branch, **data)
        return Response(s.BrandKitSerializer(kit).data)

    def perform_destroy(self, instance: BrandKit) -> None:
        services.delete_brand_kit(instance)


# --- custom domains ------------------------------------------------------------------------------


@extend_schema(tags=["website"])
class DomainViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Custom domains: add, see DNS records and status, check now, remove (FR-24-2)."""

    model = OrganisationDomain
    serializer_class = s.DomainSerializer
    pagination_class = None
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "DELETE"), "sites.domain.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return custom_domains.custom_domains().order_by("hostname")

    @extend_schema(request=s.DomainCreateSerializer, responses={201: s.DomainSerializer})
    def create(self, request: Request) -> Response:
        payload = s.DomainCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        domain = custom_domains.add_custom_domain(**payload.validated_data)
        return Response(s.DomainSerializer(domain).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.DomainSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request: Request, pk: str) -> Response:
        """Check the DNS now (also retries a failed verification)."""
        domain = custom_domains.request_check(self.get_object())
        return Response(s.DomainSerializer(domain).data)

    def perform_destroy(self, instance: OrganisationDomain) -> None:
        custom_domains.remove_custom_domain(instance)


# --- widgets -------------------------------------------------------------------------------------


@extend_schema(tags=["website"])
class WidgetViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    model = WidgetConfig
    serializer_class = s.WidgetSerializer
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "PATCH", "DELETE"), "sites.widget.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return selectors.widget_configs(self.request.user)

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "organisation": _org(self.request)}

    @extend_schema(request=s.WidgetWriteSerializer, responses={201: s.WidgetSerializer})
    def create(self, request: Request) -> Response:
        payload = s.WidgetWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("active", None)
        widget = services.create_widget(
            kind=data["kind"],
            name=data.get("name", ""),
            options=data.get("options"),
            theme=data.get("theme"),
            allowed_origins=data.get("allowed_origins"),
        )
        return Response(self.get_serializer(widget).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.WidgetUpdateSerializer, responses=s.WidgetSerializer)
    def partial_update(self, request: Request, pk: str) -> Response:
        widget = self.get_object()
        payload = s.WidgetUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("kind", None)
        widget = services.update_widget(widget, **data)
        return Response(self.get_serializer(widget).data)

    def perform_destroy(self, instance: WidgetConfig) -> None:
        services.delete_widget(instance)

    @extend_schema(responses=s.WidgetKindSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def kinds(self, request: Request) -> Response:
        return Response(
            [
                {
                    "key": k.key,
                    "title": str(k.label),
                    "element": k.element,
                    "description": str(k.description),
                    "available": k.is_available(),
                }
                for k in widgets.kinds()
            ]
        )


# --- testimonials --------------------------------------------------------------------------------


@extend_schema(tags=["website"])
class TestimonialViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = Testimonial
    serializer_class = s.TestimonialSerializer
    http_method_names = ["get", "post", "patch", "delete"]
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "PATCH", "DELETE"), "sites.widget.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return selectors.testimonials(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_testimonial(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_testimonial(
            serializer.instance, **serializer.validated_data
        )

    def perform_destroy(self, instance: Testimonial) -> None:
        services.delete_testimonial(instance)


# --- public profiles -----------------------------------------------------------------------------


@extend_schema(tags=["website"])
class PublicProfileViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Tutors' public profiles and moderation (FR-24-5). ``?status=pending`` for the queue."""

    model = PublicProfile
    serializer_class = s.PublicProfileSerializer
    lookup_value_regex = UUID
    permission_classes = perms(dict.fromkeys(("GET", "POST", "PATCH"), "sites.profile.moderate"))

    def get_tenant_queryset(self) -> Any:
        qs = selectors.public_profiles(self.request.user)
        wanted = self.request.query_params.get("status")
        if wanted:
            qs = qs.filter(status=wanted)
        return qs

    @extend_schema(
        parameters=[OpenApiParameter("status", OpenApiTypes.STR)],
        responses=s.PublicProfileSerializer(many=True),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.PublicProfileCreateSerializer, responses={201: s.PublicProfileSerializer}
    )
    def create(self, request: Request) -> Response:
        from tutortrack.people.models import TutorProfile

        payload = s.PublicProfileCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = get_object_or_404(TutorProfile.objects.all(), pk=payload.validated_data["tutor"])
        profile = services.ensure_profile(tutor)
        return Response(s.PublicProfileSerializer(profile).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.PublicProfileWriteSerializer, responses=s.PublicProfileSerializer)
    def partial_update(self, request: Request, pk: str) -> Response:
        """Staff edits publish at once."""
        payload = s.PublicProfileWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        profile = services.save_profile(
            self.get_object(), data=dict(payload.validated_data), user=request.user, moderator=True
        )
        return Response(s.PublicProfileSerializer(profile).data)

    @extend_schema(request=None, responses=s.PublicProfileSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: str) -> Response:
        profile = services.approve_profile(self.get_object(), request.user)
        return Response(s.PublicProfileSerializer(profile).data)

    @extend_schema(request=s.ProfileRejectSerializer, responses=s.PublicProfileSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: str) -> Response:
        payload = s.ProfileRejectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        profile = services.reject_profile(
            self.get_object(), request.user, payload.validated_data["reason"]
        )
        return Response(s.PublicProfileSerializer(profile).data)

    @extend_schema(request=None, responses=s.PublicProfileSerializer)
    @action(detail=True, methods=["post"])
    def hide(self, request: Request, pk: str) -> Response:
        profile = services.hide_profile(self.get_object())
        return Response(s.PublicProfileSerializer(profile).data)


@extend_schema(tags=["website"])
class MyPublicProfileView(APIView):
    """The signed-in tutor's own public profile (portal)."""

    permission_classes = AUTH

    def _profile(self, request: Request) -> PublicProfile:
        if not has_perm(request.user, "sites.profile.edit"):
            raise PermissionDenied()
        tutor = selectors.tutor_for_user(request.user)
        if tutor is None:
            raise PermissionDenied("There's no tutor profile for this login.")
        return services.ensure_profile(tutor)

    @extend_schema(responses=s.PublicProfileSerializer)
    def get(self, request: Request) -> Response:
        with transaction.atomic():
            profile = self._profile(request)
        return Response(s.PublicProfileSerializer(profile).data)

    @extend_schema(request=s.PublicProfileWriteSerializer, responses=s.PublicProfileSerializer)
    def put(self, request: Request) -> Response:
        payload = s.PublicProfileWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("slug", None)
        with transaction.atomic():
            profile = services.save_profile(
                self._profile(request),
                data=data,
                user=request.user,
                moderator=has_perm(request.user, "sites.profile.moderate"),
            )
        return Response(s.PublicProfileSerializer(profile).data)


# --- website -------------------------------------------------------------------------------------


@extend_schema(tags=["website"])
class SiteViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The hosted website (one per organisation). ``published`` needs ``sites.site.publish``."""

    model = Site
    serializer_class = s.SiteSerializer
    pagination_class = None
    lookup_value_regex = UUID
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "PATCH"), "sites.site.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return selectors.sites(self.request.user)

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "organisation": _org(self.request)}

    @extend_schema(request=s.SiteSerializer, responses={201: s.SiteSerializer})
    def create(self, request: Request) -> Response:
        payload = s.SiteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("published", None)
        if "og_image" in data:
            data["og_image"] = getattr(data["og_image"], "pk", data["og_image"])
        site = services.create_site(**data)
        return Response(self.get_serializer(site).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.SiteSerializer, responses=s.SiteSerializer)
    def partial_update(self, request: Request, pk: str) -> Response:
        site = self.get_object()
        payload = s.SiteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if "published" in data and not has_perm(request.user, "sites.site.publish"):
            raise PermissionDenied()
        if "og_image" in data:
            data["og_image"] = getattr(data["og_image"], "pk", data["og_image"])
        site = services.update_site(site, **data)
        return Response(self.get_serializer(site).data)


@extend_schema(tags=["website"])
class SiteThemesView(APIView):
    permission_classes = perms({"GET": "sites.view"})

    @extend_schema(responses=s.ThemeSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(themes.describe())


@extend_schema(tags=["website"])
class SiteBlocksView(APIView):
    permission_classes = perms({"GET": "sites.view"})

    @extend_schema(responses=s.BlockTypeSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(blocks.describe())


class PagePagination(CursorPagination):
    ordering = ("position", "id")  # type: ignore[assignment]


@extend_schema(tags=["website"])
class SitePageViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = SitePage
    serializer_class = s.SitePageSerializer
    pagination_class = PagePagination
    lookup_value_regex = UUID
    http_method_names = ["get", "post", "patch", "delete"]
    permission_classes = perms(
        {**VIEW_MANAGE, **dict.fromkeys(("POST", "PATCH", "DELETE"), "sites.site.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return selectors.site_pages(self.request.user)

    def _site(self) -> Site:
        site = selectors.site()
        if site is None:
            raise NotFound("Create the website first.")
        return site

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        serializer.instance = services.create_page(
            self._site(), title=data.pop("title"), path=data.pop("path", ""), **data
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_page(serializer.instance, **serializer.validated_data)

    def perform_destroy(self, instance: SitePage) -> None:
        services.delete_page(instance)

    def _require_publish(self, request: Request) -> None:
        if not has_perm(request.user, "sites.site.publish"):
            raise PermissionDenied()

    @extend_schema(request=None, responses=s.SitePageSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request: Request, pk: str) -> Response:
        self._require_publish(request)
        page = self.get_object()
        services.publish_page(page, request.user)
        page.refresh_from_db()
        return Response(s.SitePageSerializer(page).data)

    @extend_schema(request=None, responses=s.SitePageSerializer)
    @action(detail=True, methods=["post"])
    def unpublish(self, request: Request, pk: str) -> Response:
        self._require_publish(request)
        page = services.unpublish_page(self.get_object())
        return Response(s.SitePageSerializer(page).data)

    @extend_schema(responses=s.PagePreviewSerializer)
    @action(detail=True, methods=["get"])
    def preview(self, request: Request, pk: str) -> Response:
        """The draft rendered as HTML for the editor's preview frame."""
        page = self.get_object()
        html = render.render(
            request=request._request,
            organisation=_org(request),
            site=page.site,
            title=page.title,
            seo_title=page.seo_title,
            meta_description=page.meta_description,
            blocks=page.blocks,
            path=page.path,
            preview=True,
        )
        return Response({"html": html})

    @extend_schema(responses=s.SitePageVersionSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def versions(self, request: Request, pk: str) -> Response:
        page = self.get_object()
        return Response(s.SitePageVersionSerializer(selectors.page_versions(page), many=True).data)

    @extend_schema(request=s.PageRestoreSerializer, responses=s.SitePageSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, pk: str) -> Response:
        payload = s.PageRestoreSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        page = services.restore_version(self.get_object(), payload.validated_data["version"])
        return Response(s.SitePageSerializer(page).data)


# --- public (anonymous) --------------------------------------------------------------------------


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_widget"


def public_branding(org: Any) -> dict[str, Any]:
    b = brand.resolve(org)

    def url(file_id: str | None) -> str:
        return brand.asset_url(org, file_id)

    return {
        "name": b.name,
        "logo_url": url(b.logo_id),
        "logo_dark_url": url(b.logo_dark_id),
        "favicon_url": url(b.favicon_id),
        "app_icon_url": url(b.app_icon_id),
        "app_name": b.app_name or b.name,
        "primary_colour": b.primary_colour,
        "on_primary": b.on_primary,
        "link_colour": b.link_colour,
        "secondary_colour": b.secondary_colour,
        "font": b.font,
        "font_family": brand.font_stack(b.font),
        "font_css_url": brand.font_css_url(b.font),
        "social_links": b.social_links,
        "show_powered_by": b.show_powered_by,
        "portal_url": f"{org.base_url}/portal/",
        "login_url": f"{org.base_url}/login",
    }


@extend_schema(tags=["public"])
class PublicBrandingView(PublicView):
    """The organisation's effective brand for portals, widgets and public pages."""

    @extend_schema(responses=s.PublicBrandingSerializer)
    def get(self, request: Request) -> Response:
        return Response(public_branding(_org(request)))


@extend_schema(tags=["public"])
class PublicManifestView(PublicView):
    """PWA manifest for the portal with the tenant's app name, icon and colour."""

    @extend_schema(responses=s.ManifestSerializer)
    def get(self, request: Request) -> Response:
        org = _org(request)
        b = public_branding(org)
        icons = []
        if b["app_icon_url"] or b["logo_url"]:
            src = b["app_icon_url"] or b["logo_url"]
            icons = [
                {"src": src, "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": src, "sizes": "512x512", "type": "image/png", "purpose": "any"},
            ]
        # The portal's own icons (E16-T08) keep it installable without a brand kit and give
        # Android a maskable icon.
        icons += [
            {"src": "/portal/icons/icon-192.png", "sizes": "192x192", "type": "image/png",
             "purpose": "any"},
            {"src": "/portal/icons/icon-512.png", "sizes": "512x512", "type": "image/png",
             "purpose": "any"},
            {"src": "/portal/icons/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ]  # fmt: skip
        description = _("Lessons, reports and messages from %(name)s") % {"name": b["name"]}
        return Response(
            {
                "id": "/portal/",
                "name": b["app_name"],
                "short_name": b["app_name"][:12],
                "description": description,
                "lang": "en-GB",
                "start_url": "/portal/",
                "scope": "/portal/",
                "display": "standalone",
                "theme_color": b["primary_colour"],
                "background_color": "#ffffff",
                "categories": ["education", "productivity"],
                "shortcuts": [{"name": _("Today"), "url": "/portal/tutor"}],
                "icons": icons,
            }
        )


class DirectoryPagination(CursorPagination):
    ordering = "slug"
    page_size = 24
    max_page_size = 48


@extend_schema(tags=["public"])
class PublicTutorsView(generics.ListAPIView):
    """Searchable public tutor profiles (FR-24-3): ``q``, ``subject``, ``level``,
    ``online`` (true: online; false: in person) and ``location`` (town)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_widget"
    pagination_class = DirectoryPagination
    serializer_class = s.PublicTutorSerializer

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return PublicProfile.all_tenants.none()
        _org(self.request)
        p = self.request.query_params
        online = {"true": True, "false": False}.get(p.get("online", "").lower())
        return selectors.directory(
            q=p.get("q", "")[:100],
            subject=p.get("subject", "")[:100],
            level=p.get("level", "")[:100],
            online=online,
            location=p.get("location", "")[:100],
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR),
            OpenApiParameter("subject", OpenApiTypes.STR),
            OpenApiParameter("level", OpenApiTypes.STR),
            OpenApiParameter("online", OpenApiTypes.BOOL),
            OpenApiParameter("location", OpenApiTypes.STR),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        page = self.paginate_queryset(self.get_queryset())
        rows = [selectors.public_tutor_card(p) for p in page or []]
        return self.get_paginated_response(rows)


@extend_schema(tags=["public"])
class PublicTutorView(PublicView):
    @extend_schema(responses=s.PublicTutorDetailSerializer)
    def get(self, request: Request, slug: str) -> Response:
        _org(request)
        profile = selectors.directory().filter(slug=slug).first()
        if profile is None:
            raise NotFound()
        return Response(selectors.public_tutor_detail(profile))


@extend_schema(tags=["public"])
class PublicServicesView(PublicView):
    """Services the organisation publishes (``?widget=`` applies that widget's choice)."""

    @extend_schema(
        parameters=[OpenApiParameter("widget", OpenApiTypes.STR)],
        responses=s.PublicServiceSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        _org(request)
        ids: list[Any] = []
        prices = False
        key = request.query_params.get("widget", "")
        if key:
            widget = WidgetConfig.objects.filter(key=key, active=True, kind="services").first()
            if widget is None:
                raise NotFound()
            ids = widget.options.get("services") or []
            prices = bool(widget.options.get("show_prices"))
        return Response(selectors.public_services(ids, prices=prices))


@extend_schema(tags=["public"])
class PublicReviewsView(PublicView):
    @extend_schema(
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT),
            OpenApiParameter("min_rating", OpenApiTypes.INT),
        ],
        responses=s.PublicReviewSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        _org(request)
        try:
            limit = max(1, min(24, int(request.query_params.get("limit", 6))))
            min_rating = int(request.query_params.get("min_rating", 0)) or None
        except ValueError:
            limit, min_rating = 6, None
        return Response(selectors.public_testimonials(limit, min_rating))


@extend_schema(tags=["public"])
class PublicWidgetView(PublicView):
    """A widget's settings, theme and the brand (``<tt-* widget="key">``)."""

    @extend_schema(responses=s.PublicWidgetSerializer)
    def get(self, request: Request, key: str) -> Response:
        org = _org(request)
        widget = WidgetConfig.objects.filter(key=key, active=True).first()
        kind = widgets.get(widget.kind) if widget else None
        if widget is None or kind is None or not kind.is_available():
            raise NotFound()
        return Response(
            {
                "key": widget.key,
                "kind": widget.kind,
                "element": kind.element,
                "options": widget.options,
                "theme": widget.theme,
                "branding": public_branding(org),
            }
        )


@extend_schema(tags=["public"])
class PublicAssetView(PublicView):
    """Redirects to a short-lived URL for a published image (logo, tutor photo, page
    image); anything else is 404."""

    @extend_schema(responses={302: None})
    def get(self, request: Request, file_id: Any) -> Any:
        from tutortrack.core.models import StoredFile
        from tutortrack.core.storage.client import bucket, presign_client

        org = _org(request)
        if str(file_id) not in selectors.public_asset_ids(org):
            raise NotFound()
        stored = StoredFile.objects.filter(pk=file_id).first()
        if stored is None or not stored.is_downloadable:
            raise NotFound()
        url = presign_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket(),
                "Key": stored.storage_key,
                "ResponseContentType": stored.content_type,
                "ResponseCacheControl": "public, max-age=3600",
            },
            ExpiresIn=3600,
        )
        response = HttpResponseRedirect(url)
        response["Cache-Control"] = "public, max-age=1800"
        return response
