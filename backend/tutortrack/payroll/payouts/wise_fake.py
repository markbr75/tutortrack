"""In-memory Wise (development and tests): recipients are created per details, transfers
start ``processing`` and settle when ``settle(ref)`` is called (or immediately with
``instant``); ``fail_for`` lists recipients whose transfers bounce. Idempotent by key."""

from __future__ import annotations

import uuid
from typing import ClassVar

from tutortrack.core.money import Money
from tutortrack.integrations.providers import AccountInfo, Credentials

from . import TransferResult


class FakeWise:
    provider = "wise"
    recipients: ClassVar[dict[str, dict[str, object]]] = {}
    transfers: ClassVar[dict[str, TransferResult]] = {}
    by_key: ClassVar[dict[str, str]] = {}
    fail_for: ClassVar[set[str]] = set()
    instant: ClassVar[bool] = False

    @classmethod
    def reset(cls) -> None:
        cls.recipients.clear()
        cls.transfers.clear()
        cls.by_key.clear()
        cls.fail_for.clear()
        cls.instant = False

    @classmethod
    def settle(cls, ref: str, state: str = "paid") -> None:
        cls.transfers[ref] = TransferResult(state, ref=ref)

    def verify(self, credentials: Credentials) -> AccountInfo:
        return AccountInfo("fake-profile", "Fake Wise Business")

    def ensure_recipient(
        self,
        creds: Credentials,
        *,
        currency: str,
        name: str,
        country: str,
        details: dict[str, str],
        ref: str,
    ) -> str:
        recipient = f"{len(self.recipients) + 1000}"
        self.recipients[recipient] = {"currency": currency, "name": name, "ref": ref}
        return recipient

    def transfer(
        self,
        creds: Credentials,
        recipient: str,
        *,
        amount: Money,
        source_currency: str,
        reference: str,
        idempotency_key: str,
    ) -> TransferResult:
        if idempotency_key in self.by_key:
            return self.transfers[self.by_key[idempotency_key]]
        ref = f"wise_fake_{uuid.uuid4().hex[:10]}"
        if recipient in self.fail_for:
            result = TransferResult("failed", ref=ref, message="bounced_back")
        else:
            result = TransferResult("paid" if self.instant else "processing", ref=ref)
        self.transfers[ref] = result
        self.by_key[idempotency_key] = ref
        return result

    def status(self, creds: Credentials, transfer_id: str) -> TransferResult:
        return self.transfers.get(transfer_id, TransferResult("failed", ref=transfer_id))
