"""Provider registry. Without a provider's platform keys (development, tests) its fake twin
stands in, so every flow can be exercised end to end.

* ``stripe``: cards and wallets (Payment Element), Stripe debits (``PaymentProvider``).
* ``gocardless``: Direct Debit mandates, payments and payouts (``RedirectProvider``).
* ``paypal``: pay-now PayPal Checkout (``RedirectProvider``).
"""

from __future__ import annotations

from functools import cache
from typing import Any

from django.conf import settings

from .base import (
    AccountState,
    ChargeResult,
    Connected,
    Intent,
    MethodDetails,
    PaymentProvider,
    PayoutInfo,
    ProviderError,
    RedirectProvider,
    WebhookEvent,
)

__all__ = [
    "REDIRECT_PROVIDERS",
    "AccountState",
    "ChargeResult",
    "Connected",
    "Intent",
    "MethodDetails",
    "PaymentProvider",
    "PayoutInfo",
    "ProviderError",
    "RedirectProvider",
    "WebhookEvent",
    "get_provider",
    "redirect_provider",
]

REDIRECT_PROVIDERS = ("gocardless", "paypal")


@cache
def get_provider(name: str = "stripe") -> Any:
    if name == "stripe":
        if settings.STRIPE["SECRET_KEY"]:
            from .stripe import StripeProvider

            return StripeProvider()
        from .fake import FakeProvider

        return FakeProvider()
    if name == "gocardless":
        if settings.GOCARDLESS["CLIENT_ID"]:
            from .gocardless import GoCardlessProvider

            return GoCardlessProvider()
        from .fake_redirect import FakeGoCardless

        return FakeGoCardless()
    if name == "paypal":
        if settings.PAYPAL["CLIENT_ID"]:
            from .paypal import PayPalProvider

            return PayPalProvider()
        from .fake_redirect import FakePayPal

        return FakePayPal()
    raise ProviderError(f"Unknown payment provider {name!r}")


def redirect_provider(name: str) -> RedirectProvider:
    if name not in REDIRECT_PROVIDERS:
        raise ProviderError(f"{name!r} doesn't use hosted redirects")
    provider: RedirectProvider = get_provider(name)
    return provider
