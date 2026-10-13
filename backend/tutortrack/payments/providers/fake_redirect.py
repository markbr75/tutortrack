"""In-memory GoCardless and PayPal for tests and development without partner keys.

Hosted pages are simulated by sending the customer straight back to our return URL with
what the provider would add (``intent=`` for GoCardless flows, ``token=`` for PayPal
orders, ``code=``/``merchantIdInPayPal=`` for connecting), so every flow works end to end.
A mandate or payment whose reference contains ``fail`` is declined. GoCardless webhooks
are really HMAC-signed (with ``fake-gocardless-secret`` unless a secret is configured);
PayPal webhooks need the header ``PAYPAL-TRANSMISSION-SIG: fake-signature``.
"""

from __future__ import annotations

import json
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

FAKE_GC_SECRET = "fake-gocardless-secret"  # noqa: S105 - the fake only


def _back(url: str, **params: str) -> str:
    from urllib.parse import urlencode

    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


class _Base:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.flows: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:06d}"

    def account_state(self, account: str) -> AccountState:
        return AccountState(True, True, [], "")

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str:
        return self._id("CU_fake")

    def refund(self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str) -> str:
        self.calls.append(("refund", {"payment": payment_ref, "amount": str(amount.amount)}))
        return f"RF_{idempotency_key[-12:]}"

    def payment_info(self, account: str, payment_ref: str) -> Intent:
        info = self.payments.get(payment_ref)
        if info is None:
            raise ProviderError("No such payment.")
        return Intent(
            ref=payment_ref,
            client_secret="",
            status=str(info.get("status", "")),
            amount=info["amount"],
            metadata=dict(info.get("metadata") or {}),
            payment=payment_ref,
        )


class FakeGoCardless(_Base):
    name = "gocardless"
    saves_methods = True
    publishable_key = ""

    def __init__(self) -> None:
        super().__init__()
        self.payouts: dict[str, PayoutInfo] = {}

    def connect_url(self, *, state: str, return_url: str) -> str:
        return _back(return_url, code=self._id("fake-code-"), state=state)

    def complete_connect(self, *, code: str, return_url: str) -> Connected:
        if not code or "bad" in code:
            raise ProviderError("The authorisation code was refused.")
        return Connected(self._id("OR_fake"), f"gc-token-{code}", "GBP")

    def create_setup_intent(
        self, account: str, *, customer: str, return_url: str = "", currency: str = ""
    ) -> Intent:
        ref = self._id("BRQ_fake")
        self.flows[ref] = {"kind": "mandate", "customer": customer, "currency": currency}
        return Intent(ref, "", "redirect", redirect_url=_back(return_url, intent=ref))

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None:
        flow = self.flows.get(intent_ref)
        if flow is None:
            return None
        flow.setdefault("mandate", self._id("MD_fake"))
        return self.method_details(account, str(flow["mandate"]))

    def method_details(self, account: str, method_ref: str) -> MethodDetails:
        kind = "sepa_debit" if "sepa" in method_ref else "bacs_debit"
        return MethodDetails(method_ref, kind, "", "1234", mandate_status="active")

    def detach_method(self, account: str, method_ref: str) -> None:
        self.calls.append(("cancel_mandate", {"mandate": method_ref}))

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
        for ref, info in self.payments.items():
            if info.get("key") == idempotency_key:
                return ChargeResult("processing", ref)
        self.calls.append(("charge", {"mandate": method, "amount": str(amount.amount)}))
        if "fail" in method:
            return ChargeResult("failed", "", "mandate_cancelled", "The mandate isn't active.")
        ref = self._id("PM_fake")
        self.payments[ref] = {
            "amount": amount,
            "metadata": metadata,
            "status": "pending_submission",
            "key": idempotency_key,
        }
        return ChargeResult("processing", ref)

    def start_payment(
        self,
        account: str,
        *,
        amount: Money,
        metadata: dict[str, str],
        return_url: str,
        idempotency_key: str,
    ) -> Intent:
        ref = self._id("BRQ_fake")
        self.flows[ref] = {"kind": "payment", "amount": amount, "metadata": metadata}
        return Intent(
            ref,
            "",
            "redirect",
            amount=amount,
            metadata=metadata,
            redirect_url=_back(return_url, intent=ref),
        )

    def finish_payment(self, account: str, intent_ref: str, *, idempotency_key: str) -> Intent:
        flow = self.flows.get(intent_ref)
        if flow is None or flow.get("kind") != "payment":
            raise ProviderError("No such payment.")
        if "payment" not in flow:
            flow["payment"] = self._id("PM_fake")
            self.payments[flow["payment"]] = {
                "amount": flow["amount"],
                "metadata": flow["metadata"],
                "status": "pending_submission",
            }
        return Intent(
            intent_ref,
            "",
            "processing",
            amount=flow["amount"],
            metadata=flow["metadata"],
            payment=flow["payment"],
        )

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        return None

    def fee_of(self, amount: Money) -> Money:
        """GoCardless's standard 1% + 20p (capped at £4) for fake payouts."""
        fee = Money.from_minor(amount.to_minor() // 100 + 20, amount.currency)
        return min(fee, Money.from_minor(400, amount.currency))

    def payout(self, account: str, payout_ref: str) -> PayoutInfo:
        if payout_ref in self.payouts:
            return self.payouts[payout_ref]
        raise ProviderError("No such payout.")

    def add_payout(self, ref: str, payment_refs: list[str], currency: str = "GBP") -> PayoutInfo:
        """Test helper: a payout of these payments less their fees."""
        fees = {p: self.fee_of(self.payments[p]["amount"]) for p in payment_refs}
        gross = sum((self.payments[p]["amount"] for p in payment_refs), Money.zero(currency))
        net = gross - sum(fees.values(), Money.zero(currency))
        info = PayoutInfo(amount=net, fees=fees)
        self.payouts[ref] = info
        return info

    def parse_webhooks(self, payload: bytes, headers: dict[str, str]) -> list[WebhookEvent]:
        from .gocardless import parse_events

        secret = settings.GOCARDLESS["WEBHOOK_SECRET"] or FAKE_GC_SECRET
        return parse_events(payload, headers.get("Webhook-Signature", ""), secret)


class FakePayPal(_Base):
    name = "paypal"
    saves_methods = False
    publishable_key = ""

    def connect_url(self, *, state: str, return_url: str) -> str:
        return _back(
            return_url,
            merchantIdInPayPal=self._id("FAKEMERCHANT"),
            state=state,
            permissionsGranted="true",
        )

    def complete_connect(self, *, code: str, return_url: str) -> Connected:
        if not code:
            raise ProviderError("PayPal didn't say which account was connected.")
        return Connected(code)

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

    def start_payment(
        self,
        account: str,
        *,
        amount: Money,
        metadata: dict[str, str],
        return_url: str,
        idempotency_key: str,
    ) -> Intent:
        ref = self._id("ORDER")
        self.flows[ref] = {"amount": amount, "metadata": metadata}
        return Intent(
            ref,
            "",
            "redirect",
            amount=amount,
            metadata=metadata,
            redirect_url=_back(return_url, token=ref, PayerID="FAKEPAYER"),
        )

    def finish_payment(self, account: str, intent_ref: str, *, idempotency_key: str) -> Intent:
        flow = self.flows.get(intent_ref)
        if flow is None:
            raise ProviderError("No such order.")
        if "capture" not in flow:
            flow["capture"] = self._id("CAP")
            self.payments[flow["capture"]] = {
                "amount": flow["amount"],
                "metadata": flow["metadata"],
                "status": "completed",
            }
        return Intent(
            intent_ref,
            "",
            "succeeded",
            amount=flow["amount"],
            metadata=flow["metadata"],
            payment=flow["capture"],
        )

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        info = self.payments.get(payment_ref)
        if info is None:
            return None
        amount: Money = info["amount"]
        return Money.from_minor(amount.to_minor() * 29 // 1000 + 30, amount.currency)

    def payout(self, account: str, payout_ref: str) -> PayoutInfo:
        raise ProviderError("PayPal balances are withdrawn in PayPal.")

    def parse_webhooks(self, payload: bytes, headers: dict[str, str]) -> list[WebhookEvent]:
        from .paypal import webhook_event

        if headers.get("PAYPAL-TRANSMISSION-SIG") != "fake-signature":
            raise ProviderError("Invalid webhook signature.")
        return [webhook_event(json.loads(payload))]
