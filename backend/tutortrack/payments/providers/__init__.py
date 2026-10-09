"""Provider registry. Without Stripe keys (development, tests) a fake provider stands in,
so every flow can be exercised end to end."""

from __future__ import annotations

from functools import cache

from django.conf import settings

from .base import (
    AccountState,
    ChargeResult,
    Intent,
    MethodDetails,
    PaymentProvider,
    ProviderError,
    WebhookEvent,
)

__all__ = [
    "AccountState",
    "ChargeResult",
    "Intent",
    "MethodDetails",
    "PaymentProvider",
    "ProviderError",
    "WebhookEvent",
    "get_provider",
]


@cache
def get_provider(name: str = "stripe") -> PaymentProvider:
    if name != "stripe":
        raise ProviderError(f"Unknown payment provider {name!r}")
    if settings.STRIPE["SECRET_KEY"]:
        from .stripe import StripeProvider

        return StripeProvider()
    from .fake import FakeProvider

    return FakeProvider()
