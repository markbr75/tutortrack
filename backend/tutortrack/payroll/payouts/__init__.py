"""Payout providers (FR-12-7). Stripe Connect Express when Stripe keys are configured and
``PAYROLL_STRIPE_PAYOUTS`` is on; a fake otherwise (development and tests)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Protocol

from django.conf import settings

from tutortrack.core.money import Money


class PayoutError(Exception):
    """The provider refused (message is safe to show staff)."""


@dataclass(frozen=True)
class TransferResult:
    status: str  # paid | processing | failed
    ref: str = ""
    message: str = ""


class PayoutProvider(Protocol):
    name: str

    def create_account(self, *, email: str, country: str, ref: str) -> str: ...

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str: ...

    def payouts_enabled(self, account: str) -> bool: ...

    def transfer(
        self, account: str, *, amount: Money, description: str, idempotency_key: str
    ) -> TransferResult: ...


@cache
def get_provider() -> PayoutProvider:
    if settings.STRIPE["SECRET_KEY"] and getattr(settings, "PAYROLL_STRIPE_PAYOUTS", False):
        from .stripe import StripeExpressPayouts

        return StripeExpressPayouts()
    from .fake import FakePayouts

    return FakePayouts()
