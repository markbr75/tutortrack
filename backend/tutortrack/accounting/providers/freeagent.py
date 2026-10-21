"""FreeAgent (API v2) client (E23-T10).

Translation of our documents:

* contact → ``/contacts`` (FreeAgent contacts are both customers and suppliers; our id is
  kept in ``account_number`` so a retried create adopts the existing contact);
* invoice → ``/invoices`` then marked as sent; void → the ``mark_as_cancelled``
  transition; a tutor bill → ``/bills``;
* credit note / write-off → ``/credit_notes`` (FreeAgent applies credit notes to the
  contact's open invoices itself);
* payment and refund → a bank transaction explanation on the clearing bank account
  (``paid_invoice`` / ``paid_bill``), one per allocation;
* provider payout → a ``transfer_bank_account`` explanation of the net amount plus a
  fees explanation;
* summary journal → ``/journal_sets``;
* reallocation (gap G5) → the payment's explanations deleted and explained again against
  the new invoices, on the payment's own date.

Read-back (E23-T09, gap G5): explanations on the company's bank accounts whose
``paid_invoice`` is the invoice (from its date on; bank accounts and explanations are
fetched once per read-back run).

Every call goes through ``core.net.safe_urlopen`` (``user_url=True``). FreeAgent has
no tracking categories we map. Tested against request shapes only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings

from tutortrack.integrations.providers import AccountInfo, Credentials, http
from tutortrack.integrations.providers.oauth2 import OAuth2Client

from ..documents import (
    ContactDoc,
    CreditNoteDoc,
    Document,
    InvoiceDoc,
    JournalDoc,
    PaymentDoc,
    PayoutDoc,
    Pushed,
    ReallocationDoc,
    RefundDoc,
)
from .base import Chart, LedgerAccount, LedgerInfo, LedgerPayment, LedgerTaxCode

PER_PAGE = 100
MAX_PAGES = 20

SCOPES: tuple[str, ...] = ()  # FreeAgent grants full access to the company
TYPES = {
    "Income": "revenue",
    "Cost of Sales": "direct_costs",
    "Admin Expenses": "expense",
    "Current Assets": "current_asset",
    "Liabilities": "liability",
    "Equity": "equity",
}


def api() -> str:
    if settings.INTEGRATIONS.get("FREEAGENT_SANDBOX"):
        return "https://api.sandbox.freeagent.com/v2"
    return "https://api.freeagent.com/v2"


def _account(token: str) -> AccountInfo:
    company = (
        http.request("GET", f"{api()}/company", token=token, provider="freeagent", user_url=True)
        .json()
        .get("company", {})
    )
    return AccountInfo(
        str(company.get("url") or company.get("subdomain", "")), str(company.get("name", ""))
    )


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="freeagent",
        authorize_endpoint=f"{api()}/approve_app",
        token_endpoint=f"{api()}/token_endpoint",
        revoke_endpoint="",
        client_id=config["FREEAGENT_CLIENT_ID"],
        client_secret=config["FREEAGENT_CLIENT_SECRET"],
        basic_auth=True,
        account=_account,
    )


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _id(url: str) -> str:
    """FreeAgent identifies records by URL; we keep the full URL as the external id."""
    return str(url)


class FreeAgentClient:
    provider = "freeagent"
    rate_limit = 100  # FreeAgent allows 120 requests a minute per user

    def __init__(self) -> None:
        # Read-back caches (one client per run): bank accounts, explanations per account.
        self._banks: list[str] | None = None
        self._explained: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def _call(
        self,
        creds: Credentials,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{api()}{path}"
        return http.request(
            method,
            url,
            token=creds.access_token,
            json_body=body,
            params=params,
            user_url=True,
            provider="freeagent",
        ).json()

    def info(self, creds: Credentials) -> LedgerInfo:
        company = self._call(creds, "GET", "/company").get("company", {})
        lock = company.get("first_accounting_year_end") or None
        return LedgerInfo(
            name=str(company.get("name", "")),
            base_currency=str(company.get("currency", "")),
            country=str(company.get("address4") or company.get("country", ""))[:2].upper(),
            lock_date=date.fromisoformat(str(lock)[:10]) if lock else None,
        )

    def chart(self, creds: Credentials) -> Chart:
        body = self._call(creds, "GET", "/categories")
        accounts: list[LedgerAccount] = []
        for group, kind in (
            ("income_categories", "revenue"),
            ("cost_of_sales_categories", "direct_costs"),
            ("admin_expenses_categories", "expense"),
            ("general_categories", "other"),
        ):
            for category in body.get(group, []):
                accounts.append(
                    LedgerAccount(
                        id=_id(category["url"]),
                        code=str(category.get("nominal_code", "")),
                        name=str(category.get("description", "")),
                        type=kind,
                    )
                )
        for bank in self._call(creds, "GET", "/bank_accounts").get("bank_accounts", []):
            accounts.append(
                LedgerAccount(
                    id=_id(bank["url"]), code="", name=str(bank.get("name", "")), type="bank"
                )
            )
        taxes = [
            LedgerTaxCode(id=rate, name=f"{rate}%", rate=rate) for rate in ("20.0", "5.0", "0.0")
        ]
        return Chart(accounts=accounts, tax_codes=taxes, tracking=[])

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        found = self._call(creds, "GET", external_id)
        record = found.get("bill" if kind == "bill" else "invoice") or {}
        return str(record.get("due_value")) if record else None

    def _bank_accounts(self, creds: Credentials) -> list[str]:
        if self._banks is None:
            body = self._call(creds, "GET", "/bank_accounts")
            self._banks = [_id(b["url"]) for b in body.get("bank_accounts", []) if b.get("url")]
        return self._banks

    def _explanations(self, creds: Credentials, bank: str, since: str) -> list[dict[str, Any]]:
        key = (bank, since)
        if key not in self._explained:
            found: list[dict[str, Any]] = []
            for page in range(1, MAX_PAGES + 1):
                params: dict[str, Any] = {"bank_account": bank, "page": page, "per_page": PER_PAGE}
                if since:
                    params["from_date"] = since
                rows = self._call(
                    creds, "GET", "/bank_transaction_explanations", params=params
                ).get("bank_transaction_explanations", [])
                found.extend(rows)
                if len(rows) < PER_PAGE:
                    break
            self._explained[key] = found
        return self._explained[key]

    def invoice_payments(self, creds: Credentials, external_id: str) -> list[LedgerPayment]:
        """Money explained against the invoice on any bank account (refunds, which are
        negative, are left out)."""
        invoice = self._call(creds, "GET", external_id).get("invoice") or {}
        if Decimal(str(invoice.get("paid_value") or "0")) <= 0:
            return []
        since = str(invoice.get("dated_on") or "")[:10]
        out: list[LedgerPayment] = []
        for bank in self._bank_accounts(creds):
            for row in self._explanations(creds, bank, since):
                if row.get("paid_invoice") != external_id:
                    continue
                value = Decimal(str(row.get("gross_value") or "0"))
                if value <= 0:
                    continue
                out.append(
                    LedgerPayment(
                        id=_id(row.get("url", "")),
                        amount=str(value),
                        date=str(row.get("dated_on") or "")[:10],
                        reference=str(row.get("description") or ""),
                        account=_id(row.get("bank_account") or bank),
                    )
                )
        return out

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed:
        handler = getattr(self, f"_push_{doc.kind}")
        result: Pushed = handler(creds, doc, external_id, idempotency_key)
        return result

    def void(self, creds: Credentials, kind: str, external_id: str) -> None:
        self._call(creds, "PUT", f"{external_id}/transitions/mark_as_cancelled")

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None:
        return None  # FreeAgent renders its own invoice PDF

    @staticmethod
    def _items(doc: InvoiceDoc | CreditNoteDoc) -> list[dict[str, Any]]:
        return [
            {
                "description": line.description[:200],
                "item_type": "Services",
                "quantity": str(line.quantity),
                "price": str(
                    line.unit_amount if line.unit_amount is not None else line.net / line.quantity
                ),
                "category": line.account,
                "sales_tax_rate": line.tax_code or "0.0",
            }
            for line in doc.lines
        ]

    def _push_contact(
        self, creds: Credentials, doc: ContactDoc, external_id: str, key: str
    ) -> Pushed:
        first, _, last = doc.name.partition(" ")
        body = {
            "contact": {
                "organisation_name": doc.name[:100],
                "first_name": first[:50],
                "last_name": last[:50],
                "email": doc.email or None,
                "account_number": doc.ref[:50],
                "address1": doc.address.get("line1", "") if doc.address else "",
                "town": doc.address.get("city", "") if doc.address else "",
                "postcode": doc.address.get("postcode", "") if doc.address else "",
            }
        }
        if external_id:
            self._call(creds, "PUT", external_id, body)
            return Pushed(external_id, created=False)
        created = self._call(creds, "POST", "/contacts", body)
        return Pushed(_id(created["contact"]["url"]))

    def _push_invoice(
        self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str
    ) -> Pushed:
        if doc.bill:
            return self._push_bill(creds, doc, external_id, key)
        if doc.void:
            if external_id:
                self.void(creds, "invoice", external_id)
            return Pushed(external_id, created=False)
        body = {
            "invoice": {
                "contact": doc.contact,
                "dated_on": doc.date,
                "due_on": doc.due_date or doc.date,
                "reference": doc.number[:50],
                "currency": doc.currency,
                "comments": doc.note[:2000],
                "invoice_items": self._items(doc),
            }
        }
        if external_id:
            self._call(creds, "PUT", external_id, body)
            return Pushed(external_id, number=doc.number, created=False)
        created = self._call(creds, "POST", "/invoices", body)
        url = _id(created["invoice"]["url"])
        self._call(creds, "PUT", f"{url}/transitions/mark_as_sent")
        return Pushed(url, number=doc.number)

    def _push_bill(self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str) -> Pushed:
        body = {
            "bill": {
                "contact": doc.contact,
                "dated_on": doc.date,
                "due_on": doc.due_date or doc.date,
                "reference": doc.number[:50],
                "currency": doc.currency,
                "bill_items": [
                    {
                        "description": line.description[:200],
                        "category": line.account,
                        "total_value": _money(line.gross),
                        "sales_tax_rate": line.tax_code or "0.0",
                    }
                    for line in doc.lines
                ],
            }
        }
        if external_id:
            self._call(creds, "PUT", external_id, body)
            return Pushed(external_id, number=doc.number, created=False)
        created = self._call(creds, "POST", "/bills", body)
        return Pushed(_id(created["bill"]["url"]), number=doc.number)

    def _push_credit_note(
        self, creds: Credentials, doc: CreditNoteDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        created = self._call(
            creds,
            "POST",
            "/credit_notes",
            {
                "credit_note": {
                    "contact": doc.contact,
                    "dated_on": doc.date,
                    "reference": doc.number[:50],
                    "currency": doc.currency,
                    "comments": (doc.reason or doc.note)[:2000],
                    "credit_note_items": self._items(doc),
                }
            },
        )
        url = _id(created["credit_note"]["url"])
        self._call(creds, "PUT", f"{url}/transitions/mark_as_sent")
        return Pushed(url, number=doc.number)

    _push_write_off = _push_credit_note

    def _explain(self, creds: Credentials, body: dict[str, Any]) -> str:
        created = self._call(
            creds, "POST", "/bank_transaction_explanations", {"bank_transaction_explanation": body}
        )
        return _id(created["bank_transaction_explanation"]["url"])

    def _push_payment(
        self, creds: Credentials, doc: PaymentDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        parts = []
        for target, amount in doc.allocations:
            parts.append(
                self._explain(
                    creds,
                    {
                        "bank_account": doc.account,
                        "dated_on": doc.date,
                        "description": doc.reference[:200],
                        "gross_value": _money(-amount if doc.bill else amount),
                        "paid_bill" if doc.bill else "paid_invoice": target,
                    },
                )
            )
        if doc.unallocated:
            parts.append(
                self._explain(
                    creds,
                    {
                        "bank_account": doc.account,
                        "dated_on": doc.date,
                        "description": f"{doc.reference} (on account)"[:200],
                        "gross_value": _money(doc.unallocated),
                        "category": "",  # FreeAgent: money received on account
                    },
                )
            )
        return Pushed(parts[0] if parts else "", meta={"parts": parts})

    _push_bill_payment = _push_payment

    def _push_reallocation(
        self, creds: Credentials, doc: ReallocationDoc, external_id: str, key: str
    ) -> Pushed:
        """Explain the payment again: its explanations go and new ones are made against the
        new invoices (and money on account), dated as the payment was."""
        for part in doc.parts:
            if part and part[0].startswith("http"):
                self._call(creds, "DELETE", part[0])
        day = doc.paid_on or doc.date
        parts = [
            self._explain(
                creds,
                {
                    "bank_account": doc.account,
                    "dated_on": day,
                    "description": doc.reference[:200],
                    "gross_value": _money(amount),
                    "paid_invoice": target,
                },
            )
            for target, amount in doc.allocations
        ]
        if doc.unallocated > 0:
            parts.append(
                self._explain(
                    creds,
                    {
                        "bank_account": doc.account,
                        "dated_on": day,
                        "description": f"{doc.reference} (on account)"[:200],
                        "gross_value": _money(doc.unallocated),
                        "category": "",
                    },
                )
            )
        return Pushed(
            parts[0] if parts else doc.payment, meta={"parts": parts}, created=not external_id
        )

    def _push_refund(
        self, creds: Credentials, doc: RefundDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        url = self._explain(
            creds,
            {
                "bank_account": doc.account,
                "dated_on": doc.date,
                "description": doc.reference[:200],
                "gross_value": _money(-doc.amount),
                "paid_invoice": doc.from_invoices[0][0] if doc.from_invoices else None,
            },
        )
        return Pushed(url)

    def _push_provider_payout(
        self, creds: Credentials, doc: PayoutDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        transfer = self._explain(
            creds,
            {
                "bank_account": doc.clearing_account,
                "dated_on": doc.date,
                "description": doc.reference[:200],
                "gross_value": _money(-doc.net),
                "transfer_bank_account": doc.bank_account,
            },
        )
        meta: dict[str, Any] = {}
        if doc.fees:
            meta["fees"] = self._explain(
                creds,
                {
                    "bank_account": doc.clearing_account,
                    "dated_on": doc.date,
                    "description": "Payment provider fees",
                    "gross_value": _money(-doc.fees),
                    "category": doc.fee_account,
                },
            )
        return Pushed(transfer, meta=meta)

    def _push_journal(
        self, creds: Credentials, doc: JournalDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        created = self._call(
            creds,
            "POST",
            "/journal_sets",
            {
                "journal_set": {
                    "dated_on": doc.date,
                    "description": doc.narration[:200],
                    "journal_entries": [
                        {
                            "category": line.account,
                            "debit_value": _money(line.debit - line.credit),
                            "description": line.description[:200],
                        }
                        for line in doc.lines
                    ],
                }
            },
        )
        return Pushed(_id(created["journal_set"]["url"]))
