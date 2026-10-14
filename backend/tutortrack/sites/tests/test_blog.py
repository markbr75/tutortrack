"""G6 (FR-24-4): blog and news posts in the website builder: posts, the latest-posts block,
RSS and SEO."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.sites import services
from tutortrack.sites.models import BlogPost

from .factories import SiteFactory, SitePageFactory
from .test_profiles_sites import site_client

pytestmark = pytest.mark.django_db


def make_post(org, site, title="Summer results", **kw):
    with tenant_context(org):
        return services.create_post(site, title=title, **kw)


def test_posts_are_drafted_published_and_served(org, api):
    SiteFactory(organisation=org, published=True)
    created = api.post(
        "/api/v1/sites/posts",
        {"title": "Summer results!", "excerpt": "Best year yet",
         "body": "<b>Well done</b>\n\nSee you in September", "author_name": "Priya",
         "seo_title": "Exam results 2026"},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.content
    post = created.json()
    assert (post["slug"], post["status"], post["url"]) == (
        "summer-results",
        "draft",
        "/blog/summer-results",
    )
    client = site_client(org)
    assert client.get("/blog/summer-results").status_code == 404  # drafts aren't live
    published = api.post(f"/api/v1/sites/posts/{post['id']}/publish", {}, format="json")
    assert published.status_code == 200, published.content
    assert published.json()["status"] == "published"
    assert OutboxEvent.objects.filter(event_type="blog_post.published").exists()

    page = client.get("/blog/summer-results")
    assert page.status_code == 200
    html = page.content.decode()
    assert "<title>Exam results 2026</title>" in html
    assert '<meta property="og:type" content="article">' in html
    assert '"@type": "BlogPosting"' in html or '"@type":"BlogPosting"' in html
    assert "&lt;b&gt;Well done&lt;/b&gt;" in html  # escaped, never raw HTML
    assert 'type="application/rss+xml"' in html
    index = client.get("/blog").content.decode()
    assert "/blog/summer-results" in index
    assert "Best year yet" in index
    rss = client.get("/blog/rss.xml")
    assert rss["Content-Type"].startswith("application/rss+xml")
    assert "<link>http://" in rss.content.decode()
    assert "Summer results!" in rss.content.decode()
    assert "/blog/summer-results</loc>" in client.get("/sitemap.xml").content.decode()


def test_scheduled_posts_wait_and_unpublished_posts_disappear(org):
    site = SiteFactory(organisation=org, published=True)
    later = make_post(org, site, title="Coming soon")
    live = make_post(org, site, title="Out now")
    with tenant_context(org):
        services.publish_post(later, at=now() + timedelta(days=2))
        services.publish_post(live)
    client = site_client(org)
    assert client.get("/blog/coming-soon").status_code == 404
    assert client.get("/blog/out-now").status_code == 200
    with tenant_context(org):
        services.unpublish_post(BlogPost.objects.get(pk=live.pk))
    assert client.get("/blog/out-now").status_code == 404


def test_latest_posts_block(org, api):
    site = SiteFactory(organisation=org, published=True)
    post = make_post(org, site, title="Open day", excerpt="Come and meet us")
    with tenant_context(org):
        services.publish_post(post)
    page = SitePageFactory(organisation=org, site=site, path="", title="Home")
    response = api.patch(
        f"/api/v1/sites/pages/{page.pk}",
        {"blocks": [{"type": "blog_list", "props": {"heading": "News", "limit": 2}}]},
        format="json",
    )
    assert response.status_code == 200, response.content
    api.post(f"/api/v1/sites/pages/{page.pk}/publish")
    home = site_client(org).get("/").content.decode()
    assert "/blog/open-day" in home
    assert "Come and meet us" in home
    blocks = {b["key"] for b in api.get("/api/v1/sites/blocks").json()}
    assert "blog_list" in blocks


def test_slugs_are_unique_and_blog_is_a_reserved_page_address(org, api):
    site = SiteFactory(organisation=org)
    make_post(org, site, title="Hello")
    clash = api.post("/api/v1/sites/posts", {"title": "Hello"}, format="json")
    assert clash.status_code == 422
    assert api.post("/api/v1/sites/pages", {"title": "Blog", "path": "blog"},
                    format="json").status_code == 422  # fmt: skip


def test_only_publishers_publish_posts(org):
    site = SiteFactory(organisation=org)
    post = make_post(org, site)
    tutor = MembershipFactory(organisation=org, role="tutor").user
    assert client_for(org, tutor).post(f"/api/v1/sites/posts/{post.pk}/publish").status_code == 403


class TestBlogPostIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/sites/posts"

    def make_object(self, organisation):
        site = SiteFactory(organisation=organisation)
        return make_post(organisation, site)
