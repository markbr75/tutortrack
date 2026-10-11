"""The accounting provider interface (E23-T01).

A client gets decrypted ``Credentials`` from the integration framework and a
provider-agnostic document; it never touches the database. ``push`` is an idempotent
upsert: with an ``external_id`` it updates (or confirms) that record, without one it
creates, passing ``idempotency_key`` so a retried create after a lost response doesn't
duplicate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from tutortrack.integrations.providers import Credentials, ProviderError

from ..documents import Document, Pushed


class LedgerRejected(ProviderError):
    """The ledger refused the document (validation): retrying won't help until someone
    changes a mapping or the record. ``code`` classifies it for the dashboard."""

    retryable = False

    def __init__(self, message: str, code: str = "rejected"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LedgerAccount:
    id: str
    code: str
    name: str
    type: str  # revenue | expense | direct_costs | bank | current_asset | liability | equity
    active: bool = True

    @property
    def is_bank(self) -> bool:
        return self.type == "bank"


@dataclass(frozen=True)
class LedgerTaxCode:
    id: str
    name: str
    rate: str  # percent as a string
    active: bool = True


@dataclass(frozen=True)
class TrackingCategory:
    id: str
    name: str
    options: tuple[tuple[str, str], ...] = ()  # (id, name)


@dataclass(frozen=True)
class LedgerInfo:
    name: str
    base_currency: str = ""
    country: str = ""
    lock_date: date | None = None


@dataclass(frozen=True)
class Chart:
    accounts: list[LedgerAccount] = field(default_factory=list)
    tax_codes: list[LedgerTaxCode] = field(default_factory=list)
    tracking: list[TrackingCategory] = field(default_factory=list)


class AccountingClient(Protocol):
    provider: str
    # Requests per minute we allow ourselves per connected company (Xero: 60).
    rate_limit: int

    def info(self, creds: Credentials) -> LedgerInfo: ...

    def chart(self, creds: Credentials) -> Chart: ...

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed: ...

    def void(self, creds: Credentials, kind: str, external_id: str) -> None: ...

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        """What is still owed on an invoice or bill (a decimal string), for reconciliation."""
        ...

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None: ...
