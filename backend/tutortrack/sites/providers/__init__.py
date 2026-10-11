"""Provider selection for custom domains (FR-24-2): real clients when configured, fakes
otherwise, so every flow runs end to end without credentials."""

from __future__ import annotations

from django.conf import settings

from .certificates import CaddyOnDemand, CertificateProvider, CloudflareForSaaS, FakeCertificates
from .dns import DnsResolver, DohResolver, FakeDnsResolver


def dns_resolver() -> DnsResolver:
    config = getattr(settings, "CUSTOM_DOMAINS", {})
    if config.get("DNS_RESOLVER") == "doh":
        return DohResolver()
    return FakeDnsResolver()


def certificate_provider() -> CertificateProvider:
    config = getattr(settings, "CUSTOM_DOMAINS", {})
    choice = config.get("CERT_PROVIDER") or (
        "cloudflare" if config.get("CLOUDFLARE_API_TOKEN") else "fake"
    )
    if choice == "cloudflare" and config.get("CLOUDFLARE_API_TOKEN"):
        return CloudflareForSaaS(
            config["CLOUDFLARE_API_TOKEN"], config.get("CLOUDFLARE_ZONE_ID", "")
        )
    if choice == "caddy":
        return CaddyOnDemand()
    return FakeCertificates()


__all__ = ["certificate_provider", "dns_resolver"]
