"""An in-memory provider for tests and for development without Stripe keys.

Behaviour is driven by references: a payment method whose ref contains ``fail`` is
declined, ``3ds`` needs authentication and ``debit`` is processed later (confirmed by a
webhook), like a direct debit. Webhooks are JSON without signatures.
"""

from __future__ import annotations

import json
from typing import Any

from tutortrack.core.money import Money

from .base import AccountState, ChargeResult, Intent, MethodDetails, ProviderError, WebhookEvent


class FakeProvider:
    name = "stripe"
    publishable_key = "pk_test_fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.charges: dict[str, ChargeResult] = {}  # idempotency key -> result
        self.intents: dict[str, Intent] = {}
        self.accounts: dict[str, AccountState] = {}
        self.setup_methods: dict[str, str] = {}  # setup intent -> method ref
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_fake{self._n}"

    def create_account(self, *, country: str, email: str) -> str:
        ref = self._id("acct")
        self.accounts[ref] = AccountState(False, False, ["business_profile.url"], "gbp")
        return ref

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str:
        self.calls.append(("onboarding_link", {"account": account}))
        return f"https://connect.example.test/onboard/{account}"

    def account_state(self, account: str) -> AccountState:
        return self.accounts.get(account, AccountState(True, True, [], "gbp"))

    def create_customer(self, account: str, *, name: str, email: str, ref: str) -> str:
        return self._id("cus")

    def create_setup_intent(self, account: str, *, customer: str) -> Intent:
        ref = self._id("seti")
        return Intent(ref=ref, client_secret=f"{ref}_secret")

    def setup_result(self, account: str, intent_ref: str) -> MethodDetails | None:
        method = self.setup_methods.get(intent_ref)
        return self.method_details(account, method) if method else None

    def method_details(self, account: str, method_ref: str) -> MethodDetails:
        if "debit" in method_ref:
            return MethodDetails(method_ref, "bacs_debit", "", "6789", mandate_status="active")
        return MethodDetails(method_ref, "card", "visa", "4242", 12, 2030)

    def detach_method(self, account: str, method_ref: str) -> None:
        self.calls.append(("detach", {"method": method_ref}))

    def charge(
        self,
        account: str,
        *,
        customer: str,
        method: str,
        amount: Money,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> ChargeResult:
        if idempotency_key in self.charges:
            return self.charges[idempotency_key]
        self.calls.append(("charge", {"method": method, "amount": str(amount.amount)}))
        ref = self._id("pi")
        if "fail" in method:
            result = ChargeResult("failed", ref, "card_declined", "Your card was declined.")
        elif "3ds" in method:
            result = ChargeResult("requires_action", ref, "authentication_required", "")
        elif "debit" in method:
            result = ChargeResult("processing", ref)
        else:
            fee = Money.from_minor(int(amount.to_minor() * 15 // 1000) + 20, amount.currency)
            result = ChargeResult("succeeded", ref, fee=fee)
        self.charges[idempotency_key] = result
        return result

    def create_payment_intent(
        self,
        account: str,
        *,
        amount: Money,
        customer: str | None,
        save_method: bool,
        metadata: dict[str, str],
        idempotency_key: str,
    ) -> Intent:
        ref = self._id("pi")
        intent = Intent(ref=ref, client_secret=f"{ref}_secret", amount=amount, metadata=metadata)
        self.intents[ref] = intent
        return intent

    def succeed_intent(self, ref: str, method: str = "pm_card_visa") -> Intent:
        """Test helper: the customer paid on the page."""
        intent = self.intents[ref]
        done = Intent(
            ref=ref,
            client_secret=intent.client_secret,
            status="succeeded",
            amount=intent.amount,
            payment_method=method,
            metadata=intent.metadata,
        )
        self.intents[ref] = done
        return done

    def retrieve_intent(self, account: str, intent_ref: str) -> Intent:
        if intent_ref not in self.intents:
            raise ProviderError("No such payment.")
        return self.intents[intent_ref]

    def fee_for(self, account: str, payment_ref: str) -> Money | None:
        intent = self.intents.get(payment_ref)
        if intent and intent.amount:
            return Money.from_minor(
                int(intent.amount.to_minor() * 15 // 1000) + 20, intent.amount.currency
            )
        return None

    def refund(self, account: str, *, payment_ref: str, amount: Money, idempotency_key: str) -> str:
        self.calls.append(("refund", {"payment": payment_ref, "amount": str(amount.amount)}))
        return f"re_{idempotency_key[-12:]}"

    def parse_webhook(self, payload: bytes, signature: str) -> WebhookEvent:
        body = json.loads(payload)
        if signature != "fake-signature":
            raise ProviderError("Bad signature.")
        return WebhookEvent(
            id=body["id"],
            type=body["type"],
            account=body.get("account", ""),
            data=body["data"]["object"],
            payload=body,
        )
