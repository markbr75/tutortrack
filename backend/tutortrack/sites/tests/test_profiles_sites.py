"""E24-T04 (public profiles and moderation, FR-24-5) and E24-T07 (website builder: themes,
blocks, draft/preview/publish with versions, SEO, sitemap, hosted pages)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form
from tutortrack.people.models import TutorProfile, TutorSubject
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.sites import moderation
from tutortrack.sites.models import PublicProfile, Site, SitePage
from tutortrack.tenancy.models import OrganisationDomain
from tutortrack.tenancy.settings_service import update_settings

from .factories import PublicProfileFactory, SiteFactory, SitePageFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tutor(org) -> tuple[APIClient, TutorProfile]:
    membership = MembershipFactory(organisation=org, role="tutor")
    profile = TutorProfileFactory(
        organisation=org,
        membership=membership,
        status="active",
        first_name="Ada",
        last_name="Lovelace",
        headline="Maths tutor",
    )
    with tenant_context(org):
        TutorSubject.objects.create(tutor=profile, subject="Maths", approved=True)
    return client_for(org, membership.user), profile


def site_client(org: Any) -> APIClient:
    return APIClient(HTTP_HOST=f"{org.slug}.{settings.CUSTOM_DOMAINS['SITE_BASE_DOMAIN']}")


# --- FR-24-5 moderation filter -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Email me at ada@example.com",
        "ada (at) example (dot) com",
        "Call 07700 900123",
        "See www.adamaths.co.uk",
        "Find me on WhatsApp",
        "Follow @adamaths",
        "This is shit",
    ],
)
def test_filter_blocks_contact_details_and_profanity(text):
    assert moderation.issues(text)


def test_filter_allows_ordinary_text():
    assert moderation.issues("I have taught GCSE maths since 2015 and love algebra.") == []
    assert moderation.issues("Email me at a@b.com", contact_filter=False) == []


# --- FR-24-5 public profiles ---------------------------------------------------------------------


def test_tutor_edits_wait_for_approval(org, api, tutor):
    client, profile = tutor
    mine = client.get("/api/v1/public-profiles/mine").json()
    assert mine["draft"]["display_name"] == "Ada L."  # first name + initial by default
    assert mine["status"] == "draft"
    response = client.put(
        "/api/v1/public-profiles/mine",
        {
            "headline": "GCSE and A-level maths",
            "bio": "Ten years of teaching.",
            "show": ["qualifications"],
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "pending"
    assert OutboxEvent.objects.filter(event_type="public_profile.submitted").exists()
    # Nothing public yet.
    assert (
        APIClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}")
        .get("/api/v1/public/tutors")
        .json()["results"]
        == []
    )

    queue = api.get("/api/v1/public-profiles", {"status": "pending"}).json()["results"]
    assert [p["id"] for p in queue] == [mine["id"]]
    approved = api.post(f"/api/v1/public-profiles/{mine['id']}/approve")
    assert approved.json()["status"] == "approved"
    assert approved.json()["published"]["headline"] == "GCSE and A-level maths"
    with tenant_context(org):
        assert TutorProfile.objects.get(pk=profile.pk).public_profile is True
    public = APIClient(HTTP_HOST=f"{org.slug}.{settings.TENANT_BASE_DOMAIN}").get(
        "/api/v1/public/tutors"
    )
    assert public.json()["results"][0]["headline"] == "GCSE and A-level maths"


def test_later_edits_keep_the_approved_version_live(org, api, tutor):
    client, _profile = tutor
    client.put("/api/v1/public-profiles/mine", {"bio": "First"}, format="json")
    pid = client.get("/api/v1/public-profiles/mine").json()["id"]
    api.post(f"/api/v1/public-profiles/{pid}/approve")
    client.put("/api/v1/public-profiles/mine", {"bio": "Second"}, format="json")
    with tenant_context(org):
        profile = PublicProfile.objects.get(pk=pid)
    assert profile.status == "pending"
    assert profile.published["bio"] == "First"
    assert profile.draft["bio"] == "Second"


def test_contact_details_are_rejected_with_field_errors(tutor):
    client, _profile = tutor
    response = client.put(
        "/api/v1/public-profiles/mine", {"bio": "Text me on 07700 900123"}, format="json"
    )
    assert response.status_code == 422
    assert "bio" in response.json()["errors"]


def test_filter_can_be_switched_off_except_profanity(org, tutor):
    client, _profile = tutor
    with tenant_context(org):
        update_settings("sites", {"sites.profile_contact_filter": False})
    ok = client.put(
        "/api/v1/public-profiles/mine", {"bio": "Find me at www.ada.com"}, format="json"
    )
    assert ok.status_code == 200
    bad = client.put("/api/v1/public-profiles/mine", {"bio": "bollocks"}, format="json")
    assert bad.status_code == 422


def test_without_approval_setting_edits_publish_immediately(org, tutor):
    client, _profile = tutor
    with tenant_context(org):
        update_settings("sites", {"sites.profile_approval_required": False})
    response = client.put("/api/v1/public-profiles/mine", {"bio": "Hi"}, format="json")
    assert response.json()["status"] == "approved"


def test_reject_needs_a_reason_and_tutor_can_opt_out(org, api, tutor):
    client, _profile = tutor
    client.put("/api/v1/public-profiles/mine", {"bio": "Hi"}, format="json")
    pid = client.get("/api/v1/public-profiles/mine").json()["id"]
    assert (
        api.post(f"/api/v1/public-profiles/{pid}/reject", {"reason": ""}, format="json").status_code
        == 400
    )
    rejected = api.post(
        f"/api/v1/public-profiles/{pid}/reject", {"reason": "Add your subjects"}, format="json"
    )
    assert rejected.json()["status"] == "rejected"
    assert OutboxEvent.objects.filter(event_type="public_profile.rejected").exists()
    api.post(f"/api/v1/public-profiles/{pid}/approve")
    hidden = client.put("/api/v1/public-profiles/mine", {"listed": False}, format="json")
    assert hidden.json()["status"] == "hidden"
    assert hidden.json()["listed"] is False


def test_staff_create_and_edit_publish_at_once(org, api):
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Grace", last_name="Hopper"
    )
    created = api.post("/api/v1/public-profiles", {"tutor": str(tutor.pk)}, format="json")
    assert created.status_code == 201
    pid = created.json()["id"]
    edited = api.patch(
        f"/api/v1/public-profiles/{pid}", {"headline": "Computing", "slug": "grace"}, format="json"
    )
    assert edited.json()["status"] == "approved"
    assert edited.json()["slug"] == "grace"


def test_clients_cannot_use_the_tutor_profile_endpoint(org):
    client_user = MembershipFactory(organisation=org, role="client").user
    response = client_for(org, client_user).get("/api/v1/public-profiles/mine")
    assert response.status_code == 403


def test_tutors_cannot_moderate(org, tutor):
    client, _profile = tutor
    other = PublicProfileFactory(organisation=org, status="pending")
    assert client.post(f"/api/v1/public-profiles/{other.pk}/approve").status_code == 403


# --- FR-24-4 website builder ---------------------------------------------------------------------


def test_create_site_with_starter_pages(org, api):
    with tenant_context(org):
        Form.objects.create(name="Enquire", slug="enquire", schema={}, published=True)
    response = api.post("/api/v1/sites", {"theme": "modern"}, format="json")
    assert response.status_code == 201, response.content
    assert (
        response.json()["url"]
        == f"https://{org.slug}.{settings.CUSTOM_DOMAINS['SITE_BASE_DOMAIN']}"
    )
    pages = api.get("/api/v1/sites/pages").json()["results"]
    assert [p["path"] for p in pages] == ["", "about", "tutors", "contact"]
    contact = next(p for p in pages if p["path"] == "contact")
    assert any(b["type"] == "form" for b in contact["blocks"])
    assert api.post("/api/v1/sites", {}, format="json").status_code == 409


def test_themes_and_blocks_are_described(api):
    themes = api.get("/api/v1/sites/themes").json()
    assert len(themes) == 5
    blocks = {b["key"]: b for b in api.get("/api/v1/sites/blocks").json()}
    assert {"hero", "text", "image", "tutor_grid", "subject_list", "pricing_table",
            "testimonials", "faq", "form", "cta", "map"} <= set(blocks)  # fmt: skip
    hero_fields = {f["name"]: f["kind"] for f in blocks["hero"]["fields"]}
    assert hero_fields["cta_href"] == "href"
    faq_fields = {f["name"]: f["kind"] for f in blocks["faq"]["fields"]}
    assert faq_fields["items"] == "items"
    assert hero_fields["image"] == "image"


@pytest.mark.parametrize(
    "site_changes",
    [{"theme": "neon"}, {"analytics_id": "UA-123"}, {"tag_manager_id": "<script>"}],
)
def test_site_settings_are_validated(org, api, site_changes):
    site = SiteFactory(organisation=org)
    response = api.patch(f"/api/v1/sites/{site.pk}", site_changes, format="json")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "blocks",
    [
        [{"type": "marquee", "props": {}}],
        [
            {
                "type": "cta",
                "props": {"heading": "Hi", "cta_label": "Go", "cta_href": "javascript:alert(1)"},
            }
        ],
        [{"type": "hero", "props": {}}],
        "not a list",
    ],
)
def test_blocks_are_validated(org, api, blocks):
    page = SitePageFactory(organisation=org)
    response = api.patch(f"/api/v1/sites/pages/{page.pk}", {"blocks": blocks}, format="json")
    assert response.status_code in (400, 422)


def test_publish_snapshots_a_version_and_serves_the_page(org, api):
    site = SiteFactory(organisation=org, published=True, analytics_id="G-ABC1234")
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    blocks = [
        {
            "id": "h",
            "type": "hero",
            "props": {"heading": "Learn with us", "cta_label": "Contact", "cta_href": "/contact"},
        },
        {
            "id": "t",
            "type": "text",
            "props": {"heading": "Why us", "body": "<b>Great</b> tutors\n\nSecond"},
        },
        {"id": "f", "type": "faq", "props": {"items": [{"question": "Online?", "answer": "Yes"}]}},
    ]
    assert (
        api.patch(f"/api/v1/sites/pages/{page.pk}", {"blocks": blocks}, format="json").status_code
        == 200
    )
    # Drafts are not live.
    assert site_client(org).get("/").status_code == 404
    published = api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    assert published.json()["status"] == "published"
    assert published.json()["live_version_number"] == 1
    assert OutboxEvent.objects.filter(event_type="site_page.published").exists()

    response = site_client(org).get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1" in html
    assert "Learn with us" in html
    assert "&lt;b&gt;Great&lt;/b&gt;" in html  # escaped, never raw HTML
    assert '<html lang="en-GB">' in html
    assert "Skip to content" in html
    assert "Powered by" in html
    ld = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    assert json.loads(ld.group(1))["@type"] == "EducationalOrganization"
    assert "max-age" in response["Cache-Control"]
    assert response["ETag"]
    assert "googletagmanager" in response["Content-Security-Policy"]
    again = site_client(org).get("/", HTTP_IF_NONE_MATCH=response["ETag"])
    assert again.status_code == 304

    # A later draft change stays unpublished until published.
    api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "hero", "props": {"heading": "New heading"}}]},
        format="json",
    )
    assert "Learn with us" in site_client(org).get("/").content.decode()
    assert api.get(f"/api/v1/sites/pages/{page.pk}").json()["status"] == "changed"


def test_preview_versions_and_restore(org, api):
    site = SiteFactory(organisation=org)
    page = SitePageFactory(organisation=org, site=site, path="about", title="About")
    api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "text", "props": {"body": "One"}}]},
        format="json",
    )
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "text", "props": {"body": "Two"}}]},
        format="json",
    )
    preview = api.get(f"/api/v1/sites/pages/{page.pk}/preview").json()["html"]
    assert "Two" in preview
    assert 'name="robots" content="noindex"' in preview
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    versions = api.get(f"/api/v1/sites/pages/{page.pk}/versions").json()
    assert [v["number"] for v in versions] == [2, 1]
    restored = api.post(f"/api/v1/sites/pages/{page.pk}/restore", {"version": 1}, format="json")
    assert restored.json()["blocks"][0]["props"]["body"] == "One"
    assert restored.json()["status"] == "changed"


def test_publishing_needs_the_publish_permission(org):
    page = SitePageFactory(organisation=org)
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    client = client_for(org, coordinator)
    assert client.get(f"/api/v1/sites/pages/{page.pk}").status_code == 200
    assert client.post(f"/api/v1/sites/pages/{page.pk}/publish").status_code == 403


def test_home_page_cannot_be_deleted(org, api):
    page = SitePageFactory(organisation=org, path="")
    assert api.delete(f"/api/v1/sites/pages/{page.pk}").status_code == 422
    other = SitePageFactory(organisation=org, site=page.site, path="faq")
    assert api.delete(f"/api/v1/sites/pages/{other.pk}").status_code == 204


def test_reserved_and_duplicate_paths(org, api):
    site = SiteFactory(organisation=org)
    SitePageFactory(organisation=org, site=site, path="about")
    assert (
        api.post(
            "/api/v1/sites/pages", {"title": "About", "path": "about"}, format="json"
        ).status_code
        == 422
    )
    assert (
        api.post("/api/v1/sites/pages", {"title": "API", "path": "api"}, format="json").status_code
        == 422
    )
    created = api.post("/api/v1/sites/pages", {"title": "Prices & fees"}, format="json")
    assert created.json()["path"] == "prices-fees"


def test_dynamic_blocks_tutor_pages_sitemap_and_robots(org, api):
    site = SiteFactory(organisation=org, published=True)
    profile = PublicProfileFactory(organisation=org, slug="ada-l")
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [
            {"type": "tutor_grid", "props": {"heading": "Tutors"}},
            {"type": "map", "props": {"lat": "53.8", "lng": "-1.55", "address": "Leeds"}},
        ]},
        format="json",
    )  # fmt: skip
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    client = site_client(org)
    home = client.get("/").content.decode()
    assert "/tutors/ada-l" in home
    assert "Ada L." in home
    assert "openstreetmap.org/export/embed.html" in home
    tutor_page = client.get("/tutors/ada-l")
    assert tutor_page.status_code == 200
    assert "Maths whizz" in tutor_page.content.decode()
    assert profile.tutor.email not in tutor_page.content.decode()
    sitemap = client.get("/sitemap.xml").content.decode()
    assert "/tutors/ada-l</loc>" in sitemap
    assert "Sitemap:" in client.get("/robots.txt").content.decode()


def test_unpublished_site_is_hidden_and_not_indexed(org):
    site = SiteFactory(organisation=org, published=False)
    page = SitePageFactory(organisation=org, site=site, path="")
    with tenant_context(org):
        from tutortrack.sites import services

        services.publish_page(page, None)
    assert site_client(org).get("/").status_code == 404
    assert "Disallow: /" in site_client(org).get("/robots.txt").content.decode()


def test_site_custom_domain_serves_the_website(org, api):
    site = SiteFactory(organisation=org, published=True)
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    with tenant_context(org):
        from tutortrack.core.time import now
        from tutortrack.sites import services

        services.publish_page(page, None)
    OrganisationDomain.objects.create(
        organisation=org,
        hostname="www.brightminds.co.uk",
        type="custom",
        purpose="site",
        verified_at=now(),
        verification_status="verified",
    )
    cache.clear()
    response = APIClient(HTTP_HOST="www.brightminds.co.uk").get("/")
    assert response.status_code == 200
    assert "<h1>Home</h1>" in response.content.decode()
    # The API still works on the website host (widgets on the site use it).
    assert (
        APIClient(HTTP_HOST="www.brightminds.co.uk").get("/api/v1/public/branding").status_code
        == 200
    )


def test_site_published_toggle_needs_publish_permission(org):
    site = SiteFactory(organisation=org)
    manager = MembershipFactory(organisation=org, role="coordinator").user
    response = client_for(org, manager).patch(
        f"/api/v1/sites/{site.pk}", {"published": True}, format="json"
    )
    assert response.status_code == 403
    with tenant_context(org):
        assert Site.objects.get(pk=site.pk).published is False


def test_page_published_status_is_tracked(org, api):
    page = SitePageFactory(organisation=org, path="x")
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    unpublished = api.post(f"/api/v1/sites/pages/{page.pk}/unpublish")
    assert unpublished.json()["status"] == "draft"
    with tenant_context(org):
        assert SitePage.objects.get(pk=page.pk).live_version_id is None


# --- tenant isolation ----------------------------------------------------------------------------


class TestSiteIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/sites"

    def make_object(self, organisation):
        return SiteFactory(organisation=organisation)


class TestSitePageIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/sites/pages"

    def make_object(self, organisation):
        return SitePageFactory(organisation=organisation)


def test_analytics_load_after_consent_and_csp_allows_only_that_script(org, api):
    from tutortrack.sites.render import script_hash

    site = SiteFactory(organisation=org, published=True, tag_manager_id="GTM-ABC1234")
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    response = site_client(org).get("/")
    html = response.content.decode()
    inline = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert "tt_consent" in inline
    assert '"GTM-ABC1234"' in inline
    assert script_hash(inline) in response["Content-Security-Policy"]
    assert (
        "unsafe-inline"
        not in response["Content-Security-Policy"].split("script-src")[1].split(";")[0]
    )
