"""Mailchimp and Brevo audience sync clients (E13-T12, FR-13-9) on the E22 integration
framework: registered as ``credentials`` providers (an API key, organisation level) with a
``marketing`` client kind, each with a fake twin used in tests and without live keys.

* **Mailchimp:** the key's suffix names the data centre (``…-us21`` →
  ``https://us21.api.mailchimp.com/3.0``). That host is tenant-influenced, so it is
  checked against Mailchimp's pattern and opened through ``core.net.safe_urlopen``
  (``user_url=True``). Members are upserted by the MD5 of the lower-case address; tags
  are added with the member tags endpoint.
* **Brevo:** a fixed host (``api.brevo.com``); contacts are upserted into the chosen list
  (Brevo has no tags: they go into the ``TAGS`` attribute).

Clients never touch the database and never log keys or addresses.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings

from tutortrack.integrations import providers as registry
from tutortrack.integrations.providers import (
    AccountInfo,
    AuthError,
    Credentials,
    Provider,
    ProviderError,
    ProviderSpec,
)

CAPABILITY = "marketing"
PROVIDERS = ("mailchimp", "brevo")
MANAGE = "comms.channels.manage"


@dataclass(frozen=True)
class Audience:
    id: str
    name: str
    members: int = 0


@dataclass(frozen=True)
class Member:
    email: str
    first_name: str = ""
    last_name: str = ""
    tags: tuple[str, ...] = ()


@dataclass
class SyncResult:
    upserted: int = 0
    unsubscribed: int = 0
    errors: list[str] = field(default_factory=list)


class MarketingClient(Protocol):
    def verify(self, creds: Credentials) -> AccountInfo: ...

    def audiences(self, creds: Credentials) -> list[Audience]: ...

    def upsert(self, creds: Credentials, audience_id: str, members: list[Member]) -> SyncResult: ...

    def unsubscribe(
        self, creds: Credentials, audience_id: str, emails: list[str]
    ) -> SyncResult: ...


def _http(method: str, url: str, **kwargs: Any) -> Any:
    from tutortrack.integrations.providers.http import request

    response = request(method, url, **kwargs)
    return response.json() if response.body else {}


# --- Mailchimp ----------------------------------------------------------------------------------

DC = re.compile(r"^[a-z]{2,4}\d{1,3}$")


def mailchimp_base(api_key: str) -> str:
    """The account's API host from the key's data-centre suffix."""
    key, _, dc = api_key.strip().rpartition("-")
    if not key or not DC.match(dc):
        raise AuthError(
            "That doesn't look like a Mailchimp API key (it ends with -us21 or similar)."
        )
    # The host still goes through ``core.net.safe_urlopen`` (``user_url=True``) on each call.
    return f"https://{dc}.api.mailchimp.com/3.0"


def subscriber_hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode(), usedforsecurity=False).hexdigest()


class MailchimpClient:
    def _call(self, creds: Credentials, method: str, path: str, body: Any = None) -> Any:
        import base64

        auth = base64.b64encode(f"tutortrack:{creds.secret}".encode()).decode()
        return _http(
            method,
            f"{mailchimp_base(creds.secret)}{path}",
            auth_header=f"Basic {auth}",
            json_body=body,
            user_url=True,
            provider="mailchimp",
        )

    def verify(self, creds: Credentials) -> AccountInfo:
        data = self._call(creds, "GET", "/")
        return AccountInfo(str(data.get("account_id", "")), str(data.get("account_name", "")))

    def audiences(self, creds: Credentials) -> list[Audience]:
        data = self._call(creds, "GET", "/lists?count=100&fields=lists.id,lists.name,lists.stats")
        return [
            Audience(
                str(row["id"]),
                str(row.get("name", "")),
                int((row.get("stats") or {}).get("member_count", 0)),
            )
            for row in data.get("lists", [])
        ]

    def upsert(self, creds: Credentials, audience_id: str, members: list[Member]) -> SyncResult:
        result = SyncResult()
        for member in members:
            path = f"/lists/{audience_id}/members/{subscriber_hash(member.email)}"
            try:
                self._call(
                    creds,
                    "PUT",
                    path,
                    {
                        "email_address": member.email,
                        "status_if_new": "subscribed",
                        "status": "subscribed",
                        "merge_fields": {"FNAME": member.first_name, "LNAME": member.last_name},
                    },
                )
                if member.tags:
                    tags = [{"name": t, "status": "active"} for t in member.tags]
                    self._call(creds, "POST", f"{path}/tags", {"tags": tags})
                result.upserted += 1
            except AuthError:
                raise
            except ProviderError as exc:
                result.errors.append(str(exc))
        return result

    def unsubscribe(self, creds: Credentials, audience_id: str, emails: list[str]) -> SyncResult:
        result = SyncResult()
        for email in emails:
            try:
                self._call(
                    creds,
                    "PATCH",
                    f"/lists/{audience_id}/members/{subscriber_hash(email)}",
                    {"status": "unsubscribed"},
                )
                result.unsubscribed += 1
            except registry.NotFound:
                continue  # never subscribed
            except AuthError:
                raise
            except ProviderError as exc:
                result.errors.append(str(exc))
        return result


# --- Brevo --------------------------------------------------------------------------------------

BREVO = "https://api.brevo.com/v3"


class BrevoClient:
    def _call(self, creds: Credentials, method: str, path: str, body: Any = None) -> Any:
        return _http(
            method,
            f"{BREVO}{path}",
            headers={"api-key": creds.secret},
            json_body=body,
            provider="brevo",
        )

    def verify(self, creds: Credentials) -> AccountInfo:
        data = self._call(creds, "GET", "/account")
        return AccountInfo(str(data.get("email", "brevo")), str(data.get("companyName", "")))

    def audiences(self, creds: Credentials) -> list[Audience]:
        data = self._call(creds, "GET", "/contacts/lists?limit=50")
        return [
            Audience(str(row["id"]), str(row.get("name", "")), int(row.get("totalSubscribers", 0)))
            for row in data.get("lists", [])
        ]

    def upsert(self, creds: Credentials, audience_id: str, members: list[Member]) -> SyncResult:
        result = SyncResult()
        for member in members:
            try:
                self._call(
                    creds,
                    "POST",
                    "/contacts",
                    {
                        "email": member.email,
                        "attributes": {
                            "FIRSTNAME": member.first_name,
                            "LASTNAME": member.last_name,
                            "TAGS": ", ".join(member.tags),
                        },
                        "listIds": [int(audience_id)],
                        "updateEnabled": True,
                    },
                )
                result.upserted += 1
            except AuthError:
                raise
            except ProviderError as exc:
                result.errors.append(str(exc))
        return result

    def unsubscribe(self, creds: Credentials, audience_id: str, emails: list[str]) -> SyncResult:
        result = SyncResult()
        try:
            self._call(
                creds,
                "POST",
                f"/contacts/lists/{int(audience_id)}/contacts/remove",
                {"emails": emails},
            )
            result.unsubscribed = len(emails)
        except AuthError:
            raise
        except ProviderError as exc:
            result.errors.append(str(exc))
        return result


# --- fake twin ----------------------------------------------------------------------------------

# account id -> audience id -> email -> member state (also the test handle)
FAKE_AUDIENCES: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}


class FakeMarketingClient:
    def __init__(self, provider: str):
        self.provider = provider

    def _lists(self, creds: Credentials) -> dict[str, dict[str, dict[str, Any]]]:
        account = creds.account_id or f"{self.provider}:account"
        return FAKE_AUDIENCES.setdefault(account, {"aud1": {}, "aud2": {}})

    def verify(self, creds: Credentials) -> AccountInfo:
        if not creds.secret or "wrong" in creds.secret:
            raise AuthError("Those details weren't accepted.")
        return AccountInfo(f"{self.provider}:{creds.secret[-6:]}", f"{self.provider} account")

    def audiences(self, creds: Credentials) -> list[Audience]:
        names = {"aud1": "Families", "aud2": "Newsletter"}
        return [Audience(k, names.get(k, k), len(v)) for k, v in self._lists(creds).items()]

    def upsert(self, creds: Credentials, audience_id: str, members: list[Member]) -> SyncResult:
        audience = self._lists(creds).setdefault(audience_id, {})
        for m in members:
            audience[m.email.lower()] = {
                "status": "subscribed",
                "first_name": m.first_name,
                "last_name": m.last_name,
                "tags": sorted(m.tags),
            }
        return SyncResult(upserted=len(members))

    def unsubscribe(self, creds: Credentials, audience_id: str, emails: list[str]) -> SyncResult:
        audience = self._lists(creds).setdefault(audience_id, {})
        done = 0
        for email in emails:
            if email.lower() in audience:
                audience[email.lower()]["status"] = "unsubscribed"
                done += 1
        return SyncResult(unsubscribed=done)


def client_for(provider: str) -> MarketingClient:
    found: MarketingClient = registry.client(provider, CAPABILITY)
    return found


# --- registration -------------------------------------------------------------------------------


def _live() -> bool:
    return bool(settings.INTEGRATIONS["CREDENTIAL_PROVIDERS_LIVE"])


class _Verifier:
    """The framework's credential check for these providers (their own ``verify``)."""

    def __init__(self, provider: str):
        self.provider = provider

    def verify(self, credentials: Credentials) -> AccountInfo:
        return client_for(self.provider).verify(credentials)


def _register(key: str, label: str, live_client: type) -> None:
    registry.register(
        Provider(
            ProviderSpec(
                key,
                label,
                frozenset({CAPABILITY}),
                "credentials",
                ("organisation",),
                credential_fields=("api_key",),
                manage_permission=MANAGE,
            ),
            live=_live,
            credentials=lambda: _Verifier(key),
            clients={CAPABILITY: live_client},
            fake_clients={CAPABILITY: lambda: FakeMarketingClient(key)},
            health=lambda creds: client_for(key).audiences(creds),
        )
    )


_register("mailchimp", "Mailchimp", MailchimpClient)
_register("brevo", "Brevo", BrevoClient)
