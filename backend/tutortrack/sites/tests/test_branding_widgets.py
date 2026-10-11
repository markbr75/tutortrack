"""E24-T01/T03/T04/T05/T08: brand kit and runtime theming, widgets (config, embed, CORS, rate
limits), the public directory/services/reviews APIs and the "powered by" entitlement."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.template.loader import render_to_string
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.render import to_html
from tutortrack.core import branding, entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent, StoredFile
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form
from tutortrack.people.models import TutorQualification, TutorSubject
from tutortrack.sites import brand, services
from tutortrack.sites.models import BrandKit, WidgetConfig
from tutortrack.tenancy.tests.factories import BranchFactory

from .factories import (
    BrandKitFactory,
    PublicProfileFactory,
    QuoteFactory,
    WidgetFactory,
)

pytestmark = pytest.mark.django_db


def anonymous(org: Any, **headers: str) -> APIClient:
    return APIClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}", **headers)


class Entitlements:
    """Resolver that grants everything except ``denied``."""

    def __init__(self, *denied: str):
        self.denied = set(denied)

    def has(self, key: str, organisation_id: Any) -> bool:
        return key not in self.denied

    def limit(self, key: str, organisation_id: Any) -> int | None:
        return None

    def required_plan(self, key: str, needed: int | None = None) -> str | None:
        return "agency"


@pytest.fixture
def deny(monkeypatch):
    def apply(*keys: str) -> None:
        monkeypatch.setattr(entitlements, "_resolver", Entitlements(*keys))

    return apply


def image(org: Any, name: str = "logo.png") -> StoredFile:
    with tenant_context(org):
        return StoredFile.objects.create(
            filename=name,
            content_type="image/png",
            size_bytes=10,
            storage_key=f"{org.pk}/{uuid.uuid4()}",
            status=StoredFile.Status.UPLOADED,
            scan_status=StoredFile.ScanStatus.CLEAN,
        )


# --- FR-24-1 brand kit ---------------------------------------------------------------------------


def test_contrast_helpers_follow_wcag():
    assert brand.contrast("#000000", "#ffffff") == 21.0
    assert brand.on_colour("#fde047") == "#111827"  # yellow: dark text
    assert brand.on_colour("#1d4ed8") == "#ffffff"
    light = brand.readable_on_white("#7dd3fc")
    assert brand.contrast(light, "#ffffff") >= 4.5
    report = brand.contrast_report("#7dd3fc")
    assert report["passes_aa"] is False
    assert report["warnings"]
    assert brand.contrast_report("#1d4ed8")["passes_aa"] is True


def test_admin_saves_the_brand_kit_with_a_contrast_report(org, api):
    logo = image(org)
    response = api.post(
        "/api/v1/brand-kits",
        {
            "primary_colour": "#7DD3FC",
            "font": "Inter",
            "logo": str(logo.pk),
            "email_footer": "Bright Minds Ltd",
            "social_links": {"instagram": "https://instagram.com/bm"},
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["primary_colour"] == "#7dd3fc"
    assert body["contrast"]["passes_aa"] is False
    assert body["contrast"]["on_primary"] == "#111827"
    assert brand.contrast(body["contrast"]["link_colour"], "#ffffff") >= 4.5
    assert OutboxEvent.objects.filter(event_type="brand_kit.updated").exists()
    # Saving again updates the same organisation kit.
    again = api.post("/api/v1/brand-kits", {"primary_colour": "#1d4ed8"}, format="json")
    assert again.json()["id"] == body["id"]
    with tenant_context(org):
        assert BrandKit.objects.count() == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"primary_colour": "blue"},
        {"font": "Comic Sans"},
        {"social_links": {"myspace": "https://myspace.com/x"}},
        {"social_links": {"x": "javascript:alert(1)"}},
    ],
)
def test_invalid_brand_values_are_rejected(api, payload):
    assert api.post("/api/v1/brand-kits", payload, format="json").status_code in (400, 422)


def test_branch_kit_overrides_the_organisation_kit(org, api):
    branch = BranchFactory(organisation=org, code="LDS")
    api.post("/api/v1/brand-kits", {"primary_colour": "#1d4ed8", "font": "Lato"}, format="json")
    response = api.post(
        "/api/v1/brand-kits",
        {"branch": str(branch.pk), "primary_colour": "#b91c1c"},
        format="json",
    )
    assert response.status_code == 201
    effective = brand.resolve(org, branch.pk)
    assert effective.primary_colour == "#b91c1c"
    assert effective.font == "Lato"  # inherited
    assert brand.resolve(org).primary_colour == "#1d4ed8"


def test_organisation_logo_and_colour_are_the_fallback(org):
    org.primary_colour = "#047857"
    org.save()
    effective = brand.resolve(org)
    assert effective.primary_colour == "#047857"
    assert effective.show_powered_by is True


def test_hiding_powered_by_needs_white_label(org, api, deny):
    deny("white_label")
    response = api.post("/api/v1/brand-kits", {"hide_powered_by": True}, format="json")
    assert response.status_code == 403
    assert response.json()["type"].endswith("upgrade-required")


def test_white_label_removes_powered_by_everywhere(org, api):
    api.post("/api/v1/brand-kits", {"hide_powered_by": True}, format="json")
    assert anonymous(org).get("/api/v1/public/branding").json()["show_powered_by"] is False
    assert branding.for_email(org.pk)["show_powered_by"] is False
    assert "Powered by" not in to_html("Hi", organisation="BM", brand=branding.for_email(org.pk))


def test_powered_by_returns_if_the_plan_loses_white_label(org, deny):
    BrandKitFactory(organisation=org, hide_powered_by=True)
    deny("white_label")
    assert brand.resolve(org).show_powered_by is True


def test_emails_carry_the_brand(org):
    logo = image(org)
    BrandKitFactory(
        organisation=org,
        primary_colour="#1d4ed8",
        logo=logo,
        email_header="Learning that sticks",
        email_footer="Bright Minds Ltd, Leeds",
    )
    html = to_html(
        "Hello\n\nSee you soon", organisation="Bright Minds", brand=branding.for_email(org.pk)
    )
    assert f"/api/v1/public/assets/{logo.pk}" in html
    assert "#1d4ed8" in html
    assert "Learning that sticks" in html
    assert "Bright Minds Ltd, Leeds" in html
    assert "Powered by TutorTrack" in html


def test_documents_use_the_brand_colour_and_footer(org):
    BrandKitFactory(organisation=org, primary_colour="#b91c1c", document_footer="Company 123")
    doc = branding.for_documents(org.pk)
    css = render_to_string("billing/_style.html", {"brand": doc})
    assert "#b91c1c" in css
    assert "Company 123" in render_to_string("billing/_brand_footer.html", {"brand": doc})


def test_public_branding_is_anonymous_and_has_no_contact_details(org):
    org.contact_email = "owner@brightminds.test"
    org.save()
    BrandKitFactory(organisation=org, font="Poppins")
    body = anonymous(org).get("/api/v1/public/branding").json()
    assert body["name"] == org.name
    assert body["font_css_url"].startswith("https://fonts.googleapis.com/")
    assert body["portal_url"].endswith("/portal/")
    assert "owner@brightminds.test" not in str(body)


def test_pwa_manifest_uses_app_name_and_icon(org):
    icon = image(org, "icon.png")
    BrandKitFactory(organisation=org, app_name="Bright Minds", app_icon=icon)
    manifest = anonymous(org).get("/api/v1/public/manifest").json()
    assert manifest["name"] == "Bright Minds"
    assert manifest["start_url"] == "/portal/"
    assert str(icon.pk) in manifest["icons"][0]["src"]


def test_public_assets_only_serve_published_images(org, s3):
    logo = image(org)
    private = image(org, "contract.png")
    BrandKitFactory(organisation=org, logo=logo)
    ok = anonymous(org).get(f"/api/v1/public/assets/{logo.pk}")
    assert ok.status_code == 302
    assert anonymous(org).get(f"/api/v1/public/assets/{private.pk}").status_code == 404


# --- FR-24-3 widgets -----------------------------------------------------------------------------


def test_widget_kinds_say_what_is_available(api, deny):
    deny("recruitment")
    kinds = {k["key"]: k for k in api.get("/api/v1/widgets/kinds").json()}
    assert kinds["tutor_directory"]["element"] == "tt-tutor-directory"
    assert kinds["job_openings"]["available"] is False
    assert {"enquiry_form", "services", "reviews", "login"} <= set(kinds)


def test_create_widget_returns_embed_code_and_shortcode(org, api):
    response = api.post(
        "/api/v1/widgets",
        {
            "kind": "tutor_directory",
            "name": "Directory",
            "options": {"subjects": ["Maths"], "page_size": 12},
            "theme": {"--tt-radius": "12px"},
            "allowed_origins": ["https://www.brightminds.co.uk/"],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    w = response.json()
    assert w["allowed_origins"] == ["https://www.brightminds.co.uk"]
    assert f'data-org="{org.slug}"' in w["embed_code"]
    assert f'<tt-tutor-directory widget="{w["key"]}">' in w["embed_code"]
    assert w["wordpress_shortcode"] == f'[tutortrack widget="{w["key"]}" type="tutor_directory"]'


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "nope"},
        {"kind": "enquiry_form", "options": {"form": "missing"}},
        {"kind": "reviews", "theme": {"--tt-radius": "1px;}</style>"}},
        {"kind": "reviews", "theme": {"color": "red"}},
        {"kind": "reviews", "allowed_origins": ["ftp://example.com"]},
        {"kind": "reviews", "allowed_origins": ["https://example.com/path"]},
    ],
)
def test_widget_settings_are_validated(api, payload):
    assert api.post("/api/v1/widgets", payload, format="json").status_code in (400, 422)


def test_enquiry_widget_needs_a_published_form(org, api):
    with tenant_context(org):
        Form.objects.create(name="Enquire", slug="enquire", schema={}, published=True)
    response = api.post(
        "/api/v1/widgets", {"kind": "enquiry_form", "options": {"form": "enquire"}}, format="json"
    )
    assert response.status_code == 201
    assert 'form="enquire"' in response.json()["embed_code"]


def test_premium_widget_needs_the_plan(api, deny):
    deny("recruitment")
    assert api.post("/api/v1/widgets", {"kind": "job_openings"}, format="json").status_code == 403


def test_public_widget_config(org):
    widget = WidgetFactory(organisation=org, kind="reviews", options={"limit": 3}, theme={})
    body = anonymous(org).get(f"/api/v1/public/widgets/{widget.key}").json()
    assert body["element"] == "tt-reviews"
    assert body["options"] == {"limit": 3}
    assert body["branding"]["name"] == org.name
    with tenant_context(org):
        WidgetConfig.objects.filter(pk=widget.pk).update(active=False)
    assert anonymous(org).get(f"/api/v1/public/widgets/{widget.key}").status_code == 404


def test_widgets_do_not_leak_across_organisations(org, other_org):
    widget = WidgetFactory(organisation=other_org)
    assert anonymous(org).get(f"/api/v1/public/widgets/{widget.key}").status_code == 404


def test_cors_allows_only_the_organisations_sites(org, other_org):
    WidgetFactory(organisation=org, allowed_origins=["https://www.brightminds.co.uk"])
    WidgetFactory(organisation=other_org, allowed_origins=["https://evil.example"])
    cache.clear()
    ok = anonymous(org, HTTP_ORIGIN="https://www.brightminds.co.uk").get("/api/v1/public/branding")
    assert ok["Access-Control-Allow-Origin"] == "https://www.brightminds.co.uk"
    blocked = anonymous(org, HTTP_ORIGIN="https://evil.example").get("/api/v1/public/branding")
    assert "Access-Control-Allow-Origin" not in blocked
    preflight = anonymous(
        org,
        HTTP_ORIGIN="https://www.brightminds.co.uk",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
    ).options("/api/v1/public/tutors")
    assert preflight.status_code == 200
    assert preflight["Access-Control-Allow-Origin"] == "https://www.brightminds.co.uk"
    # Private API endpoints are never opened to widget origins.
    private = anonymous(org, HTTP_ORIGIN="https://www.brightminds.co.uk").get("/api/v1/clients")
    assert "Access-Control-Allow-Origin" not in private


def test_hosted_site_origin_is_always_allowed(org):
    cache.clear()
    site_base = settings.CUSTOM_DOMAINS["SITE_BASE_DOMAIN"]
    origin = f"https://{org.slug}.{site_base}"
    response = anonymous(org, HTTP_ORIGIN=origin).get("/api/v1/public/reviews")
    assert response["Access-Control-Allow-Origin"] == origin


def test_public_endpoints_are_rate_limited(org, monkeypatch):
    monkeypatch.setattr(
        ScopedRateThrottle,
        "THROTTLE_RATES",
        {**ScopedRateThrottle.THROTTLE_RATES, "public_widget": "2/minute"},
    )
    cache.clear()
    client = anonymous(org)
    codes = [client.get("/api/v1/public/reviews").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_unknown_organisation_is_404():
    client = APIClient(HTTP_HOST=f"nobody.{settings.TENANT_BASE_DOMAIN}")
    assert client.get("/api/v1/public/branding").status_code == 404


# --- FR-24-3 directory, services, reviews --------------------------------------------------------


def listed(org, **kw):
    profile = PublicProfileFactory(organisation=org, **kw)
    with tenant_context(org):
        TutorSubject.objects.create(
            tutor=profile.tutor, subject="Maths", level="GCSE", approved=True
        )
        TutorSubject.objects.create(tutor=profile.tutor, subject="Secret", approved=False)
    return profile


def test_directory_lists_only_published_active_tutors(org):
    shown = listed(org)
    listed(org, listed=False)
    listed(org, tutor__status="inactive")
    listed(org, tutor__public_profile=False)
    body = anonymous(org).get("/api/v1/public/tutors").json()
    assert [r["slug"] for r in body["results"]] == [shown.slug]
    row = body["results"][0]
    assert row["subjects"] == [{"subject": "Maths", "level": "GCSE"}]  # approved only
    assert shown.tutor.email not in str(body)
    assert shown.tutor.last_name not in str(body)


def test_directory_filters(org):
    maths = listed(org)
    english = PublicProfileFactory(organisation=org, tutor__delivers_online=False)
    with tenant_context(org):
        TutorSubject.objects.create(tutor=english.tutor, subject="English", approved=True)
    client = anonymous(org)
    by_subject = client.get("/api/v1/public/tutors", {"subject": "english"}).json()["results"]
    assert [r["slug"] for r in by_subject] == [english.slug]
    online = client.get("/api/v1/public/tutors", {"online": "true"}).json()["results"]
    assert maths.slug in [r["slug"] for r in online]
    assert english.slug not in [r["slug"] for r in online]
    assert (
        client.get("/api/v1/public/tutors", {"q": "math"}).json()["results"][0]["slug"]
        == maths.slug
    )


def test_tutor_detail_shows_only_the_sections_the_tutor_chose(org):
    profile = listed(org)
    with tenant_context(org):
        TutorQualification.objects.create(tutor=profile.tutor, title="BSc Maths", year=2015)
    client = anonymous(org)
    body = client.get(f"/api/v1/public/tutors/{profile.slug}").json()
    assert body["bio"] == "Hello"
    assert body["qualifications"] == []
    profile.published = {**profile.published, "show": ["qualifications"]}
    with tenant_context(org):
        profile.save()
    body = client.get(f"/api/v1/public/tutors/{profile.slug}").json()
    assert body["qualifications"][0]["title"] == "BSc Maths"
    assert client.get("/api/v1/public/tutors/nobody").status_code == 404


def test_public_services_and_prices_follow_the_widget(org):
    shown = ServiceFactory(
        organisation=org, public_description="1:1 maths", charge_rate_amount=Decimal("45")
    )
    ServiceFactory(organisation=org)  # no public description: not published
    rows = anonymous(org).get("/api/v1/public/services").json()
    assert [r["name"] for r in rows] == [shown.name]
    assert rows[0]["price"] == ""
    widget = WidgetFactory(
        organisation=org,
        kind="services",
        options={"services": [str(shown.pk)], "show_prices": True},
    )
    rows = anonymous(org).get("/api/v1/public/services", {"widget": widget.key}).json()
    assert rows[0]["price"] == "£45.00"
    assert rows[0]["price_amount"] == "45.00"


def test_public_reviews(org):
    QuoteFactory(organisation=org, quote="Great", rating=5)
    QuoteFactory(organisation=org, quote="Fine", rating=3)
    QuoteFactory(organisation=org, quote="Hidden", published=False)
    rows = anonymous(org).get("/api/v1/public/reviews", {"min_rating": 4}).json()
    assert [r["quote"] for r in rows] == ["Great"]
    assert rows[0]["stars"] == "★★★★★"


def test_testimonials_crud_filters_offensive_language(api):
    created = api.post(
        "/api/v1/testimonials", {"quote": "Lovely", "author": "Jo", "rating": 4}, format="json"
    )
    assert created.status_code == 201
    pk = created.json()["id"]
    assert (
        api.patch(f"/api/v1/testimonials/{pk}", {"published": False}, format="json").json()[
            "published"
        ]
        is False
    )
    bad = api.post("/api/v1/testimonials", {"quote": "shit", "author": "X"}, format="json")
    assert bad.status_code == 422
    assert api.delete(f"/api/v1/testimonials/{pk}").status_code == 204


def test_coordinator_can_view_but_not_change_branding(org):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    client = client_for(org, coordinator)
    assert client.get("/api/v1/brand-kits").status_code == 200
    assert client.post("/api/v1/brand-kits", {"font": "Inter"}, format="json").status_code == 403


def test_services_layer_events(org):
    with tenant_context(org):
        widget = services.create_widget(kind="login", name="Login", options={"portal": "tutor"})
        assert widget.options == {"portal": "tutor"}
        assert OutboxEvent.objects.filter(event_type="widget.saved").count() == 1


# --- tenant isolation ----------------------------------------------------------------------------


class TestBrandKitIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/brand-kits"

    def make_object(self, organisation):
        return BrandKitFactory(organisation=organisation)


class TestWidgetIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/widgets"

    def make_object(self, organisation):
        return WidgetFactory(organisation=organisation)


class TestTestimonialIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/testimonials"

    def make_object(self, organisation):
        return QuoteFactory(organisation=organisation)


class TestPublicProfileIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/public-profiles"

    def make_object(self, organisation):
        return PublicProfileFactory(organisation=organisation)
