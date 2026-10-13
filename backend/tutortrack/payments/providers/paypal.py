"""PayPal (E11-T12): pay-now through PayPal Checkout (Orders v2) on behalf of the tenant's
own PayPal business account, connected by partner referral.

* The pay page creates an order (``payee.merchant_id`` = the tenant) and redirects to
  PayPal's approval page; on return ``finish_payment`` captures it (``PayPal-Request-Id``
  makes the capture idempotent). The capture id is the payment reference; its fee comes
  from ``seller_receivable_breakdown``.
* No saved methods or auto-pay (vaulting isn't offered): ``saves_methods`` is False.
* Webhooks are verified with PayPal's ``verify-webhook-signature`` API.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.parse
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

HEADERS = (
    "PAYPAL-AUTH-ALGO",
    "PAYPAL-CERT-URL",
    "PAYPAL-TRANSMISSION-ID",
    "PAYPAL-TRANSMISSION-SIG",
    "PAYPAL-TRANSMISSION-TIME",
)


def encode_metadata(values: dict[str, str]) -> str:
    """Orders carry our ids in ``custom_id`` (127 characters)."""
    return urllib.parse.urlencode(values)[:127]


def decode_metadata(value: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(value or ""))


def _amount(value: dict[str, Any]) -> Money:
    return Money(Decimal(str(value["value"])), str(value["currency_code"]).upper())


def webhook_event(body: dict[str, Any]) -> WebhookEvent:
    resource = body.get("resource") or {}
    payee = resource.get("payee") or {}
    return WebhookEvent(
        id=str(body["id"]),
        type=str(body["event_type"]),
        account=str(payee.get("merchant_id") or body.get("merchant_id") or ""),
        data=resource,
        payload=body,
    )


class PayPalProvider:
    name = "paypal"
    saves_methods = False
    publishable_key = ""

    def __init__(self) -> None:
        config = settings.PAYPAL
        live = config["ENVIRONMENT"] == "live"
        self.api = "https://api-m.paypal.com" if live else "https://api-m.sandbox.paypal.com"
        self.client_id = config["CLIENT_ID"]
        self.client_secret = config["CLIENT_SECRET"]
        self.partner = config["PARTNER_MERCHANT_ID"]
        self.webhook_id = config["WEBHOOK_ID"]
        self._token: tuple[str, float] = ("", 0.0)

    def _access_token(self) -> str:
        from tutortrack.integrations.providers import ProviderError as HttpError
        from tutortrack.integrations.providers.http import request

        token, expires = self._token
        if token and expires > time.time() + 60:
            return token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        try:
            response = request(
                "POST",
                f"{self.api}/v1/oauth2/token",
                auth_header=f"Basic {basic}",
                form={"grant_type": "client_credentials"},
                provider="paypal",
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        data = response.json()
        self._token = (str(data["access_token"]), time.time() + int(data.get("expires_in", 300)))
        return self._token[0]

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        merchant: str = "",
        key: str = "",
    ) -> dict[str, Any]:
        from tutortrack.integrations.providers import ProviderError as HttpError
        from tutortrack.integrations.providers.http import request

        headers = {"Prefer": "return=representation"}
        if key:
            headers["PayPal-Request-Id"] = key[:108]
        if merchant:  # act for the tenant's account
            header = base64.b64encode(b'{"alg":"none"}').decode().rstrip("=")
            claims = (
                base64.b64encode(json.dumps({"iss": self.client_id, "payer_id": merchant}).encode())
                .decode()
                .rstrip("=")
            )
            headers["PayPal-Auth-Assertion"] = f"{header}.{claims}."
        try:
            response = request(
                method,
                f"{self.api}{path}",
                token=self._access_token(),
                json_body=body,
                headers=headers,
                provider="paypal",
            )
        except HttpError as exc:
            raise ProviderError(str(exc)) from exc
        data: dict[str, Any] = response.json()
        return data

    # --- connection (partner referrals) --------------------------------------------------

    def connect_url(self, *, state: str, return_url: str) -> str:
        data = self._call(
            "POST",
            "/v2/customer/partner-referrals",
            {
                "tracking_id": state[:127],
                "operations": [
                    {
                        "operation": "API_INTEGRATION",
                        "api_integration_preference": {
                            "rest_api_integration": {
                                "integration_method": "PAYPAL",
                                "integration_type": "THIRD_PARTY",
                                "third_party_details": {
                                    "features": ["PAYMENT", "REFUND", "ACCESS_MERCHANT_INFORMATION"]
                                },
                            }
                        },
                    }
                ],
                "products": ["EXPRESS_CHECKOUT"],
                "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
                "partner_config_override": {"return_url": return_url},
            },
        )
        for link in data.get("links") or []:
            if link.get("rel") == "action_url":
                return str(link["href"])
        raise ProviderError("PayPal didn't return a sign-up link.")

    def complete_connect(self, *, code: str, return_url: str) -> Connected:
        """``code`` is the ``merchantIdInPayPal`` PayPal adds to the return URL."""
        if not code:
            raise ProviderError("PayPal didn't say which account was connected.")
        return Connected(code)

    def account_state(self, account: str) -> AccountState:
        data = self._call(
            "GET", f"/v1/customer/partners/{self.partner}/merchant-integrations/{account}"
        )
        receivable = bool(data.get("payments_receivable"))
        confirmed = bool(data.get("primary_email_confirmed"))
        requirements = [] if confirmed else ["primary_email_confirmed"]
        return AccountState(receivable, receivable, requirements, "")

    # --- unsupported for PayPal (no vaulting) ---------------------------------------------

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str:
        return f"paypal:{ref}"

    def create_setup_intent(
        self, account: str, *, customer: str, return_url: str = "", currency: str = ""
    ) -> Intent:
        raise ProviderError("PayPal can't be saved for automatic payments.")

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None:
        return None

    def method_details(self, account: str, method_ref: str) -> MethodDetails:
        return MethodDetails(method_ref, "paypal")

    def detach_method(self, account: str, method_ref: str) -> None:
        return None

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
        return ChargeResult("failed", "", "not_supported", "PayPal can't be charged automatically.")

    # --- checkout -------------------------------------------------------------------------

    def start_payment(
        self,
        account: str,
        *,
        amount: Money,
        metadata: dict[str, str],
        return_url: str,
        idempotency_key: str,
    ) -> Intent:
        order = self._call(
            "POST",
            "/v2/checkout/orders",
            {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": amount.currency, "value": str(amount.amount)},
                        "payee": {"merchant_id": account},
                        "custom_id": encode_metadata(metadata),
                    }
                ],
                "application_context": {
                    "return_url": return_url,
                    "cancel_url": return_url,
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                },
            },
            key=idempotency_key,
        )
        approve = next(
            (
                str(link["href"])
                for link in order.get("links") or []
                if link.get("rel") in {"approve", "payer-action"}
            ),
            "",
        )
        return Intent(
            ref=str(order["id"]),
            client_secret="",
            status="redirect",
            amount=amount,
            metadata=metadata,
            redirect_url=approve,
        )

    def _capture_intent(
        self, order_id: str, capture: dict[str, Any], unit: dict[str, Any]
    ) -> Intent:
        status = str(capture.get("status") or "").lower()
        return Intent(
            ref=order_id,
            client_secret="",
            status="succeeded"
            if status == "completed"
            else ("processing" if status == "pending" else status),
            amount=_amount(capture["amount"]) if capture.get("amount") else None,
            metadata=decode_metadata(str(unit.get("custom_id") or capture.get("custom_id") or "")),
            payment=str(capture.get("id") or ""),
        )

    def finish_payment(self, account: str, intent_ref: str, *, idempotency_key: str) -> Intent:
        order = self._call("GET", f"/v2/checkout/orders/{intent_ref}")
        if order.get("status") == "APPROVED":
            order = self._call(
                "POST", f"/v2/checkout/orders/{intent_ref}/capture", {}, key=idempotency_key
            )
        units = order.get("purchase_units") or [{}]
        captures = ((units[0].get("payments") or {}).get("captures")) or []
        if not captures:
            return Intent(
                ref=intent_ref, client_secret="", status=str(order.get("status", "")).lower()
            )
        return self._capture_intent(intent_ref, captures[0], units[0])

    def payment_info(self, account: str, payment_ref: str) -> Intent:
        capture = self._call("GET", f"/v2/payments/captures/{payment_ref}", merchant=account)
        return self._capture_intent("", capture, {})

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        capture = self._call("GET", f"/v2/payments/captures/{payment_ref}", merchant=account)
        breakdown = capture.get("seller_receivable_breakdown") or {}
        fee = breakdown.get("paypal_fee")
        return _amount(fee) if fee else None

    def refund(self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str) -> str:
        data = self._call(
            "POST",
            f"/v2/payments/captures/{payment_ref}/refund",
            {"amount": {"currency_code": amount.currency, "value": str(amount.amount)}},
            merchant=account,
            key=idempotency_key,
        )
        return str(data["id"])

    def payout(self, account: str, payout_ref: str) -> PayoutInfo:
        raise ProviderError("PayPal balances are withdrawn in PayPal.")

    def parse_webhooks(self, payload: bytes, headers: dict[str, str]) -> list[WebhookEvent]:
        try:
            body = json.loads(payload)
        except ValueError as exc:
            raise ProviderError("Invalid webhook body.") from exc
        values = {h: headers.get(h, "") for h in HEADERS}
        if not self.webhook_id or not all(values.values()):
            raise ProviderError("Invalid webhook signature.")
        result = self._call(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            {
                "auth_algo": values["PAYPAL-AUTH-ALGO"],
                "cert_url": values["PAYPAL-CERT-URL"],
                "transmission_id": values["PAYPAL-TRANSMISSION-ID"],
                "transmission_sig": values["PAYPAL-TRANSMISSION-SIG"],
                "transmission_time": values["PAYPAL-TRANSMISSION-TIME"],
                "webhook_id": self.webhook_id,
                "webhook_event": body,
            },
        )
        if result.get("verification_status") != "SUCCESS":
            raise ProviderError("Invalid webhook signature.")
        return [webhook_event(body)]


def new_tracking_id() -> str:
    return secrets.token_urlsafe(18)
