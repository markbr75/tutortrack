"""Stripe Billing on the TutorTrack platform account (FR-04-4): Checkout for the first
subscription, the customer portal for cards and invoices, Stripe Tax, subscription
schedules for period-end downgrades and Billing Meters for revenue share."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

import stripe
from django.conf import settings

from tutortrack.core.money import Money

from .base import (
    CardSummary,
    ChargeResult,
    Checkout,
    CheckoutResult,
    GatewayError,
    InvoiceSummary,
    Item,
    RemoteSubscription,
    WebhookEvent,
)


def _dt(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


def _line(item: Item) -> dict[str, Any]:
    line: dict[str, Any] = {"price": item.price}
    if item.quantity is not None:
        line["quantity"] = item.quantity
    return line


def _remote(sub: Any) -> RemoteSubscription:
    items = sub["items"]["data"]
    # API 2025-03-31+: billing periods live on the subscription items.
    first = items[0] if items else {}
    start = sub.get("current_period_start") or first.get("current_period_start")
    end = sub.get("current_period_end") or first.get("current_period_end")
    return RemoteSubscription(
        id=sub["id"],
        customer=sub["customer"] if isinstance(sub["customer"], str) else sub["customer"]["id"],
        status=sub["status"],
        price_ids=tuple(i["price"]["id"] for i in items),
        current_period_start=_dt(start),
        current_period_end=_dt(end),
        cancel_at_period_end=bool(sub.get("cancel_at_period_end")),
    )


class StripeGateway:
    name = "stripe"

    def __init__(self) -> None:
        self.client = stripe.StripeClient(settings.STRIPE["SECRET_KEY"])
        self.webhook_secret = settings.SUBSCRIPTIONS["STRIPE_WEBHOOK_SECRET"]

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except stripe.StripeError as exc:
            raise GatewayError(exc.user_message or str(exc)) from exc

    def create_customer(
        self, *, name: str, email: str, organisation_id: str, country: str, vat_number: str
    ) -> str:
        customer = self._call(
            self.client.customers.create,
            params={
                "name": name,
                "email": email,
                "address": {"country": country},
                "metadata": {"organisation_id": organisation_id},
            },
            options={"idempotency_key": f"tt-customer-{organisation_id}"},
        )
        if vat_number:
            kind = "gb_vat" if country == "GB" else "eu_vat"
            # An invalid number shouldn't block subscribing; Checkout collects it again.
            with contextlib.suppress(stripe.StripeError):
                tax_id: Any = {"type": kind, "value": vat_number}
                self.client.customers.tax_ids.create(customer["id"], params=tax_id)
        return str(customer["id"])

    def checkout_subscription(
        self, *, customer: str, items: list[Item], success_url: str, cancel_url: str,
        trial_end: datetime | None, metadata: dict[str, str],
    ) -> Checkout:  # fmt: skip
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer,
            "line_items": [_line(i) for i in items],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
            "customer_update": {"address": "auto", "name": "auto"},
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
        }
        if trial_end is not None:
            params["subscription_data"]["trial_end"] = int(trial_end.timestamp())
        session = self._call(self.client.checkout.sessions.create, params=params)
        return Checkout(session["id"], session["url"])

    def checkout_payment(
        self, *, customer: str, amount: Money, description: str, success_url: str,
        cancel_url: str, metadata: dict[str, str],
    ) -> Checkout:  # fmt: skip
        session = self._call(
            self.client.checkout.sessions.create,
            params={
                "mode": "payment",
                "customer": customer,
                "line_items": [{
                    "quantity": 1,
                    "price_data": {
                        "currency": amount.currency.lower(),
                        "unit_amount": amount.to_minor(),
                        "product_data": {"name": description},
                    },
                }],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "automatic_tax": {"enabled": True},
                "metadata": metadata,
                "payment_intent_data": {"setup_future_usage": "off_session"},
            },
        )  # fmt: skip
        return Checkout(session["id"], session["url"])

    def retrieve_checkout(self, session_id: str) -> CheckoutResult:
        s = self._call(self.client.checkout.sessions.retrieve, session_id)
        return CheckoutResult(
            id=s["id"],
            complete=s["status"] == "complete",
            mode=s["mode"],
            customer=s["customer"] or "",
            subscription=s.get("subscription") or "",
            payment_ref=s.get("payment_intent") or "",
            metadata=dict(s.get("metadata") or {}),
        )

    def portal_url(self, *, customer: str, return_url: str) -> str:
        session = self._call(
            self.client.billing_portal.sessions.create,
            params={"customer": customer, "return_url": return_url},
        )
        return str(session["url"])

    def retrieve_subscription(self, subscription: str) -> RemoteSubscription:
        return _remote(self._call(self.client.subscriptions.retrieve, subscription))

    def _item_changes(self, subscription: str, items: list[Item]) -> list[dict[str, Any]]:
        current = self._call(self.client.subscriptions.retrieve, subscription)
        existing = {i["price"]["id"]: i["id"] for i in current["items"]["data"]}
        wanted = {i.price for i in items}
        changes = [
            {**_line(i), **({"id": existing[i.price]} if i.price in existing else {})}
            for i in items
        ]
        for price, item_id in existing.items():
            if price not in wanted:
                changes.append({"id": item_id, "deleted": True})
        for change in changes:
            if "id" in change and "price" in change:
                del change["price"]
        return changes

    def update_items(
        self, subscription: str, items: list[Item], *, prorate: bool
    ) -> RemoteSubscription:
        sub = self._call(
            self.client.subscriptions.update,
            subscription,
            params={
                "items": self._item_changes(subscription, items),
                "proration_behavior": "always_invoice" if prorate else "none",
            },
        )
        return _remote(sub)

    def schedule_items(self, subscription: str, items: list[Item]) -> None:
        sub = self._call(self.client.subscriptions.retrieve, subscription)
        schedule_id = sub.get("schedule")
        if not schedule_id:
            schedule = self._call(
                self.client.subscription_schedules.create,
                params={"from_subscription": subscription},
            )
        else:
            schedule = self._call(self.client.subscription_schedules.retrieve, schedule_id)
        phase = schedule["phases"][0]
        current = [
            {"price": i["price"] if isinstance(i["price"], str) else i["price"]["id"],
             **({"quantity": i["quantity"]} if i.get("quantity") is not None else {})}
            for i in phase["items"]
        ]  # fmt: skip
        self._call(
            self.client.subscription_schedules.update,
            schedule["id"],
            params={
                "end_behavior": "release",
                "phases": [
                    {"items": current, "start_date": phase["start_date"],
                     "end_date": phase["end_date"]},
                    {"items": [_line(i) for i in items], "iterations": 1},
                ],
            },
        )  # fmt: skip

    def set_cancel_at_period_end(self, subscription: str, cancel: bool) -> RemoteSubscription:
        sub = self._call(
            self.client.subscriptions.update,
            subscription,
            params={"cancel_at_period_end": cancel},
        )
        return _remote(sub)

    def set_quantity(self, subscription: str, price: str, quantity: int) -> None:
        current = self._call(self.client.subscriptions.retrieve, subscription)
        for item in current["items"]["data"]:
            if item["price"]["id"] == price:
                self._call(
                    self.client.subscription_items.update,
                    item["id"],
                    params={"quantity": quantity, "proration_behavior": "create_prorations"},
                )
                return

    def preview_change(self, subscription: str, items: list[Item]) -> Money | None:
        sub = self._call(self.client.subscriptions.retrieve, subscription)
        invoice = self._call(
            self.client.invoices.create_preview,
            params={
                "customer": sub["customer"],
                "subscription": subscription,
                "subscription_details": {
                    "items": self._item_changes(subscription, items),
                    "proration_behavior": "always_invoice",
                },
            },
        )
        return Money.from_minor(int(invoice["amount_due"]), str(invoice["currency"]).upper())

    def upcoming_total(self, subscription: str) -> Money | None:
        sub = self._call(self.client.subscriptions.retrieve, subscription)
        try:
            invoice = self.client.invoices.create_preview(
                params={"customer": sub["customer"], "subscription": subscription}
            )
        except stripe.StripeError:
            return None
        return Money.from_minor(int(invoice["total"]), str(invoice["currency"]).upper())

    def invoices(self, customer: str) -> list[InvoiceSummary]:
        result = self._call(self.client.invoices.list, params={"customer": customer, "limit": 24})
        return [
            InvoiceSummary(
                id=i["id"],
                number=i.get("number") or "",
                status=i["status"],
                total=Money.from_minor(int(i["total"]), str(i["currency"]).upper()),
                created=_dt(i["created"]) or datetime.now(UTC),
                pdf_url=i.get("invoice_pdf") or "",
                hosted_url=i.get("hosted_invoice_url") or "",
            )
            for i in result["data"]
        ]

    def default_card(self, customer: str) -> CardSummary | None:
        c = self._call(
            self.client.customers.retrieve,
            customer,
            params={"expand": ["invoice_settings.default_payment_method"]},
        )
        method = (c.get("invoice_settings") or {}).get("default_payment_method")
        if not method or method.get("type") != "card":
            return None
        card = method["card"]
        return CardSummary(card["brand"], card["last4"], card["exp_month"], card["exp_year"])

    def report_usage(
        self, *, event_name: str, customer: str, value: int, identifier: str, timestamp: datetime
    ) -> None:
        self._call(
            self.client.billing.meter_events.create,
            params={
                "event_name": event_name,
                "identifier": identifier,
                "timestamp": int(timestamp.timestamp()),
                "payload": {"stripe_customer_id": customer, "value": str(value)},
            },
        )

    def charge(
        self, *, customer: str, amount: Money, description: str, idempotency_key: str
    ) -> ChargeResult:
        try:
            self.client.invoice_items.create(
                params={
                    "customer": customer,
                    "amount": amount.to_minor(),
                    "currency": amount.currency.lower(),
                    "description": description,
                },
                options={"idempotency_key": f"{idempotency_key}-item"},
            )
            invoice = self.client.invoices.create(
                params={
                    "customer": customer,
                    "collection_method": "charge_automatically",
                    "pending_invoice_items_behavior": "include",
                    "automatic_tax": {"enabled": True},
                },
                options={"idempotency_key": f"{idempotency_key}-invoice"},
            )
            paid = self.client.invoices.pay(
                invoice["id"], options={"idempotency_key": f"{idempotency_key}-pay"}
            )
        except stripe.StripeError as exc:
            return ChargeResult(False, message=exc.user_message or str(exc))
        return ChargeResult(paid["status"] == "paid", ref=paid["id"])

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        try:
            event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise GatewayError("Invalid webhook.") from exc
        body = event.to_dict()
        return WebhookEvent(body["id"], body["type"], body["data"]["object"], body)


__all__ = ["StripeGateway"]
