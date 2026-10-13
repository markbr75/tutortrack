"""GoCardless (E11-T11): Direct Debit mandates, payments and payouts through the GoCardless
Pro API, with tenants connecting their own creditor account by partner OAuth.

* Mandates are set up on GoCardless's hosted **billing request flow** (redirect) and then
  charged off-session like a saved card: payments start ``pending_submission`` and are
  confirmed (or fail) days later by webhook, so ``charge`` returns ``processing``.
* The pay page uses a billing request with a ``payment_request`` (Instant Bank Pay where
  available, otherwise a one-off debit), finished by ``finish_payment``.
* Fees aren't on the payment: they come with the payout's items (``payout``).
* Webhooks are a batch of events signed with HMAC-SHA256 of the body.

Hosts are constants (no tenant-influenced URLs). Access tokens are stored encrypted on the
``ProviderAccount`` and looked up by its reference.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings

from tutortrack.core.money import Money

from .base import (
    AccountState,
    ChargeResult,
    Connected,
    Intent,
    MethodDetails,
    PayoutInfo,
    ProviderError,
    WebhookEvent,
)

VERSION = "2015-07-06"
SCHEMES = {
    "GBP": "bacs",
    "EUR": "sepa_core",
    "USD": "ach",
    "AUD": "becs",
    "NZD": "becs_nz",
    "CAD": "pad",
    "SEK": "autogiro",
    "DKK": "betalingsservice",
}
METHOD_TYPES = {
    "bacs": "bacs_debit",
    "sepa_core": "sepa_debit",
    "ach": "ach_debit",
    "becs": "becs_debit",
    "becs_nz": "becs_nz_debit",
    "pad": "pad_debit",
    "autogiro": "autogiro_debit",
    "betalingsservice": "betalingsservice_debit",
}


def _hosts() -> tuple[str, str]:
    if settings.GOCARDLESS["ENVIRONMENT"] == "live":
        return "https://api.gocardless.com", "https://connect.gocardless.com"
    return "https://api-sandbox.gocardless.com", "https://connect-sandbox.gocardless.com"


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def parse_events(payload: bytes, signature: str, secret: str) -> list[WebhookEvent]:
    if not secret or not verify_signature(payload, signature, secret):
        raise ProviderError("Invalid webhook signature.")
    try:
        body = json.loads(payload)
    except ValueError as exc:
        raise ProviderError("Invalid webhook body.") from exc
    out = []
    for event in body.get("events") or []:
        links = event.get("links") or {}
        out.append(
            WebhookEvent(
                id=str(event["id"]),
                type=f"{event.get('resource_type')}.{event.get('action')}",
                account=str(links.get("organisation") or ""),
                data=event,
                payload=event,
            )
        )
    return out


def _metadata(values: dict[str, str]) -> dict[str, str]:
    """GoCardless keeps at most three metadata keys of 50 characters."""
    return {k[:50]: str(v)[:500] for k, v in list(values.items())[:3]}


class GoCardlessProvider:
    name = "gocardless"
    saves_methods = True
    publishable_key = ""

    def __init__(self) -> None:
        self.api, self.connect = _hosts()
        config = settings.GOCARDLESS
        self.client_id = config["CLIENT_ID"]
        self.client_secret = config["CLIENT_SECRET"]
        self.webhook_secret = config["WEBHOOK_SECRET"]
        self.fee_percent = Decimal(str(config["APP_FEE_PERCENT"] or "0"))

    # --- plumbing ----------------------------------------------------------------------

    def _token(self, account: str) -> str:
        from ..models import ProviderAccount

        row = ProviderAccount.objects.filter(provider="gocardless", account_ref=account).first()
        if row is None or not row.access_token:
            raise ProviderError("GoCardless isn't connected.")
        return str(row.access_token)

    def _call(
        self,
        method: str,
        path: str,
        account: str,
        body: dict[str, Any] | None = None,
        *,
        key: str = "",
    ) -> dict[str, Any]:
        from tutortrack.integrations.providers import ProviderError as HttpError
        from tutortrack.integrations.providers.http import request

        headers = {"GoCardless-Version": VERSION}
        if key:
            headers["Idempotency-Key"] = key[:128]
        try:
            response = request(
                method,
                f"{self.api}{path}",
                token=self._token(account),
                json_body=body,
                headers=headers,
                provider="gocardless",
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        data: dict[str, Any] = response.json()
        return data

    # --- connection --------------------------------------------------------------------

    def connect_url(self, *, state: str, return_url: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": return_url,
                "scope": "read_write",
                "response_type": "code",
                "state": state,
                "initial_view": "signup",
            }
        )
        return f"{self.connect}/oauth/authorize?{query}"

    def complete_connect(self, *, code: str, return_url: str) -> Connected:
        from tutortrack.integrations.providers import ProviderError as HttpError
        from tutortrack.integrations.providers.http import request

        try:
            response = request(
                "POST",
                f"{self.connect}/oauth/access_token",
                form={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": return_url,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                provider="gocardless",
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        data = response.json()
        return Connected(str(data["organisation_id"]), str(data["access_token"]))

    def account_state(self, account: str) -> AccountState:
        creditors = self._call("GET", "/creditors", account).get("creditors") or []
        creditor = creditors[0] if creditors else {}
        status = str(creditor.get("verification_status") or "action_required")
        currencies = creditor.get("fx_payout_currency") or ""
        return AccountState(
            charges_enabled=status in {"successful", "in_review"},
            payouts_enabled=status == "successful",
            requirements=["verification"] if status == "action_required" else [],
            default_currency=str(currencies or ""),
        )

    # --- customers and mandates --------------------------------------------------------

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str:
        body = {
            "customers": {
                "company_name": name[:100],
                "email": email or None,
                "metadata": {"client_id": ref},
            }
        }
        data = self._call("POST", "/customers", account, body, key=f"customer-{ref}")
        return str(data["customers"]["id"])

    def create_setup_intent(
        self, account: str, *, customer: str, return_url: str = "", currency: str = ""
    ) -> Intent:
        scheme = SCHEMES.get((currency or "GBP").upper(), "bacs")
        request = self._call(
            "POST",
            "/billing_requests",
            account,
            {
                "billing_requests": {
                    "mandate_request": {"scheme": scheme},
                    "links": {"customer": customer},
                }
            },
        )["billing_requests"]
        return self._flow(account, request["id"], return_url)

    def _flow(self, account: str, request_id: str, return_url: str) -> Intent:
        sep = "&" if "?" in return_url else "?"
        back = f"{return_url}{sep}intent={request_id}"
        flow = self._call(
            "POST",
            "/billing_request_flows",
            account,
            {
                "billing_request_flows": {
                    "redirect_uri": back,
                    "exit_uri": back,
                    "links": {"billing_request": request_id},
                }
            },
        )["billing_request_flows"]
        return Intent(
            ref=request_id,
            client_secret="",
            status="redirect",
            redirect_url=str(flow["authorisation_url"]),
        )

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None:
        request = self._call("GET", f"/billing_requests/{intent_ref}", account)["billing_requests"]
        mandate = (request.get("links") or {}).get("mandate_request_mandate")
        if request.get("status") != "fulfilled" or not mandate:
            return None
        return self.method_details(account, str(mandate))

    def method_details(self, account: str, method_ref: str) -> MethodDetails:
        mandate = self._call("GET", f"/mandates/{method_ref}", account)["mandates"]
        last4 = ""
        bank = (mandate.get("links") or {}).get("customer_bank_account")
        if bank:
            info = self._call("GET", f"/customer_bank_accounts/{bank}", account)
            last4 = str(info["customer_bank_accounts"].get("account_number_ending") or "")[-4:]
        return MethodDetails(
            method_ref,
            METHOD_TYPES.get(str(mandate.get("scheme")), "bacs_debit"),
            "",
            last4,
            mandate_status=str(mandate.get("status") or ""),
        )

    def detach_method(self, account: str, method_ref: str) -> None:
        self._call("POST", f"/mandates/{method_ref}/actions/cancel", account, {})

    # --- payments ----------------------------------------------------------------------

    def _app_fee(self, amount: Money) -> int | None:
        if not self.fee_percent:
            return None
        return int((Decimal(amount.to_minor()) * self.fee_percent / 100).to_integral_value())

    def charge(
        self,
        account: str,
        *,
        customer: str,
        method: str,
        amount: Money,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> ChargeResult:
        body: dict[str, Any] = {
            "amount": amount.to_minor(),
            "currency": amount.currency,
            "metadata": _metadata(metadata),
            "links": {"mandate": method},
        }
        if (fee := self._app_fee(amount)) is not None:
            body["app_fee"] = fee
        try:
            data = self._call("POST", "/payments", account, {"payments": body}, key=idempotency_key)
        except ProviderError as exc:
            return ChargeResult("failed", "", "gocardless_error", str(exc)[:300])
        payment = data["payments"]
        if payment.get("status") in {"failed", "cancelled"}:
            return ChargeResult("failed", str(payment["id"]), str(payment["status"]), "")
        return ChargeResult("processing", str(payment["id"]))

    def start_payment(
        self,
        account: str,
        *,
        amount: Money,
        metadata: dict[str, str],
        return_url: str,
        idempotency_key: str,
    ) -> Intent:
        request = self._call(
            "POST",
            "/billing_requests",
            account,
            {
                "billing_requests": {
                    "payment_request": {
                        "amount": amount.to_minor(),
                        "currency": amount.currency,
                        "description": "Invoice payment",
                    },
                    "metadata": _metadata(metadata),
                }
            },
            key=idempotency_key,
        )["billing_requests"]
        flow = self._flow(account, str(request["id"]), return_url)
        return Intent(
            ref=flow.ref,
            client_secret="",
            status="redirect",
            amount=amount,
            metadata=metadata,
            redirect_url=flow.redirect_url,
        )

    def finish_payment(self, account: str, intent_ref: str, *, idempotency_key: str) -> Intent:
        request = self._call("GET", f"/billing_requests/{intent_ref}", account)["billing_requests"]
        payment = (request.get("links") or {}).get("payment_request_payment") or ""
        details = request.get("payment_request") or {}
        amount = (
            Money.from_minor(int(details["amount"]), str(details["currency"]).upper())
            if details.get("amount")
            else None
        )
        status = "processing" if request.get("status") == "fulfilled" and payment else "pending"
        return Intent(
            ref=intent_ref,
            client_secret="",
            status=status,
            amount=amount,
            metadata=dict(request.get("metadata") or {}),
            payment=str(payment),
        )

    def payment_info(self, account: str, payment_ref: str) -> Intent:
        payment = self._call("GET", f"/payments/{payment_ref}", account)["payments"]
        return Intent(
            ref=payment_ref,
            client_secret="",
            status=str(payment.get("status") or ""),
            amount=Money.from_minor(int(payment["amount"]), str(payment["currency"]).upper()),
            metadata=dict(payment.get("metadata") or {}),
            payment=payment_ref,
        )

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        return None  # fees are known when the payout arrives (``payout``)

    def refund(self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str) -> str:
        data = self._call(
            "POST",
            "/refunds",
            account,
            {
                "refunds": {
                    "amount": amount.to_minor(),
                    "links": {"payment": payment_ref},
                    "total_amount_confirmation": amount.to_minor(),
                }
            },
            key=idempotency_key,
        )
        return str(data["refunds"]["id"])

    def payout(self, account: str, payout_ref: str) -> PayoutInfo:
        payout = self._call("GET", f"/payouts/{payout_ref}", account)["payouts"]
        currency = str(payout["currency"]).upper()
        fees: dict[str, Money] = {}
        items = self._call("GET", f"/payout_items?payout={payout_ref}&limit=500", account)
        for item in items.get("payout_items") or []:
            if item.get("type") in {"gocardless_fee", "app_fee"}:
                ref = str((item.get("links") or {}).get("payment") or "")
                fee = Money(-Decimal(str(item["amount"])), currency)
                fees[ref] = fees.get(ref, Money.zero(currency)) + fee
        arrival = payout.get("arrival_date")
        return PayoutInfo(
            amount=Money.from_minor(int(payout["amount"]), currency),
            arrival_date=date.fromisoformat(arrival) if arrival else None,
            status=str(payout.get("status") or "paid"),
            fees=fees,
        )

    def parse_webhooks(self, payload: bytes, headers: dict[str, str]) -> list[WebhookEvent]:
        return parse_events(payload, headers.get("Webhook-Signature", ""), self.webhook_secret)
