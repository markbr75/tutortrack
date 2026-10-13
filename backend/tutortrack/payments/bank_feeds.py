"""Open Banking bank feeds (E11-T13) as a provider on the E22 integration framework.

``open_banking`` is GoCardless Bank Account Data (formerly Nordigen): the organisation
connects with its ``secret_id:secret_key`` and the Bank Account Data account id of the
bank account it gave consent for (the consent itself is given in GoCardless's portal).
Transactions are pulled daily by ``BankFeedSyncWorkflow`` (a Temporal Schedule per
connection) or on demand, then matched like an imported statement. Without platform
credentials (tests, development) a fake bank serves sample transactions.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache

from tutortrack.core.time import now
from tutortrack.integrations import providers as registry
from tutortrack.integrations.providers import (
    AccountInfo,
    AuthError,
    Credentials,
    Provider,
    ProviderSpec,
)

from .statements import Parsed, Row

CAPABILITY = "bank_feed"
PROVIDER = "open_banking"
API = "https://bankaccountdata.gocardless.com/api/v2"
FAKE_KEY = "payments:fake-bank:{account}"


class BankDataClient:
    """GoCardless Bank Account Data (real)."""

    def _token(self, credentials: Credentials) -> str:
        from tutortrack.integrations.providers.http import request

        secret_id, _sep, secret_key = credentials.secret.partition(":")
        if not secret_key:
            raise AuthError("Enter the key as secret_id:secret_key.")
        data = request(
            "POST",
            f"{API}/token/new/",
            json_body={"secret_id": secret_id, "secret_key": secret_key},
            provider=PROVIDER,
        ).json()
        return str(data["access"])

    def verify(self, credentials: Credentials) -> AccountInfo:
        from tutortrack.integrations.providers.http import request

        token = self._token(credentials)
        account = credentials.username
        data = request("GET", f"{API}/accounts/{account}/details/", token=token, provider=PROVIDER)
        details = data.json().get("account") or {}
        name = str(details.get("name") or details.get("iban") or account)
        return AccountInfo(f"{PROVIDER}:{account}", name[:255])

    def transactions(self, credentials: Credentials, *, since: date | None = None) -> Parsed:
        from tutortrack.integrations.providers.http import request

        token = self._token(credentials)
        params = {"date_from": since.isoformat()} if since else None
        data = request(
            "GET",
            f"{API}/accounts/{credentials.username}/transactions/",
            token=token,
            params=params,
            provider=PROVIDER,
        ).json()
        return _parsed((data.get("transactions") or {}).get("booked") or [])


def _parsed(items: list[dict[str, Any]]) -> Parsed:
    out = Parsed()
    for item in items:
        amount = item.get("transactionAmount") or {}
        info = item.get("remittanceInformationUnstructured") or " ".join(
            item.get("remittanceInformationUnstructuredArray") or []
        )
        out.rows.append(
            Row(
                booked_on=date.fromisoformat(str(item.get("bookingDate"))[:10]),
                amount=Decimal(str(amount.get("amount", "0"))),
                description=str(info)[:500],
                reference=str(item.get("endToEndId") or info)[:200],
                counterparty=str(item.get("debtorName") or item.get("creditorName") or "")[:200],
                external_id=("ob:" + str(item["transactionId"]))[:120]
                if item.get("transactionId")
                else "",
                currency=str(amount.get("currency") or "").upper(),
            )
        )
    return out


class FakeBank:
    """Sample transactions (or ones a test sets with ``set_transactions``)."""

    def verify(self, credentials: Credentials) -> AccountInfo:
        if not credentials.secret or "wrong" in credentials.secret:
            raise AuthError("Those details weren't accepted.")
        account = credentials.username or "fake-account"
        return AccountInfo(f"{PROVIDER}:{account}", "Business current account")

    def transactions(self, credentials: Credentials, *, since: date | None = None) -> Parsed:
        self.verify(credentials)
        items = cache.get(FAKE_KEY.format(account=credentials.username or "fake-account"))
        if items is None:
            today = now().date()
            items = [
                {"transactionId": "fake-1", "bookingDate": (today - timedelta(days=1)).isoformat(),
                 "transactionAmount": {"amount": "40.00", "currency": "GBP"},
                 "remittanceInformationUnstructured": "TUITION", "debtorName": "A PARENT"},
            ]  # fmt: skip
        return _parsed(items)


def set_transactions(account: str, items: list[dict[str, Any]]) -> None:
    cache.set(FAKE_KEY.format(account=account), items, 60 * 60 * 24)


def _live() -> bool:
    return bool(settings.INTEGRATIONS.get("CREDENTIAL_PROVIDERS_LIVE"))


registry.register(
    Provider(
        ProviderSpec(
            PROVIDER,
            "Open Banking bank feed (GoCardless Bank Account Data)",
            frozenset({CAPABILITY}),
            "credentials",
            ("organisation",),
            credential_fields=("username", "api_key"),
            manage_permission="payments.provider.manage",
        ),
        live=_live,
        credentials=BankDataClient,
        clients={CAPABILITY: BankDataClient},
        fake_clients={CAPABILITY: FakeBank},
        health=lambda creds: registry.client(PROVIDER, CAPABILITY).verify(creds),
    )
)
