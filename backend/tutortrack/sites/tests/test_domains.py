"""E24-T02: custom domains: adding and validation, DNS records, providers (fakes and the
real clients' parsing), routing, per-domain cookies, strict hosts, the TLS ask endpoint and
links that use the custom domain."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from rest_framework.test import APIClient

from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.sites.middleware import CustomDomainMiddleware
from tutortrack.sites.providers import certificate_provider, dns, dns_resolver
from tutortrack.sites.providers.certificates import CloudflareForSaaS, FakeCertificates
from tutortrack.sites.providers.dns import FakeDnsResolver
from tutortrack.tenancy import custom_domains
from tutortrack.tenancy.models import OrganisationDomain

from .test_branding_widgets import Entitlements

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fakes():
    FakeDnsResolver.reset()
    FakeCertificates.reset()
    cache.clear()
    yield
    FakeDnsResolver.reset()
    FakeCertificates.reset()


def custom(org: Any, hostname: str, **kw: Any) -> OrganisationDomain:
    defaults = {
        "type": "custom",
        "purpose": "app",
        "verification_token": "tt-verify=abc",
    }
    return OrganisationDomain.objects.create(
        organisation=org, hostname=hostname, **{**defaults, **kw}
    )


def test_add_domain_returns_dns_instructions(org, api):
    response = api.post(
        "/api/v1/domains", {"hostname": "Portal.BrightMinds.co.uk", "purpose": "app"}, format="json"
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["hostname"] == "portal.brightminds.co.uk"
    assert body["verification_status"] == "pending"
    assert body["ssl_status"] == "pending"
    records = {r["record_type"]: r for r in body["dns_records"]}
    assert records["CNAME"]["value"] == settings.CUSTOM_DOMAINS["CNAME_TARGET"]
    assert records["TXT"]["name"] == "_tutortrack-challenge.portal.brightminds.co.uk"
    assert records["TXT"]["value"].startswith("tt-verify=")
    event = OutboxEvent.objects.get(event_type="custom_domain.added")
    assert event.payload["data"]["hostname"] == "portal.brightminds.co.uk"


@pytest.mark.parametrize(
    "hostname",
    [
        "192.168.0.1",
        "localhost",
        "nodots",
        "brightminds.tutortrack.test",
        "-bad-.example.com",
        "a..b.com",
    ],
)
def test_invalid_hostnames_are_rejected(api, hostname):
    response = api.post("/api/v1/domains", {"hostname": hostname, "purpose": "app"}, format="json")
    assert response.status_code == 422


def test_a_domain_belongs_to_one_organisation(org, other_org, api):
    custom(other_org, "portal.example.com")
    response = api.post(
        "/api/v1/domains", {"hostname": "portal.example.com", "purpose": "app"}, format="json"
    )
    assert response.status_code == 409


def test_custom_domains_need_the_entitlement(api, monkeypatch):
    monkeypatch.setattr(entitlements, "_resolver", Entitlements("custom_domain"))
    response = api.post(
        "/api/v1/domains", {"hostname": "portal.example.com", "purpose": "app"}, format="json"
    )
    assert response.status_code == 403


def test_limit_of_five_domains(org, api):
    for n in range(5):
        custom(org, f"d{n}.example.com")
    response = api.post(
        "/api/v1/domains", {"hostname": "d9.example.com", "purpose": "site"}, format="json"
    )
    assert response.status_code == 422


def test_check_now_and_remove_publish_events(org, api):
    domain = custom(org, "portal.example.com", verification_status="failed")
    response = api.post(f"/api/v1/domains/{domain.pk}/verify")
    assert response.json()["verification_status"] == "pending"
    assert OutboxEvent.objects.filter(event_type="custom_domain.check_requested").exists()
    assert api.delete(f"/api/v1/domains/{domain.pk}").status_code == 204
    assert not OrganisationDomain.objects.filter(pk=domain.pk).exists()
    assert OutboxEvent.objects.filter(event_type="custom_domain.removed").exists()


def test_former_slugs_are_not_listed_as_custom_domains(org, api):
    OrganisationDomain.objects.create(organisation=org, hostname="oldslug", type="subdomain")
    custom(org, "portal.example.com")
    assert [d["hostname"] for d in api.get("/api/v1/domains").json()] == ["portal.example.com"]


# --- providers -----------------------------------------------------------------------------------


def test_dns_check_accepts_the_txt_token_or_a_cname_to_the_edge():
    resolver = FakeDnsResolver(auto_verify=False)
    assert not dns.check(resolver, "portal.example.com", "tt-verify=abc").verified
    FakeDnsResolver.records[("_tutortrack-challenge.portal.example.com", "TXT")] = [
        '"tt-verify=abc"'
    ]
    assert dns.check(resolver, "portal.example.com", "tt-verify=abc") == dns.DnsCheck(True, "txt")
    FakeDnsResolver.reset()
    FakeDnsResolver.records[("www.example.com", "CNAME")] = [
        settings.CUSTOM_DOMAINS["CNAME_TARGET"] + "."
    ]
    assert dns.check(resolver, "www.example.com", "x").method == "cname"
    FakeDnsResolver.records[("other.example.com", "CNAME")] = ["elsewhere.net"]
    result = dns.check(resolver, "other.example.com", "x")
    assert not result.verified
    assert "elsewhere.net" in result.detail


def test_dns_lookup_errors_are_not_verifications():
    class Broken:
        def txt(self, name):
            raise OSError("timeout")

        def cname(self, name):
            return ""

    result = dns.check(Broken(), "portal.example.com", "t")
    assert not result.verified
    assert "timeout" in result.detail


def test_providers_fall_back_to_fakes_without_credentials(settings):
    assert isinstance(dns_resolver(), FakeDnsResolver)
    assert isinstance(certificate_provider(), FakeCertificates)
    settings.CUSTOM_DOMAINS = {
        **settings.CUSTOM_DOMAINS,
        "CLOUDFLARE_API_TOKEN": "t",
        "CLOUDFLARE_ZONE_ID": "z",
    }
    assert isinstance(certificate_provider(), CloudflareForSaaS)


def test_cloudflare_states_are_mapped():
    state = CloudflareForSaaS._state(
        {"ssl": {"status": "active", "expires_on": "2027-01-01T00:00:00Z"}}
    )
    assert state.status == "active"
    assert state.expires_at.year == 2027
    assert CloudflareForSaaS._state({"ssl": {"status": "pending_validation"}}).status == "issuing"
    assert CloudflareForSaaS._state({"ssl": {"status": "validation_timed_out"}}).status == "failed"
    assert CloudflareForSaaS._state(None).status == "failed"


def test_fake_certificates_follow_their_script():
    FakeCertificates.script["a.example.com"] = ["issuing", "active"]
    fake = FakeCertificates()
    assert fake.request("a.example.com").status == "issuing"
    active = fake.status("a.example.com")
    assert active.status == "active"
    assert active.expires_at > now() + timedelta(days=80)


def test_services_record_verification_and_certificate(org):
    domain = custom(org, "portal.example.com")
    with tenant_context(org):
        from django.db import transaction

        with transaction.atomic():
            custom_domains.mark_verified(domain.pk, method="txt")
            custom_domains.mark_verified(domain.pk, method="txt")  # idempotent
            custom_domains.record_certificate(
                domain.pk, status="active", expires_at=now() + timedelta(days=90)
            )
    domain.refresh_from_db()
    assert domain.verification_status == "verified"
    assert domain.ssl_status == "active"
    assert OutboxEvent.objects.filter(event_type="custom_domain.verified").count() == 1
    assert OutboxEvent.objects.filter(event_type="custom_domain.activated").count() == 1


# --- routing, links, cookies ---------------------------------------------------------------------


def test_verified_custom_domain_resolves_the_organisation(org):
    custom(org, "portal.example.com")
    unverified = APIClient(HTTP_HOST="portal.example.com").get("/api/v1/public/branding")
    assert unverified.status_code == 404  # not verified yet: not this organisation's host
    OrganisationDomain.objects.filter(hostname="portal.example.com").update(verified_at=now())
    verified = APIClient(HTTP_HOST="portal.example.com").get("/api/v1/public/branding")
    assert verified.json()["name"] == org.name


def test_links_use_the_custom_domain_once_it_has_a_certificate(org):
    """AC: emails link to the custom domain."""
    assert org.base_url == f"https://{org.slug}.{settings.TENANT_BASE_DOMAIN}"
    domain = custom(org, "portal.example.com", verified_at=now())
    assert org.base_url.endswith(settings.TENANT_BASE_DOMAIN)  # no certificate yet
    domain.ssl_status = "active"
    domain.save()
    assert org.base_url == "https://portal.example.com"
    custom(org, "www.example.com", purpose="site", verified_at=now(), ssl_status="active")
    assert org.base_url == "https://portal.example.com"  # the website domain isn't the app's


def test_invitation_emails_link_to_the_custom_domain(
    org, user, member, mailoutbox, django_capture_on_commit_callbacks
):
    custom(org, "portal.example.com", verified_at=now(), ssl_status="active")
    from tutortrack.identity.services import invite

    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        invite("new.tutor@example.com", role="tutor")
    assert any("https://portal.example.com/accept-invite" in m.body for m in mailoutbox)


def _response_with_cookie(domain: str) -> HttpResponse:
    response = HttpResponse("ok")
    response.set_cookie("sessionid", "abc", domain=domain)
    return response


def test_auth_cookies_are_host_only_on_custom_domains(rf):
    middleware = CustomDomainMiddleware(lambda request: _response_with_cookie(".tutortrack.test"))
    on_custom = middleware(rf.get("/", HTTP_HOST="portal.example.com"))
    assert on_custom.cookies["sessionid"]["domain"] == ""
    on_platform = middleware(rf.get("/", HTTP_HOST="brightminds.tutortrack.test"))
    assert on_platform.cookies["sessionid"]["domain"] == ".tutortrack.test"


def test_strict_hosts_refuse_unknown_hostnames(org, rf, settings):
    settings.CUSTOM_DOMAINS = {**settings.CUSTOM_DOMAINS, "STRICT_HOSTS": True}
    middleware = CustomDomainMiddleware(lambda request: HttpResponse("ok"))

    def status(host: str, path: str = "/api/v1/me") -> int:
        request: HttpRequest = rf.get(path, HTTP_HOST=host)
        return middleware(request).status_code

    assert status("evil.example") == 400
    assert status("evil.example", "/healthz") == 200
    assert status(f"{org.slug}.{settings.TENANT_BASE_DOMAIN}") == 200
    custom(org, "portal.example.com", verified_at=now())
    cache.clear()
    assert status("portal.example.com") == 200


def test_tls_ask_endpoint_allows_only_connected_domains(org):
    client = APIClient(HTTP_HOST="custom.tutortrack.app")
    assert client.get("/internal/tls/ask", {"domain": "portal.example.com"}).status_code == 404
    custom(org, "portal.example.com", verified_at=now())
    assert client.get("/internal/tls/ask", {"domain": "portal.example.com"}).status_code == 200
    site_host = f"{org.slug}.{settings.CUSTOM_DOMAINS['SITE_BASE_DOMAIN']}"
    assert client.get("/internal/tls/ask", {"domain": site_host}).status_code == 200
    assert client.get("/internal/tls/ask").status_code == 400


class TestDomainIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/domains"

    def make_object(self, organisation):
        return custom(organisation, f"portal.{organisation.slug}.example.com")
