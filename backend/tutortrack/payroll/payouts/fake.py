"""In-memory payouts: accounts become ready on their first status check; transfers succeed
unless ``fail_for`` lists the account."""

from __future__ import annotations

import uuid
from typing import ClassVar

from tutortrack.core.money import Money

from . import TransferResult


class FakePayouts:
    name = "fake"
    accounts: ClassVar[dict[str, dict[str, object]]] = {}
    transfers: ClassVar[dict[str, TransferResult]] = {}
    fail_for: ClassVar[set[str]] = set()

    def create_account(self, *, email: str, country: str, ref: str) -> str:
        account = f"acct_fake_{uuid.uuid4().hex[:12]}"
        self.accounts[account] = {"email": email, "country": country, "ready": True}
        return account

    def onboarding_link(self, account: str, *, return_url: str, refresh_url: str) -> str:
        return return_url

    def payouts_enabled(self, account: str) -> bool:
        return bool(self.accounts.get(account, {}).get("ready"))

    def transfer(
        self, account: str, *, amount: Money, description: str, idempotency_key: str
    ) -> TransferResult:
        if idempotency_key in self.transfers:
            return self.transfers[idempotency_key]
        if account in self.fail_for:
            result = TransferResult("failed", message="The account can't receive payouts.")
        else:
            result = TransferResult("paid", ref=f"tr_fake_{uuid.uuid4().hex[:12]}")
        self.transfers[idempotency_key] = result
        return result
