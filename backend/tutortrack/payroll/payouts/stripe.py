"""Stripe Connect Express payouts. Tutors onboard through Stripe-hosted KYC; transfers move
funds from the platform balance to their account. This needs the organisation's Stripe
setup to act as a Connect platform for its tutors (see E12 implementation notes)."""

from __future__ import annotations

from typing import Any

import stripe
from django.conf import settings

from tutortrack.core.money import Money

from . import PayoutError, TransferResult


class StripeExpressPayouts:
    name = "stripe"

    def __init__(self) -> None:
        self.client = stripe.StripeClient(settings.STRIPE["SECRET_KEY"])

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except stripe.StripeError as exc:
            raise PayoutError(exc.user_message or str(exc)) from exc

    def create_account(self, *, email: str, country: str, ref: str) -> str:
        account = self._call(
            self.client.accounts.create,
            params={
                "type": "express",
                "country": country,
                "email": email,
                "capabilities": {"transfers": {"requested": True}},
                "metadata": {"tutor": ref},
            },
            options={"idempotency_key": f"tt-express-{ref}"},
        )
        return str(account["id"])

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str:
        link = self._call(
            self.client.account_links.create,
            params={
                "account": account,
                "type": "account_onboarding",
                "return_url": return_url,
                "refresh_url": refresh_url,
            },
        )
        return str(link["url"])

    def payouts_enabled(self, account: str) -> bool:
        return bool(self._call(self.client.accounts.retrieve, account).get("payouts_enabled"))

    def transfer(
        self, account: str, *, amount: Money, description: str, idempotency_key: str
    ) -> TransferResult:
        try:
            transfer = self.client.transfers.create(
                params={
                    "amount": amount.to_minor(),
                    "currency": amount.currency.lower(),
                    "destination": account,
                    "description": description,
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            return TransferResult("failed", message=exc.user_message or str(exc))
        return TransferResult("paid", ref=str(transfer["id"]))
