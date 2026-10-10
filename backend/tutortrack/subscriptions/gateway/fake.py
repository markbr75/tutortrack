"""An in-memory stand-in for Stripe Billing (development and tests): checkouts complete
as soon as they are retrieved, charges succeed unless ``fail_charges`` is set."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from urllib.parse import quote

from tutortrack.core.money import Money
from tutortrack.core.time import now

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


def _id(prefix: str) -> str:
    return f"{prefix}_fake_{uuid.uuid4().hex[:16]}"


def _price_amount(ref: str) -> Money | None:
    from ..services import price_for_ref

    price = price_for_ref(ref)
    if price is None or price.component == "revenue_share":
        return None
    return Money(price.unit_amount, price.currency)


class FakeGateway:
    name = "fake"
    fail_charges: ClassVar[bool] = False
    customers: ClassVar[dict[str, dict[str, Any]]] = {}
    sessions: ClassVar[dict[str, dict[str, Any]]] = {}
    subscriptions: ClassVar[dict[str, dict[str, Any]]] = {}
    usage: ClassVar[list[dict[str, Any]]] = []
    ledger: ClassVar[dict[str, list[InvoiceSummary]]] = {}

    def create_customer(
        self, *, name: str, email: str, organisation_id: str, country: str, vat_number: str
    ) -> str:
        ref = _id("cus")
        self.customers[ref] = {"name": name, "email": email, "organisation_id": organisation_id}
        return ref

    def _session(self, kind: str, success_url: str, **data: Any) -> Checkout:
        ref = _id("cs")
        self.sessions[ref] = {"mode": kind, **data}
        return Checkout(ref, success_url.replace("{CHECKOUT_SESSION_ID}", quote(ref)))

    def checkout_subscription(
        self, *, customer: str, items: list[Item], success_url: str, cancel_url: str,
        trial_end: datetime | None, metadata: dict[str, str],
    ) -> Checkout:  # fmt: skip
        return self._session(
            "subscription", success_url, customer=customer, items=items, trial_end=trial_end,
            metadata=metadata,
        )  # fmt: skip

    def checkout_payment(
        self, *, customer: str, amount: Money, description: str, success_url: str,
        cancel_url: str, metadata: dict[str, str],
    ) -> Checkout:  # fmt: skip
        return self._session(
            "payment", success_url, customer=customer, amount=amount, metadata=metadata
        )

    def retrieve_checkout(self, session_id: str) -> CheckoutResult:
        session = self.sessions.get(session_id)
        if session is None:
            raise GatewayError("Unknown checkout session.")
        if session["mode"] == "payment":
            session.setdefault("payment_ref", _id("pi"))
            return CheckoutResult(session_id, True, "payment", session["customer"],
                                  payment_ref=session["payment_ref"],
                                  metadata=session["metadata"])  # fmt: skip
        if "subscription" not in session:
            sub = self.create_subscription(
                session["customer"], session["items"], trial_end=session["trial_end"]
            )
            session["subscription"] = sub.id
        return CheckoutResult(session_id, True, "subscription", session["customer"],
                              subscription=session["subscription"],
                              metadata=session["metadata"])  # fmt: skip

    def create_subscription(
        self, customer: str, items: list[Item], *, trial_end: datetime | None = None,
        interval_days: int = 30,
    ) -> RemoteSubscription:  # fmt: skip
        ref = _id("sub")
        start = now()
        self.subscriptions[ref] = {
            "customer": customer,
            "status": "trialing" if trial_end else "active",
            "items": {i.price: i.quantity for i in items},
            "start": start,
            "end": trial_end or start + timedelta(days=interval_days),
            "cancel": False,
            "scheduled": None,
        }
        self.customers.setdefault(customer, {})["card"] = CardSummary("visa", "4242", 12, 2030)
        return self.retrieve_subscription(ref)

    def portal_url(self, *, customer: str, return_url: str) -> str:
        return return_url

    def retrieve_subscription(self, subscription: str) -> RemoteSubscription:
        sub = self.subscriptions.get(subscription)
        if sub is None:
            raise GatewayError("Unknown subscription.")
        return RemoteSubscription(
            subscription, sub["customer"], sub["status"], tuple(sub["items"]), sub["start"],
            sub["end"], sub["cancel"],
        )  # fmt: skip

    def update_items(
        self, subscription: str, items: list[Item], *, prorate: bool
    ) -> RemoteSubscription:
        self.subscriptions[subscription]["items"] = {i.price: i.quantity for i in items}
        return self.retrieve_subscription(subscription)

    def schedule_items(self, subscription: str, items: list[Item]) -> None:
        self.subscriptions[subscription]["scheduled"] = {i.price: i.quantity for i in items}

    def set_cancel_at_period_end(self, subscription: str, cancel: bool) -> RemoteSubscription:
        self.subscriptions[subscription]["cancel"] = cancel
        return self.retrieve_subscription(subscription)

    def set_quantity(self, subscription: str, price: str, quantity: int) -> None:
        self.subscriptions[subscription]["items"][price] = quantity

    def _total(self, items: dict[str, int | None]) -> Money | None:
        total: Money | None = None
        for ref, quantity in items.items():
            amount = _price_amount(ref)
            if amount is None:
                continue
            line = amount * Decimal(quantity or 0)
            total = line if total is None else total + line
        return total

    def preview_change(self, subscription: str, items: list[Item]) -> Money | None:
        sub = self.subscriptions[subscription]
        new = self._total({i.price: i.quantity for i in items})
        old = self._total(sub["items"])
        if new is None:
            return None
        if old is None or new.currency != old.currency:
            return new
        left = max(sub["end"] - now(), timedelta(0)) / max(sub["end"] - sub["start"], timedelta(1))
        diff = ((new - old) * Decimal(str(round(left, 4)))).round_to_minor()
        return diff if diff.amount > 0 else Money.zero(new.currency)

    def upcoming_total(self, subscription: str) -> Money | None:
        sub = self.subscriptions.get(subscription)
        return self._total(sub["scheduled"] or sub["items"]) if sub else None

    def invoices(self, customer: str) -> list[InvoiceSummary]:
        return list(self.ledger.get(customer, []))

    def default_card(self, customer: str) -> CardSummary | None:
        card = self.customers.get(customer, {}).get("card")
        return card if isinstance(card, CardSummary) else None

    def report_usage(
        self, *, event_name: str, customer: str, value: int, identifier: str, timestamp: datetime
    ) -> None:
        if any(u["identifier"] == identifier for u in self.usage):
            return
        self.usage.append({"event_name": event_name, "customer": customer, "value": value,
                           "identifier": identifier, "timestamp": timestamp})  # fmt: skip

    def charge(
        self, *, customer: str, amount: Money, description: str, idempotency_key: str
    ) -> ChargeResult:
        if self.fail_charges:
            return ChargeResult(False, message="Your card was declined.")
        invoices = self.ledger.setdefault(customer, [])
        ref = f"in_fake_{idempotency_key}"
        if not any(i.id == ref for i in invoices):
            invoices.append(
                InvoiceSummary(ref, f"TT-{len(invoices) + 1:04d}", "paid", amount, now())
            )
        return ChargeResult(True, ref=ref)

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        if signature != "fake-signature":
            raise GatewayError("Invalid signature.")
        body = json.loads(payload)
        return WebhookEvent(body["id"], body["type"], body["data"]["object"], body)
