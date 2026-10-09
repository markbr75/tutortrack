"""Outbound HTTP safety (FR-29-1 SSRF protection).

Every fetch of a URL that a tenant or user can influence (webhook targets E27, URL imports
E28, calendar feeds E22, avatar URLs) must go through ``safe_url`` / ``safe_urlopen``:

* only ``https`` (``http`` only when ``ALLOW_HTTP_OUTBOUND`` is set, for local testing),
* no credentials in the URL, only default ports unless allowed,
* the hostname must resolve exclusively to public addresses: loopback, private, link-local
  (including the cloud metadata endpoint 169.254.169.254), multicast, reserved and
  carrier-grade NAT ranges are refused, for IPv4 and IPv6,
* redirects are not followed automatically (each hop would need re-validation).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

ALLOWED_PORTS = {443, 80}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURL(ValueError):
    pass


@dataclass(frozen=True)
class CheckedURL:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


def is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT)
    )


def _resolve(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Cannot resolve {host!r}") from exc
    return tuple(sorted({str(info[4][0]) for info in infos}))


def safe_url(url: str) -> CheckedURL:
    parts = urlsplit(url.strip())
    schemes = {"https", "http"} if getattr(settings, "ALLOW_HTTP_OUTBOUND", False) else {"https"}
    if parts.scheme not in schemes:
        raise UnsafeURL("Only https URLs are allowed.")
    if parts.username or parts.password:
        raise UnsafeURL("URLs must not contain credentials.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("The URL has no host.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS and port not in getattr(settings, "OUTBOUND_EXTRA_PORTS", ()):
        raise UnsafeURL("Non-standard ports are not allowed.")
    addresses = _resolve(host, port)
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise UnsafeURL("The URL points to a private or reserved network address.")
    return CheckedURL(url=url.strip(), host=host, port=port, addresses=addresses)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # surface 3xx to the caller, who must re-validate the Location


def safe_urlopen(
    url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
    method: str = "GET", timeout: float = 10,
) -> Any:  # fmt: skip
    """``urllib`` open after validation, without following redirects.

    The address is re-checked immediately before connecting, narrowing DNS-rebinding races.
    """
    checked = safe_url(url)
    if _resolve(checked.host, checked.port) != checked.addresses:
        raise UnsafeURL("The host's addresses changed during the request.")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(checked.url, data=data, headers=headers or {}, method=method)  # noqa: S310
    return opener.open(request, timeout=timeout)
