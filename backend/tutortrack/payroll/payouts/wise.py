"""Wise Business payouts (E12-T12, FR-12-7 "Wise Business API").

The organisation connects its own Wise Business account with a personal API token
(integration framework, ``provider="wise"``; the token is stored encrypted on the
``IntegrationConnection`` and the business profile id is its account id). Tutors are paid
from the organisation's Wise balance in their own currency:

1. ``ensure_recipient``: a recipient account from the tutor's validated bank details
   (UK sort code, IBAN, US ACH, AU BSB), re-created when the details change;
2. ``transfer``: a quote (source = the balance currency, target = the payout amount), a
   transfer with ``customerTransactionId`` = our idempotency key (a retried create after a
   lost response returns the same transfer), then funding from the balance;
3. ``status``: Wise transfer states mapped to ``paid | processing | failed``.

Every call goes through ``core.net.safe_urlopen`` (``user_url=True``). Webhooks
(``transfers#state-change``) are signed by Wise with RSA-SHA256 (``X-Signature-SHA256``,
base64) and checked against Wise's public key (``WISE["WEBHOOK_PUBLIC_KEY"]``).
"""

from __future__ import annotations

import base64
import uuid
from typing import Any, Protocol

from django.conf import settings

from tutortrack.core.money import Money
from tutortrack.integrations.providers import Credentials, ProviderError, http

from . import TransferResult

PAID_STATES = {"outgoing_payment_sent"}
FAILED_STATES = {"funds_refunded", "bounced_back", "cancelled", "charged_back"}


def map_state(state: str) -> str:
    if state in PAID_STATES:
        return "paid"
    if state in FAILED_STATES:
        return "failed"
    return "processing"


class WiseClient(Protocol):
    provider: str

    def ensure_recipient(
        self,
        creds: Credentials,
        *,
        currency: str,
        name: str,
        country: str,
        details: dict[str, str],
        ref: str,
    ) -> str: ...

    def transfer(
        self,
        creds: Credentials,
        recipient: str,
        *,
        amount: Money,
        source_currency: str,
        reference: str,
        idempotency_key: str,
    ) -> TransferResult: ...

    def status(self, creds: Credentials, transfer_id: str) -> TransferResult: ...


def api_base() -> str:
    return str(settings.WISE["API_URL"]).rstrip("/")


def recipient_body(
    *, currency: str, name: str, country: str, details: dict[str, str], profile: str
) -> dict[str, Any]:
    """Wise ``/v1/accounts`` body from our bank detail shapes (``payroll.banking``)."""
    body: dict[str, Any] = {
        "currency": currency,
        "profile": profile,
        "accountHolderName": name,
        "ownedByCustomer": False,
    }
    if details.get("sort_code"):
        body["type"] = "sort_code"
        body["details"] = {
            "legalType": "PRIVATE",
            "sortCode": details["sort_code"],
            "accountNumber": details.get("account_number", ""),
        }
    elif details.get("iban"):
        body["type"] = "iban"
        body["details"] = {"legalType": "PRIVATE", "IBAN": details["iban"]}
        if details.get("bic"):
            body["details"]["BIC"] = details["bic"]
    elif details.get("routing_number"):
        body["type"] = "aba"
        body["details"] = {
            "legalType": "PRIVATE",
            "abartn": details["routing_number"],
            "accountNumber": details.get("account_number", ""),
            "accountType": (details.get("account_type") or "checking").upper(),
            "address": {"country": country or "US"},
        }
    elif details.get("bsb"):
        body["type"] = "australian"
        body["details"] = {
            "legalType": "PRIVATE",
            "bsbCode": details["bsb"],
            "accountNumber": details.get("account_number", ""),
        }
    else:
        raise ProviderError("Wise needs a sort code, IBAN, US routing number or BSB.")
    return body


class WiseApi:
    provider = "wise"

    def _call(self, creds: Credentials, method: str, path: str, body: Any = None) -> Any:
        return http.request(
            method,
            f"{api_base()}{path}",
            token=creds.secret,
            json_body=body,
            user_url=True,
            provider="wise",
        ).json()

    def verify(self, credentials: Credentials) -> Any:
        """The business profile the token belongs to (its id is the connection's account)."""
        from tutortrack.integrations.providers import AccountInfo

        profiles = self._call(credentials, "GET", "/v2/profiles") or []
        business = next((p for p in profiles if p.get("type") == "BUSINESS"), None)
        if business is None:
            raise ProviderError("This Wise token has no business profile.")
        name = (business.get("details") or {}).get("name") or business.get("fullName") or ""
        return AccountInfo(str(business["id"]), str(name))

    def ensure_recipient(
        self,
        creds: Credentials,
        *,
        currency: str,
        name: str,
        country: str,
        details: dict[str, str],
        ref: str,
    ) -> str:
        body = recipient_body(
            currency=currency,
            name=name,
            country=country,
            details=details,
            profile=creds.account_id,
        )
        created = self._call(creds, "POST", "/v1/accounts", body)
        return str(created["id"])

    def transfer(
        self,
        creds: Credentials,
        recipient: str,
        *,
        amount: Money,
        source_currency: str,
        reference: str,
        idempotency_key: str,
    ) -> TransferResult:
        quote = self._call(
            creds,
            "POST",
            f"/v3/profiles/{creds.account_id}/quotes",
            {
                "sourceCurrency": source_currency,
                "targetCurrency": amount.currency,
                "targetAmount": str(amount.amount),  # a decimal string, never a float
                "targetAccount": int(recipient) if recipient.isdigit() else recipient,
                "payOut": "BANK_TRANSFER",
            },
        )
        transfer = self._call(
            creds,
            "POST",
            "/v1/transfers",
            {
                "targetAccount": int(recipient) if recipient.isdigit() else recipient,
                "quoteUuid": quote["id"],
                "customerTransactionId": str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key)),
                "details": {"reference": reference[:18]},
            },
        )
        transfer_id = str(transfer["id"])
        funded = self._call(
            creds,
            "POST",
            f"/v3/profiles/{creds.account_id}/transfers/{transfer_id}/payments",
            {"type": "BALANCE"},
        )
        if str(funded.get("status", "")).upper() == "REJECTED":
            return TransferResult(
                "failed", ref=transfer_id, message=str(funded.get("errorCode") or "rejected")
            )
        return TransferResult(map_state(str(transfer.get("status", ""))), ref=transfer_id)

    def status(self, creds: Credentials, transfer_id: str) -> TransferResult:
        transfer = self._call(creds, "GET", f"/v1/transfers/{transfer_id}")
        state = str(transfer.get("status", ""))
        return TransferResult(map_state(state), ref=transfer_id, message=state)


def verify_signature(body: bytes, signature: str, public_key_pem: str | None = None) -> bool:
    """Wise webhooks: base64 RSA-SHA256 (PKCS#1 v1.5) over the raw body."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    pem = public_key_pem if public_key_pem is not None else settings.WISE["WEBHOOK_PUBLIC_KEY"]
    if not pem or not signature:
        return False
    try:
        key = serialization.load_pem_public_key(pem.encode())
        if not isinstance(key, rsa.RSAPublicKey):
            return False
        key.verify(base64.b64decode(signature), body, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True
