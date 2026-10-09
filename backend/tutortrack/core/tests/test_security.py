"""E29-T01: security headers and SSRF-safe outbound URLs."""

from __future__ import annotations

import socket
from unittest import mock

import pytest
from rest_framework.test import APIClient

from tutortrack.core import net


@pytest.mark.django_db
def test_api_responses_are_locked_down():
    response = APIClient().get("/healthz")
    csp = response["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "camera=()" in response["Permissions-Policy"]
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response["X-Frame-Options"] == "DENY"


@pytest.mark.django_db
def test_html_pages_get_a_nonce_policy(client):
    response = client.get("/django-admin/login/")
    csp = response["Content-Security-Policy"]
    assert "script-src 'self' 'nonce-" in csp
    assert "object-src 'none'" in csp
    nonces = {client.get("/django-admin/login/")["Content-Security-Policy"] for _ in range(2)}
    assert len(nonces) == 2  # fresh per response


def addrinfo(*ips: str):
    return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, 1, 6, "", (ip, 443)) for ip in ips]


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - an address under test, not a bind
        "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1",
    ],
)  # fmt: skip
def test_private_and_reserved_addresses_are_refused(ip):
    with mock.patch("socket.getaddrinfo", return_value=addrinfo(ip)), pytest.raises(net.UnsafeURL):
        net.safe_url("https://hooks.example.com/x")


def test_public_https_urls_are_allowed():
    with mock.patch("socket.getaddrinfo", return_value=addrinfo("93.184.216.34")):
        checked = net.safe_url("https://hooks.example.com/path?q=1")
    assert checked.host == "hooks.example.com"
    assert checked.addresses == ("93.184.216.34",)


def test_any_private_address_among_several_is_refused():
    """A hostname with one public and one internal record must not be fetched."""
    records = addrinfo("93.184.216.34", "10.0.0.5")
    with mock.patch("socket.getaddrinfo", return_value=records), pytest.raises(net.UnsafeURL):
        net.safe_url("https://mixed.example.com/")


@pytest.mark.parametrize(
    "url",
    ["http://example.com/", "ftp://example.com/", "https://user:pw@example.com/",
     "https://example.com:8080/", "https:///nohost", "file:///etc/passwd"],
)  # fmt: skip
def test_bad_schemes_ports_and_credentials_are_refused(url):
    records = addrinfo("93.184.216.34")
    with mock.patch("socket.getaddrinfo", return_value=records), pytest.raises(net.UnsafeURL):
        net.safe_url(url)


def test_dns_rebinding_between_check_and_connect_is_refused():
    answers = iter([addrinfo("93.184.216.34"), addrinfo("10.0.0.5")])
    with (
        mock.patch("socket.getaddrinfo", side_effect=lambda *a, **k: next(answers)),
        pytest.raises(net.UnsafeURL),
    ):
        net.safe_urlopen("https://rebind.example.com/")
