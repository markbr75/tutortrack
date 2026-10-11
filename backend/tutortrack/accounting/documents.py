"""Provider-agnostic accounting documents (E23-T01).

Builders turn TutorTrack records into these; each provider client translates them into
its API (Xero, QuickBooks Online, the fake ledger). Amounts are ``Decimal`` strings in
the document's currency, already rounded at line level (CLAUDE.md rule 5). Documents
carry external ids of what they depend on (the contact, the invoice), never our models,
and hash deterministically so an unchanged record is never pushed twice.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Line:
    description: str
    account: str  # external account id
    net: Decimal
    tax: Decimal = Decimal(0)
    tax_code: str = ""  # external tax code id
    quantity: Decimal = Decimal(1)
    unit_amount: Decimal | None = None  # net per unit; defaults to net / quantity
    tracking: tuple[tuple[str, str], ...] = ()  # (category id, option id)
    account_code: str = ""

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax


@dataclass(frozen=True)
class Document:
    kind: str = ""
    ref: str = ""  # our record id (stored as the provider's reference/metadata)
    date: str = ""  # ISO date posted
    currency: str = ""
    note: str = ""  # e.g. "Originally dated 2026-03-31 (period locked)"

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def content_hash(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def with_date(self, date: str, note: str) -> Document:
        return dataclasses.replace(self, date=date, note=note)


@dataclass(frozen=True)
class ContactDoc(Document):
    """A bill payer (customer) or a self-employed tutor (supplier)."""

    name: str = ""
    email: str = ""
    phone: str = ""
    address: dict[str, str] = field(default_factory=dict)
    supplier: bool = False


@dataclass(frozen=True)
class InvoiceDoc(Document):
    number: str = ""
    contact: str = ""
    due_date: str = ""
    reference: str = ""  # PO number
    lines: tuple[Line, ...] = ()
    total: Decimal = Decimal(0)
    credit_applied: Decimal = Decimal(0)  # client credit used on it (FR-10, apply_credit)
    void: bool = False
    bill: bool = False  # True: a supplier bill (tutor pay)


@dataclass(frozen=True)
class CreditNoteDoc(Document):
    """A credit note, or a write-off (one line to the bad debt account)."""

    number: str = ""
    contact: str = ""
    invoice: str = ""  # external invoice id it reduces
    allocate: Decimal = Decimal(0)  # how much of it pays off the invoice
    lines: tuple[Line, ...] = ()
    total: Decimal = Decimal(0)
    reason: str = ""


@dataclass(frozen=True)
class PaymentDoc(Document):
    """Money received (or, with ``bill``, a payout to a tutor against their bill)."""

    contact: str = ""
    account: str = ""  # clearing/bank account the money went to (or came from)
    amount: Decimal = Decimal(0)
    reference: str = ""  # includes the invoice numbers (FR-23-4)
    allocations: tuple[tuple[str, Decimal], ...] = ()  # (external invoice/bill id, amount)
    unallocated: Decimal = Decimal(0)  # becomes an overpayment/unapplied credit
    bill: bool = False


@dataclass(frozen=True)
class RefundDoc(Document):
    contact: str = ""
    account: str = ""
    payment: str = ""  # external payment id
    amount: Decimal = Decimal(0)
    reference: str = ""
    from_invoices: tuple[tuple[str, Decimal], ...] = ()  # reopens what the payment paid
    from_credit: Decimal = Decimal(0)  # out of the client's unallocated credit
    credit_note: str = ""  # external credit note the refund is paid against, if any
    # How the provider recorded the payment: (invoice id | "overpayment", part id, amount),
    # from the payment's push result. Xero needs it to replace or refund the parts.
    parts: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class PayoutDoc(Document):
    """A provider payout: one bank deposit of ``net`` (matching the bank feed line), the
    provider's fees as spend money from the clearing account (FR-23-4)."""

    reference: str = ""
    clearing_account: str = ""
    bank_account: str = ""
    fee_account: str = ""
    net: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    fee_tax_code: str = ""


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)
    description: str = ""
    tax_code: str = ""
    tax: Decimal = Decimal(0)
    reference: str = ""
    tracking: tuple[tuple[str, str], ...] = ()
    account_code: str = ""


@dataclass(frozen=True)
class JournalDoc(Document):
    narration: str = ""
    lines: tuple[JournalLine, ...] = ()

    @property
    def balanced(self) -> bool:
        return sum((x.debit for x in self.lines), Decimal(0)) == sum(
            (x.credit for x in self.lines), Decimal(0)
        )


@dataclass(frozen=True)
class Pushed:
    external_id: str
    number: str = ""
    created: bool = True
    meta: dict[str, Any] = field(default_factory=dict)
