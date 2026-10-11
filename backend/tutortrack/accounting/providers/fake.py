"""An in-memory ledger standing in for Xero and QuickBooks Online when the platform keys
are empty (development, tests). It keeps balances like the real thing, so tests can
assert that the ledger's invoice balance matches TutorTrack's at each step (E23 AC).

State lives in the Django cache under the connected company's account id (shared by the
web process and workers in development). Test helpers: ``FakeLedger(account_id)`` to
inspect records, ``archive(code)`` to make an account unusable (a validation error), and
``set_lock_date``; ``integrations.providers.fake.fail("xero", n)`` makes calls fail.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.cache import cache

from tutortrack.integrations.providers import Credentials, NotFound
from tutortrack.integrations.providers.fake import _check

from ..documents import (
    ContactDoc,
    CreditNoteDoc,
    Document,
    InvoiceDoc,
    JournalDoc,
    PaymentDoc,
    PayoutDoc,
    Pushed,
    RefundDoc,
)
from .base import Chart, LedgerAccount, LedgerInfo, LedgerRejected, LedgerTaxCode, TrackingCategory

TTL = 60 * 60 * 24 * 30
PREFIX = "accounting:fake"
_lock = threading.Lock()

ACCOUNTS = (
    ("090", "Business Bank Account", "bank"),
    ("091", "Stripe Clearing", "bank"),
    ("092", "Cash and Cheques Clearing", "bank"),
    ("200", "Tuition Sales", "revenue"),
    ("210", "Other Revenue", "revenue"),
    ("310", "Tutor Costs", "direct_costs"),
    ("404", "Bank and Payment Fees", "expense"),
    ("420", "Tutor Expenses", "expense"),
    ("610", "Accounts Receivable", "current_asset"),
    ("684", "Bad Debts", "expense"),
    ("800", "Accounts Payable", "liability"),
    ("820", "VAT", "liability"),
    ("860", "Rounding", "liability"),
)
TAX_CODES = (
    ("OUTPUT2", "20% (VAT on Income)", "20"),
    ("ZERORATEDOUTPUT", "Zero Rated Income", "0"),
    ("EXEMPTOUTPUT", "Exempt Income", "0"),
    ("INPUT2", "20% (VAT on Expenses)", "20"),
    ("NONE", "No VAT", "0"),
)
TRACKING = (("trk-branch", "Branch", (("opt-main", "Main"), ("opt-north", "North"))),)


def _key(account_id: str) -> str:
    return f"{PREFIX}:{account_id}"


def _empty() -> dict[str, Any]:
    return {
        "records": {},  # collection -> {id: record}
        "archived": [],
        "lock_date": None,
        "idempotency": {},
        "calls": 0,
    }


def _load(account_id: str) -> dict[str, Any]:
    return cache.get(_key(account_id)) or _empty()


def _save(account_id: str, state: dict[str, Any]) -> None:
    cache.set(_key(account_id), state, TTL)


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


class FakeLedger:
    """Test helper: inspect and steer one fake company."""

    def __init__(self, account_id: str):
        self.account_id = account_id

    def records(self, collection: str) -> list[dict[str, Any]]:
        return list(_load(self.account_id)["records"].get(collection, {}).values())

    def get(self, collection: str, external_id: str) -> dict[str, Any]:
        return dict(_load(self.account_id)["records"][collection][external_id])

    def amount_due(self, collection: str, external_id: str) -> Decimal:
        return _dec(self.get(collection, external_id)["amount_due"])

    def archive(self, code: str) -> None:
        with _lock:
            state = _load(self.account_id)
            state["archived"] = [*state["archived"], code]
            _save(self.account_id, state)

    def unarchive(self, code: str) -> None:
        with _lock:
            state = _load(self.account_id)
            state["archived"] = [c for c in state["archived"] if c != code]
            _save(self.account_id, state)

    def set_lock_date(self, day: date | None) -> None:
        with _lock:
            state = _load(self.account_id)
            state["lock_date"] = day.isoformat() if day else None
            _save(self.account_id, state)

    @property
    def calls(self) -> int:
        return int(_load(self.account_id)["calls"])


class FakeAccountingClient:
    """Shared by both providers; ``provider`` only changes the names it reports."""

    def __init__(self, provider: str, rate_limit: int = 60):
        self.provider = provider
        self.rate_limit = rate_limit

    # --- reads ------------------------------------------------------------------------------

    def info(self, creds: Credentials) -> LedgerInfo:
        _check(self.provider, creds.account_id)
        state = _load(creds.account_id)
        lock = state.get("lock_date")
        label = "Xero" if self.provider == "xero" else "QuickBooks"
        return LedgerInfo(
            name=f"Bright Minds Ltd ({label} demo company)",
            base_currency="GBP",
            country="GB",
            lock_date=date.fromisoformat(lock) if lock else None,
        )

    def chart(self, creds: Credentials) -> Chart:
        _check(self.provider, creds.account_id)
        archived = set(_load(creds.account_id)["archived"])
        return Chart(
            accounts=[
                LedgerAccount(f"acc-{code}", code, name, kind, active=code not in archived)
                for code, name, kind in ACCOUNTS
            ],
            tax_codes=[LedgerTaxCode(code, name, rate) for code, name, rate in TAX_CODES],
            tracking=[TrackingCategory(cid, name, options) for cid, name, options in TRACKING],
        )

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        collection = "bills" if kind == "bill" else "invoices"
        record = _load(creds.account_id)["records"].get(collection, {}).get(external_id)
        return None if record is None else str(record["amount_due"])

    # --- writes -----------------------------------------------------------------------------

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed:
        _check(self.provider, creds.account_id)
        with _lock:
            state = _load(creds.account_id)
            state["calls"] += 1
            if not external_id and idempotency_key in state["idempotency"]:
                _save(creds.account_id, state)
                found = state["idempotency"][idempotency_key]
                return Pushed(found["id"], found.get("number", ""), created=False)
            self._validate(state, doc)
            handler = getattr(self, f"_push_{doc.kind}")
            result: Pushed = handler(state, doc, external_id)
            if result.created:
                state["idempotency"][idempotency_key] = {
                    "id": result.external_id,
                    "number": result.number,
                }
            _save(creds.account_id, state)
        return result

    def void(self, creds: Credentials, kind: str, external_id: str) -> None:
        _check(self.provider, creds.account_id)
        with _lock:
            state = _load(creds.account_id)
            invoice = self._find(state, "invoices", external_id)
            if _dec(invoice["paid"]) > 0:
                raise LedgerRejected("Invoice has payments applied; remove them first.")
            invoice["status"] = "VOIDED"
            invoice["amount_due"] = "0"
            _save(creds.account_id, state)

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None:
        _check(self.provider, creds.account_id)
        with _lock:
            state = _load(creds.account_id)
            attachments = state["records"].setdefault("attachments", {})
            attachments[f"{external_id}:{filename}"] = {
                "record": external_id,
                "filename": filename,
                "size": len(content),
            }
            _save(creds.account_id, state)

    # --- internals --------------------------------------------------------------------------

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(6)}"

    @staticmethod
    def _find(state: dict[str, Any], collection: str, external_id: str) -> dict[str, Any]:
        record = state["records"].get(collection, {}).get(external_id)
        if record is None:
            raise NotFound(f"{collection[:-1].capitalize()} {external_id} not found.")
        found: dict[str, Any] = record
        return found

    @staticmethod
    def _store(state: dict[str, Any], collection: str, record: dict[str, Any]) -> None:
        state["records"].setdefault(collection, {})[record["id"]] = record

    def _validate(self, state: dict[str, Any], doc: Document) -> None:
        lock = state.get("lock_date")
        if lock and doc.date and doc.date <= lock:
            raise LedgerRejected(
                "The document date cannot be before the period lock date.", "period_locked"
            )
        valid = {f"acc-{code}": code for code, _n, _k in ACCOUNTS}
        archived = set(state["archived"])
        accounts: list[str] = []
        taxes: list[str] = []
        for line in getattr(doc, "lines", ()):
            accounts.append(line.account)
            if line.tax_code:
                taxes.append(line.tax_code)
        for name in ("account", "clearing_account", "bank_account", "fee_account"):
            if getattr(doc, name, ""):
                accounts.append(getattr(doc, name))
        for account in accounts:
            code = valid.get(account)
            if code is None or code in archived:
                shown = code or account
                raise LedgerRejected(
                    f"Account code '{shown}' has been archived, or has been deleted. Each "
                    "line item must reference a valid account.",
                    "account_archived",
                )
        known_tax = {code for code, _n, _r in TAX_CODES}
        for tax in taxes:
            if tax not in known_tax:
                raise LedgerRejected(f"The TaxType code '{tax}' does not exist.", "tax_code")
        contact = getattr(doc, "contact", "")
        if contact and contact not in state["records"].get("contacts", {}):
            raise LedgerRejected("The contact could not be found.", "contact_missing")

    def _push_contact(self, state: dict[str, Any], doc: ContactDoc, external_id: str) -> Pushed:
        contacts = state["records"].setdefault("contacts", {})
        if not external_id:  # adopt a contact we created before (ContactNumber = our id)
            for record in contacts.values():
                if record["ref"] == doc.ref:
                    external_id = record["id"]
        record = contacts.get(external_id) if external_id else None
        created = record is None
        if record is None:
            record = {"id": self._new_id("contact"), "credit": "0"}
        record.update(
            ref=doc.ref, name=doc.name, email=doc.email, supplier=doc.supplier, phone=doc.phone
        )
        self._store(state, "contacts", record)
        return Pushed(record["id"], created=created)

    def _push_invoice(self, state: dict[str, Any], doc: InvoiceDoc, external_id: str) -> Pushed:
        collection = "bills" if doc.bill else "invoices"
        if doc.void:
            raise LedgerRejected("Void an invoice with void().")
        record = state["records"].get(collection, {}).get(external_id) if external_id else None
        total = sum((line.gross for line in doc.lines), Decimal(0))
        if total != doc.total:
            raise LedgerRejected("The line totals don't add up to the invoice total.")
        if record is None:
            record = {
                "id": self._new_id("bill" if doc.bill else "inv"),
                "number": doc.number,
                "contact": doc.contact,
                "date": doc.date,
                "currency": doc.currency,
                "total": str(doc.total),
                "paid": "0",
                "credited": "0",
                "credit_applied": "0",
                "amount_due": str(doc.total),
                "status": "AUTHORISED",
                "lines": [asdict(line) for line in doc.lines],
                "note": doc.note,
            }
            created = True
        else:
            created = False
            if _dec(record["paid"]) == 0 and record["total"] != str(doc.total):
                record["total"] = str(doc.total)
                record["lines"] = [asdict(line) for line in doc.lines]
            elif record["total"] != str(doc.total):
                raise LedgerRejected("Invoice has payments applied; it can't be changed.")
        if not doc.bill:
            delta = doc.credit_applied - _dec(record["credit_applied"])
            if delta:
                self._use_credit(state, doc.contact, delta)
                record["credit_applied"] = str(doc.credit_applied)
        self._recompute(record)
        self._store(state, collection, record)
        return Pushed(record["id"], record["number"], created=created)

    _push_bill = _push_invoice

    @staticmethod
    def _recompute(record: dict[str, Any]) -> None:
        due = (
            _dec(record["total"])
            - _dec(record["paid"])
            - _dec(record["credited"])
            - _dec(record.get("credit_applied", "0"))
        )
        record["amount_due"] = str(due)
        if record["status"] != "VOIDED":
            record["status"] = "PAID" if due <= 0 else "AUTHORISED"

    def _use_credit(self, state: dict[str, Any], contact: str, amount: Decimal) -> None:
        record = self._find(state, "contacts", contact)
        left = _dec(record["credit"]) - amount
        if left < 0:
            raise LedgerRejected("The contact doesn't have enough credit to allocate.")
        record["credit"] = str(left)

    def _push_credit_note(
        self, state: dict[str, Any], doc: CreditNoteDoc, external_id: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)  # issued credit notes never change
        invoice = self._find(state, "invoices", doc.invoice)
        if doc.allocate > _dec(invoice["amount_due"]):
            raise LedgerRejected("The allocation is more than is owed on the invoice.")
        record = {
            "id": self._new_id("cn"),
            "number": doc.number,
            "kind": doc.kind,
            "invoice": doc.invoice,
            "contact": doc.contact,
            "total": str(doc.total),
            "allocated": str(doc.allocate),
            "date": doc.date,
        }
        invoice["credited"] = str(_dec(invoice["credited"]) + doc.allocate)
        self._recompute(invoice)
        contact = self._find(state, "contacts", doc.contact)
        contact["credit"] = str(_dec(contact["credit"]) + doc.total - doc.allocate)
        self._store(state, "credit_notes", record)
        return Pushed(record["id"], doc.number)

    _push_write_off = _push_credit_note

    def _push_payment(self, state: dict[str, Any], doc: PaymentDoc, external_id: str) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        collection = "bills" if doc.bill else "invoices"
        for target, amount in doc.allocations:
            record = self._find(state, collection, target)
            if amount > _dec(record["amount_due"]):
                raise LedgerRejected(
                    "Payment amount exceeds the amount outstanding on this document."
                )
        for target, amount in doc.allocations:
            record = self._find(state, collection, target)
            record["paid"] = str(_dec(record["paid"]) + amount)
            self._recompute(record)
        if doc.unallocated and doc.contact:
            contact = self._find(state, "contacts", doc.contact)
            contact["credit"] = str(_dec(contact["credit"]) + doc.unallocated)
        record = {
            "id": self._new_id("pay"),
            "contact": doc.contact,
            "account": doc.account,
            "amount": str(doc.amount),
            "reference": doc.reference,
            "allocations": [[t, str(a)] for t, a in doc.allocations],
            "unallocated": str(doc.unallocated),
            "date": doc.date,
        }
        self._store(state, "bill_payments" if doc.bill else "payments", record)
        return Pushed(record["id"])

    _push_bill_payment = _push_payment

    def _push_refund(self, state: dict[str, Any], doc: RefundDoc, external_id: str) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        for invoice_id, amount in doc.from_invoices:
            invoice = self._find(state, "invoices", invoice_id)
            invoice["paid"] = str(_dec(invoice["paid"]) - amount)
            self._recompute(invoice)
        if doc.from_credit:
            self._use_credit(state, doc.contact, doc.from_credit)
        record = {
            "id": self._new_id("refund"),
            "payment": doc.payment,
            "contact": doc.contact,
            "amount": str(doc.amount),
            "reference": doc.reference,
            "date": doc.date,
        }
        self._store(state, "refunds", record)
        return Pushed(record["id"])

    def _push_provider_payout(
        self, state: dict[str, Any], doc: PayoutDoc, external_id: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        transfer = {
            "id": self._new_id("transfer"),
            "from": doc.clearing_account,
            "to": doc.bank_account,
            "amount": str(doc.net),
            "reference": doc.reference,
            "date": doc.date,
        }
        self._store(state, "transfers", transfer)
        if doc.fees:
            self._store(
                state,
                "spend",
                {
                    "id": self._new_id("spend"),
                    "from": doc.clearing_account,
                    "account": doc.fee_account,
                    "amount": str(doc.fees),
                    "reference": doc.reference,
                    "date": doc.date,
                },
            )
        return Pushed(transfer["id"])

    def _push_journal(self, state: dict[str, Any], doc: JournalDoc, external_id: str) -> Pushed:
        if not doc.balanced:
            raise LedgerRejected("The journal doesn't balance.", "unbalanced")
        record: dict[str, Any] = {
            "id": external_id or self._new_id("journal"),
            "date": doc.date,
            "narration": doc.narration,
            "lines": [asdict(line) for line in doc.lines],
        }
        self._store(state, "journals", record)
        return Pushed(record["id"], created=not external_id)
