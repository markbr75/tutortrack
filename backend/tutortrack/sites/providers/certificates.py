"""TLS certificates for custom domains (FR-24-2).

* ``CloudflareForSaaS``: Cloudflare custom hostnames (``CLOUDFLARE_API_TOKEN`` + zone).
* ``CaddyOnDemand``: Caddy issues on the first TLS handshake after asking
  ``/internal/tls/ask?domain=`` (which only allows verified domains); ``status`` probes the
  hostname's certificate over TLS (public addresses only).
* ``FakeCertificates``: deterministic; scripted states for tests, else active at once.

All return ``CertState``; renewals are automatic with both real providers, so the
workflow's monitoring only records the new expiry and alerts on failure.
"""

from __future__ import annotations

import json
import socket
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol

from django.conf import settings

from tutortrack.core.net import UnsafeURL, is_public_ip
from tutortrack.core.time import now

ACTIVE, PENDING, FAILED = "active", "issuing", "failed"


@dataclass(frozen=True)
class CertState:
    status: str  # issuing | active | failed
    expires_at: datetime | None = None
    detail: str = ""


class CertificateProvider(Protocol):
    name: str

    def request(self, hostname: str) -> CertState: ...

    def status(self, hostname: str) -> CertState: ...

    def release(self, hostname: str) -> None: ...


def _config() -> dict[str, Any]:
    return dict(getattr(settings, "CUSTOM_DOMAINS", {}))


class CloudflareForSaaS:
    name = "cloudflare"
    API = "https://api.cloudflare.com/client/v4"

    def __init__(self, token: str, zone_id: str, timeout: float = 10):
        self.token, self.zone_id, self.timeout = token, zone_id, timeout

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - fixed Cloudflare API host
            f"{self.API}/zones/{self.zone_id}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read())

    def _find(self, hostname: str) -> dict[str, Any] | None:
        query = urllib.parse.urlencode({"hostname": hostname})
        found = self._call("GET", f"/custom_hostnames?{query}").get("result") or []
        return found[0] if found else None

    @staticmethod
    def _state(row: dict[str, Any] | None) -> CertState:
        if row is None:
            return CertState(FAILED, detail="The hostname is not registered with the edge.")
        ssl_info = row.get("ssl") or {}
        status = str(ssl_info.get("status", ""))
        expires = ssl_info.get("expires_on") or (ssl_info.get("certificates") or [{}])[0].get(
            "expires_on"
        )
        expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None
        if status == "active":
            return CertState(ACTIVE, expires_at)
        if status in {"validation_timed_out", "issuance_timed_out", "deleted"}:
            return CertState(FAILED, detail=f"Certificate {status.replace('_', ' ')}.")
        return CertState(PENDING, detail=status.replace("_", " "))

    def request(self, hostname: str) -> CertState:
        existing = self._find(hostname)
        if existing is not None:
            return self._state(existing)
        created = self._call(
            "POST",
            "/custom_hostnames",
            {"hostname": hostname, "ssl": {"method": "http", "type": "dv"}},
        )
        return self._state(created.get("result"))

    def status(self, hostname: str) -> CertState:
        return self._state(self._find(hostname))

    def release(self, hostname: str) -> None:
        row = self._find(hostname)
        if row is not None:
            self._call("DELETE", f"/custom_hostnames/{row['id']}")


class CaddyOnDemand:
    name = "caddy"

    def __init__(self, timeout: float = 8):
        self.timeout = timeout

    def request(self, hostname: str) -> CertState:
        # Caddy issues on the first handshake; asking now warms it up.
        return self.status(hostname)

    def status(self, hostname: str) -> CertState:
        try:
            infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
            addresses = sorted({str(i[4][0]) for i in infos})
            if not addresses or not all(is_public_ip(a) for a in addresses):
                raise UnsafeURL("The hostname points to a private address.")
            context = ssl.create_default_context()
            with (
                socket.create_connection((addresses[0], 443), timeout=self.timeout) as raw,
                context.wrap_socket(raw, server_hostname=hostname) as tls,
            ):
                cert = tls.getpeercert() or {}
        except ssl.SSLCertVerificationError as exc:
            return CertState(PENDING, detail=str(exc)[:300])
        except (OSError, UnsafeURL) as exc:
            return CertState(PENDING, detail=str(exc)[:300])
        not_after = cert.get("notAfter")
        expires = (
            datetime.fromtimestamp(ssl.cert_time_to_seconds(str(not_after)), tz=UTC)
            if not_after
            else None
        )
        return CertState(ACTIVE, expires)

    def release(self, hostname: str) -> None:
        return None  # the ask endpoint stops allowing it once the row is gone


class FakeCertificates:
    """``FakeCertificates.script[hostname] = ["issuing", "error", "active"]`` (one state per
    call; ``error`` raises, like a provider outage)."""

    name = "fake"
    script: ClassVar[dict[str, list[str]]] = {}
    released: ClassVar[list[str]] = []

    def _next(self, hostname: str) -> CertState:
        queue = self.script.get(hostname)
        status = queue.pop(0) if queue else ACTIVE
        if status == "error":  # an outage: the activity fails and Temporal retries it
            raise RuntimeError("Fake certificate authority unavailable.")
        if status == ACTIVE:
            return CertState(ACTIVE, now().replace(microsecond=0) + timedelta(days=90))
        if status == FAILED:
            return CertState(FAILED, detail="Fake certificate authority refused the order.")
        return CertState(PENDING, detail="Waiting for the certificate authority.")

    def request(self, hostname: str) -> CertState:
        return self._next(hostname)

    def status(self, hostname: str) -> CertState:
        return self._next(hostname)

    def release(self, hostname: str) -> None:
        self.released.append(hostname)

    @classmethod
    def reset(cls) -> None:
        cls.script.clear()
        cls.released.clear()


__all__ = [
    "ACTIVE",
    "FAILED",
    "PENDING",
    "CaddyOnDemand",
    "CertState",
    "CertificateProvider",
    "CloudflareForSaaS",
    "FakeCertificates",
]
