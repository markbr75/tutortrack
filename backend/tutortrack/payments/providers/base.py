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

    def create_setup_intent(self, account: str, *, customer: str) -> Intent: ...

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
