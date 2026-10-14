"""Payout providers (FR-12-7). Stripe Connect Express when Stripe keys are configured and
``PAYROLL_STRIPE_PAYOUTS`` is on; a fake otherwise (development and tests)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

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


def wise_client() -> Any:
    """The Wise client (E12-T12): the real API when credential providers are live, the
    in-memory fake otherwise (development and tests)."""
    from tutortrack.integrations import providers as registry

    found = registry.client("wise", "payouts")
    return found


def _register_wise() -> None:
    from tutortrack.integrations import providers as registry
    from tutortrack.integrations.providers import Provider, ProviderSpec

    def live() -> bool:
        return bool(settings.INTEGRATIONS["CREDENTIAL_PROVIDERS_LIVE"])

    def real() -> Any:
        from .wise import WiseApi

        return WiseApi()

    def fake() -> Any:
        from .wise_fake import FakeWise

        return FakeWise()

    registry.register(
        Provider(
            ProviderSpec(
                "wise",
                "Wise Business",
                frozenset({"payouts"}),
                "credentials",
                ("organisation",),
                credential_fields=("api_key",),
                manage_permission="payroll.payrun.pay",
            ),
            live=live,
            credentials=real,
            clients={"payouts": real},
            fake_clients={"payouts": fake},
        )
    )


_register_wise()


@cache
def get_provider() -> PayoutProvider:
    if settings.STRIPE["SECRET_KEY"] and getattr(settings, "PAYROLL_STRIPE_PAYOUTS", False):
        from .stripe import StripeExpressPayouts

        return StripeExpressPayouts()
    from .fake import FakePayouts

    return FakePayouts()
