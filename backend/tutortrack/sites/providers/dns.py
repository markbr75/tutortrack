"""DNS checks for custom-domain verification (FR-24-2).

A domain is verified when either

* ``_tutortrack-challenge.<host>`` has a TXT record with the domain's token (ownership), or
* ``<host>`` is a CNAME to ``CUSTOM_DOMAINS["CNAME_TARGET"]`` (traffic already reaches us,
  which is what an HTTP challenge proves, without plain-HTTP fetches the SSRF guard forbids).

``DohResolver`` asks a DNS-over-HTTPS service (fixed URL, no credentials); ``FakeDnsResolver``
answers from an in-memory table (tests) or accepts everything (``FAKE_AUTO_VERIFY``, local).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from django.conf import settings

TXT, CNAME = 16, 5


@dataclass(frozen=True)
class DnsCheck:
    verified: bool
    method: str = ""  # txt | cname
    detail: str = ""


def _config() -> dict[str, Any]:
    return dict(getattr(settings, "CUSTOM_DOMAINS", {}))


class DnsResolver(Protocol):
    def txt(self, name: str) -> list[str]: ...

    def cname(self, name: str) -> str: ...


def check(resolver: DnsResolver, hostname: str, token: str) -> DnsCheck:
    from tutortrack.tenancy.custom_domains import challenge_name

    target = str(_config().get("CNAME_TARGET", "")).lower().rstrip(".")
    try:
        records = resolver.txt(challenge_name(hostname))
        if token and any(r.strip().strip('"') == token for r in records):
            return DnsCheck(True, "txt")
        cname = resolver.cname(hostname).lower().rstrip(".")
    except OSError as exc:
        return DnsCheck(False, detail=f"DNS lookup failed: {exc}"[:300])
    if target and cname == target:
        return DnsCheck(True, "cname")
    if cname:
        return DnsCheck(False, detail=f"{hostname} points to {cname}, not {target}.")
    return DnsCheck(False, detail="The DNS records were not found yet.")


class DohResolver:
    """RFC 8484 JSON API (Cloudflare/Google). The URL is fixed by settings."""

    def __init__(self, url: str | None = None, timeout: float = 5):
        self.url = url or str(_config().get("DOH_URL", "https://cloudflare-dns.com/dns-query"))
        self.timeout = timeout

    def _query(self, name: str, rtype: int) -> list[str]:
        query = urllib.parse.urlencode({"name": name, "type": rtype})
        request = urllib.request.Request(  # noqa: S310 - fixed https URL from settings
            f"{self.url}?{query}", headers={"Accept": "application/dns-json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            body = json.loads(response.read())
        return [str(a.get("data", "")) for a in body.get("Answer", []) if a.get("type") == rtype]

    def txt(self, name: str) -> list[str]:
        return self._query(name, TXT)

    def cname(self, name: str) -> str:
        found = self._query(name, CNAME)
        return found[0] if found else ""


class FakeDnsResolver:
    """In-memory DNS: ``FakeDnsResolver.records[(name, "TXT")] = [...]``."""

    records: ClassVar[dict[tuple[str, str], list[str]]] = {}

    def __init__(self, auto_verify: bool | None = None):
        self.auto_verify = (
            bool(_config().get("FAKE_AUTO_VERIFY")) if auto_verify is None else auto_verify
        )

    def txt(self, name: str) -> list[str]:
        if self.auto_verify:
            return []
        return list(self.records.get((name.lower(), "TXT"), []))

    def cname(self, name: str) -> str:
        if self.auto_verify:
            return str(_config().get("CNAME_TARGET", ""))
        found = self.records.get((name.lower(), "CNAME"), [])
        return found[0] if found else ""

    @classmethod
    def reset(cls) -> None:
        cls.records.clear()
