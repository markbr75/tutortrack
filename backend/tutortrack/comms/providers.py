"""Phase 2 channel providers (E13-T12), each with a fake twin used in tests and whenever
the platform keys are empty (development):

* **WhatsApp** through Twilio's WhatsApp Business API: free-form text inside the 24-hour
  customer service window, otherwise an approved Content template (``content_sid`` plus
  variables). Status callbacks and inbound messages share the SMS webhooks (Twilio
  signs them the same way; addresses carry a ``whatsapp:`` prefix).
* **Sender domains** through Postmark's Domains API: creating a domain returns the DKIM
  and return-path DNS records; verifying asks Postmark to check them. The domain is
  typed in by a tenant, but we never fetch it: only Postmark's fixed API host is called.

Provider hosts are constants (no tenant-influenced URLs here). Errors never include
tokens or message bodies.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Protocol

from django.conf import settings

from .channels import ChannelError, SmsResult

# --- WhatsApp -----------------------------------------------------------------------------------


def wa_address(phone: str) -> str:
    return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"


def strip_wa(address: str) -> str:
    return address.removeprefix("whatsapp:")


class WhatsAppProvider(Protocol):
    def send(
        self,
        *,
        to: str,
        status_callback: str,
        body: str = "",
        content_sid: str = "",
        variables: dict[str, str] | None = None,
        sender: str = "",
    ) -> SmsResult: ...


class TwilioWhatsApp:
    def __init__(self) -> None:
        self.sid = settings.TWILIO["ACCOUNT_SID"]
        self.token = settings.TWILIO["AUTH_TOKEN"]
        self.sender = settings.TWILIO["WHATSAPP_FROM"]

    def send(
        self,
        *,
        to: str,
        status_callback: str,
        body: str = "",
        content_sid: str = "",
        variables: dict[str, str] | None = None,
        sender: str = "",
    ) -> SmsResult:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        params = {
            "To": wa_address(to),
            "From": wa_address(sender or self.sender),
            "StatusCallback": status_callback,
        }
        if content_sid:
            params["ContentSid"] = content_sid
            params["ContentVariables"] = json.dumps(variables or {})
        else:
            params["Body"] = body
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(params).encode(),
            headers={"Authorization": f"Basic {auth}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise ChannelError(f"Twilio WhatsApp refused the message ({exc.code}).") from None
        except (urllib.error.URLError, OSError) as exc:
            raise ChannelError(f"Twilio WhatsApp unreachable ({type(exc).__name__}).") from None
        return SmsResult(str(payload.get("sid", "")), str(payload.get("status", "queued")))


class FakeWhatsApp:
    """Records WhatsApp messages instead of sending them (no Twilio WhatsApp sender)."""

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []

    def send(
        self,
        *,
        to: str,
        status_callback: str,
        body: str = "",
        content_sid: str = "",
        variables: dict[str, str] | None = None,
        sender: str = "",
    ) -> SmsResult:
        self.outbox.append(
            {
                "to": wa_address(to),
                "body": body,
                "content_sid": content_sid,
                "variables": dict(variables or {}),
                "from": sender,
                "status_callback": status_callback,
            }
        )
        return SmsResult(f"WAfake{len(self.outbox)}", "queued")


@cache
def whatsapp_provider() -> WhatsAppProvider:
    if settings.TWILIO["ACCOUNT_SID"] and settings.TWILIO["WHATSAPP_FROM"]:
        return TwilioWhatsApp()
    return FakeWhatsApp()


# --- sender domains -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DnsRecord:
    purpose: str  # dkim | return_path | spf | dmarc
    type: str  # TXT | CNAME
    host: str
    value: str
    verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "type": self.type,
            "host": self.host,
            "value": self.value,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class DomainState:
    ref: str
    records: list[DnsRecord] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        needed = [r for r in self.records if r.purpose in {"dkim", "return_path"}]
        return bool(needed) and all(r.verified for r in needed)


def advisory_records(domain: str) -> list[DnsRecord]:
    """Records we recommend but the provider doesn't check (SPF include and DMARC)."""
    return [
        DnsRecord("spf", "TXT", domain, "v=spf1 a mx include:spf.mtasv.net ~all"),
        DnsRecord(
            "dmarc", "TXT", f"_dmarc.{domain}", "v=DMARC1; p=none; rua=mailto:dmarc@" + domain
        ),
    ]


class SenderDomainProvider(Protocol):
    def create(self, domain: str) -> DomainState: ...

    def verify(self, ref: str, domain: str) -> DomainState: ...

    def delete(self, ref: str) -> None: ...


class PostmarkDomains:
    BASE = "https://api.postmarkapp.com/domains"

    def __init__(self) -> None:
        self.token = settings.COMMS["POSTMARK_ACCOUNT_TOKEN"]

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        from tutortrack.integrations.providers import ProviderError
        from tutortrack.integrations.providers.http import request

        try:
            response = request(
                method,
                f"{self.BASE}{path}",
                json_body=body,
                headers={"X-Postmark-Account-Token": self.token},
                provider="postmark",
            )
        except ProviderError as exc:
            raise ChannelError(str(exc)) from None
        return response.json() if response.body else {}

    def _state(self, data: dict[str, Any], domain: str) -> DomainState:
        dkim_host = str(data.get("DKIMPendingHost") or data.get("DKIMHost") or "")
        dkim_value = str(data.get("DKIMPendingTextValue") or data.get("DKIMTextValue") or "")
        return DomainState(
            ref=str(data.get("ID", "")),
            records=[
                DnsRecord("dkim", "TXT", dkim_host, dkim_value, bool(data.get("DKIMVerified"))),
                DnsRecord(
                    "return_path",
                    "CNAME",
                    str(data.get("ReturnPathDomain") or f"pm-bounces.{domain}"),
                    str(data.get("ReturnPathDomainCNAMEValue") or "pm.mtasv.net"),
                    bool(data.get("ReturnPathDomainVerified")),
                ),
            ],
        )

    def create(self, domain: str) -> DomainState:
        data = self._call("POST", "", {"Name": domain, "ReturnPathDomain": f"pm-bounces.{domain}"})
        return self._state(data, domain)

    def verify(self, ref: str, domain: str) -> DomainState:
        self._call("PUT", f"/{ref}/verifyDkim")
        data = self._call("PUT", f"/{ref}/verifyReturnPath")
        return self._state(data, domain)

    def delete(self, ref: str) -> None:
        self._call("DELETE", f"/{ref}")


class FakeSenderDomains:
    """Development and tests: DNS "verifies" on the first check, except for domains
    containing ``unverified`` (to show the failure path)."""

    def __init__(self) -> None:
        self.domains: dict[str, str] = {}

    def _records(self, domain: str, verified: bool) -> list[DnsRecord]:
        return [
            DnsRecord(
                "dkim",
                "TXT",
                f"20261014pm._domainkey.{domain}",
                "k=rsa;p=MIGfMA0GCSqGSIb3DQ",
                verified,
            ),
            DnsRecord("return_path", "CNAME", f"pm-bounces.{domain}", "pm.mtasv.net", verified),
        ]

    def create(self, domain: str) -> DomainState:
        ref = str(len(self.domains) + 1000)
        self.domains[ref] = domain
        return DomainState(ref, self._records(domain, False))

    def verify(self, ref: str, domain: str) -> DomainState:
        return DomainState(ref, self._records(domain, "unverified" not in domain))

    def delete(self, ref: str) -> None:
        self.domains.pop(ref, None)


@cache
def sender_domain_provider() -> SenderDomainProvider:
    if settings.COMMS["POSTMARK_ACCOUNT_TOKEN"]:
        return PostmarkDomains()
    return FakeSenderDomains()
