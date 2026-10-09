"""Stripe Connect (FR-11-1/2/3): tenants connect their own Stripe account (Standard) and
charges are direct charges on it, with an optional platform application fee."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings

from tutortrack.core.money import Money

from .base import AccountState, ChargeResult, Intent, MethodDetails, ProviderError, WebhookEvent


def _minor(amount: Money) -> int:
    return amount.to_minor()


def _money(minor: int, currency: str) -> Money:
    return Money.from_minor(int(minor), currency.upper())


def _details(method: Any) -> MethodDetails:
    kind = method["type"]
    if kind == "card":
        card = method["card"]
        return MethodDetails(
            method["id"], kind, card.get("brand", ""), card.get("last4", ""),
            card.get("exp_month"), card.get("exp_year"),
        )  # fmt: skip
    info = method.get(kind) or {}
    return MethodDetails(method["id"], kind, "", info.get("last4", ""), mandate_status="active")


class StripeProvider:
    name = "stripe"

    def __init__(self) -> None:
        self.client = stripe.StripeClient(settings.STRIPE["SECRET_KEY"])
        self.publishable_key = settings.STRIPE["PUBLISHABLE_KEY"]
        self.fee_percent = Decimal(str(settings.STRIPE["APPLICATION_FEE_PERCENT"]))

    @staticmethod
    def _opts(account: str, key: str | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {"stripe_account": account}
        if key:
            opts["idempotency_key"] = key
        return opts

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except stripe.StripeError as exc:
            raise ProviderError(exc.user_message or str(exc)) from exc

    def create_account(self, *, country: str, email: str) -> str:
        account = self._call(
            self.client.accounts.create,
            params={"type": "standard", "country": country, "email": email},
        )
        return str(account.id)

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str:
        link = self._call(
            self.client.account_links.create,
            params={
                "account": account,
                "type": "account_onboarding",
                "return_url": return_url,
                "refresh_url": refresh_url,
            },
        )
        return str(link.url)

    def account_state(self, account: str) -> AccountState:
        data = self._call(self.client.accounts.retrieve, account)
        due = list((data.get("requirements") or {}).get("currently_due") or [])
        return AccountState(
            bool(data.get("charges_enabled")),
            bool(data.get("payouts_enabled")),
            due,
            str(data.get("default_currency") or ""),
        )

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str:
        customer = self._call(
            self.client.customers.create,
            params={"name": name, "email": email or None, "metadata": {"client_id": ref}},
            options=self._opts(account, f"customer-{ref}"),
        )
        return str(customer.id)

    def create_setup_intent(self, account: str, *, customer: str) -> Intent:
        intent = self._call(
            self.client.setup_intents.create,
            params={
                "customer": customer,
                "usage": "off_session",
                "automatic_payment_methods": {"enabled": True},
            },
            options=self._opts(account),
        )
        return Intent(ref=intent.id, client_secret=intent.client_secret, status=intent.status)

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None:
        intent = self._call(
            self.client.setup_intents.retrieve, intent_ref, options=self._opts(account)
        )
        if intent.status != "succeeded" or not intent.payment_method:
            return None
        return self.method_details(account, str(intent.payment_method))

    def method_details(self, account: str, method_ref: str) -> MethodDetails:
        method = self._call(
            self.client.payment_methods.retrieve, method_ref, options=self._opts(account)
        )
        return _details(method)

    def detach_method(self, account: str, method_ref: str) -> None:
        self._call(self.client.payment_methods.detach, method_ref, options=self._opts(account))

    def _fee(self, amount: Money) -> int | None:
        if not self.fee_percent:
            return None
        return int((Decimal(_minor(amount)) * self.fee_percent / 100).to_integral_value())

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
        params: dict[str, Any] = {
            "amount": _minor(amount),
            "currency": amount.currency.lower(),
            "customer": customer,
            "payment_method": method,
            "off_session": True,
            "confirm": True,
            "metadata": metadata,
        }
        if (fee := self._fee(amount)) is not None:
            params["application_fee_amount"] = fee
        try:
            intent = self.client.payment_intents.create(
                params=params,  # type: ignore[arg-type]
                options=self._opts(account, idempotency_key),  # type: ignore[arg-type]
            )
        except stripe.CardError as exc:
            error = exc.error
            code = (error.code if error else None) or "card_declined"
            intent_ref = ""
            if error and error.payment_intent:
                intent_ref = str(error.payment_intent.get("id", ""))
            status = "requires_action" if code == "authentication_required" else "failed"
            return ChargeResult(status, intent_ref, code, exc.user_message or "")
        except stripe.StripeError as exc:
            return ChargeResult("failed", "", exc.code or "error", exc.user_message or "")
        status = {"succeeded": "succeeded", "processing": "processing"}.get(
            intent.status, "requires_action" if intent.status == "requires_action" else "failed"
        )
        return ChargeResult(status, intent.id)

    def create_payment_intent(
        self,
        account: str,
        *,
        amount: Money,
        customer: str | None,
        save_method: bool,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> Intent:
        params: dict[str, Any] = {
            "amount": _minor(amount),
            "currency": amount.currency.lower(),
            "automatic_payment_methods": {"enabled": True},
            "metadata": metadata,
        }
        if customer:
            params["customer"] = customer
        if save_method and customer:
            params["setup_future_usage"] = "off_session"
        if (fee := self._fee(amount)) is not None:
            params["application_fee_amount"] = fee
        intent = self._call(
            self.client.payment_intents.create,
            params=params,
            options=self._opts(account, idempotency_key),
        )
        return self._intent(intent)

    def _intent(self, intent: Any) -> Intent:
        return Intent(
            ref=intent.id,
            client_secret=intent.client_secret or "",
            status=intent.status,
            amount=_money(intent.amount, intent.currency),
            payment_method=str(intent.payment_method or ""),
            metadata=dict(intent.metadata or {}),
        )

    def retrieve_intent(self, account: str, intent_ref: str) -> Intent:
        return self._intent(
            self._call(
                self.client.payment_intents.retrieve, intent_ref, options=self._opts(account)
            )
        )

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        intent = self._call(
            self.client.payment_intents.retrieve,
            payment_ref,
            params={"expand": ["latest_charge.balance_transaction"]},
            options=self._opts(account),
        )
        charge = intent.latest_charge
        txn = getattr(charge, "balance_transaction", None) if charge else None
        if not txn or isinstance(txn, str):
            return None
        return _money(txn.fee, txn.currency)

    def refund(self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str) -> str:
        refund = self._call(
            self.client.refunds.create,
            params={"payment_intent": payment_ref, "amount": _minor(amount)},
            options=self._opts(account, idempotency_key),
        )
        return str(refund.id)

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE["WEBHOOK_SECRET"]
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise ProviderError("Invalid webhook.") from exc
        body = event.to_dict()
        return WebhookEvent(
            id=body["id"],
            type=body["type"],
            account=body.get("account") or "",
            data=body["data"]["object"],
            payload=body,
        )
