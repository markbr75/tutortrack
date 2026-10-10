"""Billing gateway registry: Stripe when keys are configured, a fake otherwise."""

from __future__ import annotations

from functools import cache

from django.conf import settings

from .base import (
    BillingGateway,
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

__all__ = [
    "BillingGateway",
    "CardSummary",
    "ChargeResult",
    "Checkout",
    "CheckoutResult",
    "GatewayError",
    "InvoiceSummary",
    "Item",
    "RemoteSubscription",
    "WebhookEvent",
    "get_gateway",
]


@cache
def get_gateway() -> BillingGateway:
    if settings.STRIPE["SECRET_KEY"]:
        from .stripe import StripeGateway

        return StripeGateway()
    from .fake import FakeGateway

    return FakeGateway()
