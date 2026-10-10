"""Stripe Billing for our own subscription (FR-04-4), behind an interface so development
and tests run against a fake. Unlike ``payments`` (Stripe Connect, on the tenant's own
account), every call here is on the TutorTrack platform account."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from tutortrack.core.money import Money


class GatewayError(Exception):
    """Stripe refused or failed a request (message is safe to show the owner)."""


@dataclass(frozen=True)
class Item:
    price: str
    quantity: int | None = 1  # None: metered (usage-based)


@dataclass(frozen=True)
class RemoteSubscription:
    id: str
    customer: str
    status: str  # trialing | active | past_due | unpaid | canceled | incomplete...
    price_ids: tuple[str, ...]
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


@dataclass(frozen=True)
class Checkout:
    id: str
    url: str


@dataclass(frozen=True)
class CheckoutResult:
    id: str
    complete: bool
    mode: str  # subscription | payment
    customer: str
    subscription: str = ""
    payment_ref: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InvoiceSummary:
    id: str
    number: str
    status: str
    total: Money
    created: datetime
    pdf_url: str = ""
    hosted_url: str = ""


@dataclass(frozen=True)
class CardSummary:
    brand: str
    last4: str
    exp_month: int | None = None
    exp_year: int | None = None


@dataclass(frozen=True)
class ChargeResult:
    paid: bool
    ref: str = ""
    message: str = ""


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    data: dict[str, Any]
    payload: dict[str, Any]


class BillingGateway(Protocol):
    name: str

    def create_customer(
        self, *, name: str, email: str, organisation_id: str, country: str, vat_number: str
    ) -> str: ...

    def checkout_subscription(
        self, *, customer: str, items: list[Item], success_url: str, cancel_url: str,
        trial_end: datetime | None, metadata: dict[str, str],
    ) -> Checkout: ...  # fmt: skip

    def checkout_payment(
        self, *, customer: str, amount: Money, description: str, success_url: str,
        cancel_url: str, metadata: dict[str, str],
    ) -> Checkout: ...  # fmt: skip

    def retrieve_checkout(self, session_id: str) -> CheckoutResult: ...

    def portal_url(self, *, customer: str, return_url: str) -> str: ...

    def retrieve_subscription(self, subscription: str) -> RemoteSubscription: ...

    def update_items(
        self, subscription: str, items: list[Item], *, prorate: bool
    ) -> RemoteSubscription: ...

    def schedule_items(self, subscription: str, items: list[Item]) -> None:
        """Switch to ``items`` at the end of the current period (downgrades)."""
        ...

    def set_cancel_at_period_end(self, subscription: str, cancel: bool) -> RemoteSubscription: ...

    def set_quantity(self, subscription: str, price: str, quantity: int) -> None: ...

    def preview_change(self, subscription: str, items: list[Item]) -> Money | None:
        """What an immediate change would charge now (proration)."""
        ...

    def upcoming_total(self, subscription: str) -> Money | None: ...

    def invoices(self, customer: str) -> list[InvoiceSummary]: ...

    def default_card(self, customer: str) -> CardSummary | None: ...

    def report_usage(
        self, *, event_name: str, customer: str, value: int, identifier: str, timestamp: datetime
    ) -> None: ...

    def charge(
        self, *, customer: str, amount: Money, description: str, idempotency_key: str
    ) -> ChargeResult: ...

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent: ...
