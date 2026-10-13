"""The provider-agnostic payment interface (FR-11 §2).

Amounts cross this boundary as ``Money``; providers convert to their own units. Every
call that moves money takes an ``idempotency_key`` derived from our own record ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from tutortrack.core.money import Money


class ProviderError(Exception):
    """The provider refused or failed a request (message is safe to show staff)."""


@dataclass(frozen=True)
class AccountState:
    charges_enabled: bool
    payouts_enabled: bool
    requirements: list[str] = field(default_factory=list)
    default_currency: str = ""


@dataclass(frozen=True)
class MethodDetails:
    ref: str
    type: str
    brand: str = ""
    last4: str = ""
    exp_month: int | None = None
    exp_year: int | None = None
    mandate_status: str = ""


@dataclass(frozen=True)
class ChargeResult:
    """``succeeded``, ``processing`` (debits: confirmed later by webhook),
    ``requires_action`` (the customer must authenticate) or ``failed``."""

    status: str
    ref: str = ""
    failure_code: str = ""
    failure_message: str = ""
    fee: Money | None = None


@dataclass(frozen=True)
class Intent:
    ref: str
    client_secret: str
    status: str = "requires_payment_method"
    amount: Money | None = None
    payment_method: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    # Redirect providers (GoCardless, PayPal): where the customer goes, and the payment the
    # flow created (GoCardless payment / PayPal capture id).
    redirect_url: str = ""
    payment: str = ""


@dataclass(frozen=True)
class Connected:
    """A finished partner connection (GoCardless OAuth, PayPal partner referral)."""

    account_ref: str
    access_token: str = ""
    default_currency: str = ""


@dataclass(frozen=True)
class PayoutInfo:
    amount: Money
    arrival_date: Any = None  # date
    status: str = "paid"
    fees: dict[str, Money] = field(default_factory=dict)  # payment ref -> fee


@dataclass(frozen=True)
class WebhookEvent:
    id: str
    type: str
    account: str
    data: dict[str, Any]
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    name: str
    publishable_key: str

    def create_account(self, *, country: str, email: str) -> str: ...

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str: ...

    def account_state(self, account: str) -> AccountState: ...

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str: ...

    def create_setup_intent(
        self, account: str, *, customer: str, return_url: str = "", currency: str = ""
    ) -> Intent: ...

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None: ...

    def method_details(self, account: str, method_ref: str) -> MethodDetails: ...

    def detach_method(self, account: str, method_ref: str) -> None: ...

    def charge(
        self,
        account: str,
        *,
        customer: str,
        method: str,
        amount: Money,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> ChargeResult: ...

    def create_payment_intent(
        self,
        account: str,
        *,
        amount: Money,
        customer: str | None,
        save_method: bool,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> Intent: ...

    def retrieve_intent(self, account: str, intent_ref: str) -> Intent: ...

    def fee_for(self, account: str, payment_ref: str) -> Money | None: ...

    def refund(
        self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str
    ) -> str: ...

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent: ...


class RedirectProvider(Protocol):
    """GoCardless and PayPal (E11-T11/T12): the customer is redirected to the provider's
    hosted pages to set up a mandate or pay, and comes back to us. Tenants connect by a
    partner flow (OAuth / partner referral). Webhooks arrive in batches."""

    name: str
    saves_methods: bool  # GoCardless mandates can be charged later; PayPal is pay-now only

    def connect_url(self, *, state: str, return_url: str) -> str: ...

    def complete_connect(self, *, code: str, return_url: str) -> Connected: ...

    def account_state(self, account: str) -> AccountState: ...

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str: ...

    def create_setup_intent(
        self, account: str, *, customer: str, return_url: str = "", currency: str = ""
    ) -> Intent: ...

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None: ...

    def method_details(self, account: str, method_ref: str) -> MethodDetails: ...

    def detach_method(self, account: str, method_ref: str) -> None: ...

    def charge(
        self,
        account: str,
        *,
        customer: str,
        method: str,
        amount: Money,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> ChargeResult: ...

    def start_payment(
        self,
        account: str,
        *,
        amount: Money,
        metadata: dict[str, str],
        return_url: str,
        idempotency_key: str,
    ) -> Intent: ...

    def finish_payment(self, account: str, intent_ref: str, *, idempotency_key: str) -> Intent:
        """``succeeded`` (PayPal capture), ``processing`` (a GoCardless payment that a
        webhook confirms later) or the provider's waiting/failed status."""
        ...

    def payment_info(self, account: str, payment_ref: str) -> Intent: ...

    def fee_for(self, account: str, payment_ref: str) -> Money | None: ...

    def refund(
        self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str
    ) -> str: ...

    def payout(self, account: str, payout_ref: str) -> PayoutInfo: ...

    def parse_webhooks(self, payload: bytes, headers: dict[str, str]) -> list[WebhookEvent]: ...
