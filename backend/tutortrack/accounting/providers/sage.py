"""Sage Business Cloud Accounting (API v3.1) client (E23-T10).

Translation of our documents:

* contact → ``/contacts`` (``CUSTOMER`` or ``VENDOR``; ``reference`` = our id, so a retried
  create adopts the existing contact);
* invoice → ``/sales_invoices``; a tutor bill → ``/purchase_invoices``; void → ``DELETE``
  with a void reason;
* credit note / write-off → ``/sales_credit_notes``, allocated to the invoice through a
  ``/contact_allocations`` entry;
* payment → ``/contact_payments`` (``CUSTOMER_RECEIPT``; bill payments ``VENDOR_PAYMENT``)
  allocated to each invoice, the rest left on account (a payment on account);
* refund → ``/contact_payments`` of type ``CUSTOMER_REFUND``;
* provider payout → ``/bank_transfers`` of the net amount plus an ``/other_payments``
  for the fees, both from the clearing account;
* summary journal → ``/journals``.

The business is the connection's ``external_account_id`` (``X-Business``). Every call goes
through ``core.net.safe_urlopen`` (``user_url=True``). Branch tracking (analysis types) is
not mapped. Tested against request shapes only (no sandbox credentials in CI).
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
    RefundDoc,
)
from .base import Chart, LedgerAccount, LedgerInfo, LedgerTaxCode

API = "https://api.accounting.sage.com/v3.1"
SCOPES = ("full_access",)
TYPES = {
    "SALES": "revenue",
    "OTHER_INCOME": "revenue",
    "EXPENSES": "expense",
    "OVERHEADS": "expense",
    "DIRECT_EXPENSES": "direct_costs",
    "BANK": "bank",
    "CURRENT_ASSETS": "current_asset",
    "CURRENT_LIABILITY": "liability",
    "FUTURE_LIABILITY": "liability",
    "EQUITY": "equity",
}


def _account(token: str) -> AccountInfo:
    """The business the user picked on Sage's consent screen (the lead business)."""
    body = http.request(
        "GET", f"{API}/businesses", token=token, provider="sage", user_url=True
    ).json()
    items = body.get("$items") or []
    first = items[0] if items else {}
    return AccountInfo(str(first.get("id", "")), str(first.get("name", "")))


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="sage",
        authorize_endpoint="https://www.sageone.com/oauth2/auth/central",
        token_endpoint="https://oauth.accounting.sage.com/token",  # noqa: S106 - a URL
        revoke_endpoint="https://oauth.accounting.sage.com/revoke",
        client_id=config["SAGE_CLIENT_ID"],
        client_secret=config["SAGE_CLIENT_SECRET"],
        extra_params={"filter": "apiv3.1"},
        account=_account,
    )


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class SageClient:
    provider = "sage"
    rate_limit = 100  # Sage allows 1,296,000 requests a day; we pace well below

    def _call(
        self,
        creds: Credentials,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return http.request(
            method,
            f"{API}{path}",
            token=creds.access_token,
            json_body=body,
            params=params,
            headers={"X-Business": creds.account_id},
            user_url=True,
            provider="sage",
        ).json()

    # --- reads ------------------------------------------------------------------------------

    def info(self, creds: Credentials) -> LedgerInfo:
        business = self._call(creds, "GET", "/business")
        financial = self._call(creds, "GET", "/financial_settings")
        lock = financial.get("accounts_start_date") or None
        currency = (financial.get("base_currency") or {}).get("id", "")
        return LedgerInfo(
            name=str(business.get("name", "")),
            base_currency=str(currency).upper(),
            country=str((business.get("address") or {}).get("country", {}).get("id", "")),
            lock_date=date.fromisoformat(str(lock)[:10]) if lock else None,
        )

    def chart(self, creds: Credentials) -> Chart:
        accounts = [
            LedgerAccount(
                id=str(a["id"]),
                code=str(a.get("nominal_code", "")),
                name=str(a.get("displayed_as") or a.get("name", "")),
                type=TYPES.get(str((a.get("ledger_account_type") or {}).get("id", "")), "other"),
                active=bool(a.get("visible_in_journals", True)),
            )
            for a in self._call(
                creds,
                "GET",
                "/ledger_accounts",
                params={"items_per_page": 200, "attributes": "all"},
            ).get("$items", [])
        ]
        taxes = [
            LedgerTaxCode(
                id=str(t["id"]),
                name=str(t.get("displayed_as", "")),
                rate=str(t.get("percentage", "0")),
                active=bool(t.get("is_visible", True)),
            )
            for t in self._call(creds, "GET", "/tax_rates", params={"attributes": "all"}).get(
                "$items", []
            )
        ]
        return Chart(accounts=accounts, tax_codes=taxes, tracking=[])

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        path = "/purchase_invoices" if kind == "bill" else "/sales_invoices"
        found = self._call(creds, "GET", f"{path}/{external_id}")
        return str(found.get("outstanding_amount")) if found else None

    # --- writes -----------------------------------------------------------------------------

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed:
        handler = getattr(self, f"_push_{doc.kind}")
        result: Pushed = handler(creds, doc, external_id, idempotency_key)
        return result

    def void(self, creds: Credentials, kind: str, external_id: str) -> None:
        path = "/purchase_invoices" if kind == "bill" else "/sales_invoices"
        self._call(creds, "DELETE", f"{path}/{external_id}", {"void_reason": "Voided"})

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None:
        import base64

        self._call(
            creds,
            "POST",
            "/attachments",
            {
                "attachment": {
                    "file": base64.b64encode(content).decode(),
                    "file_name": filename,
                    "mime_type": "application/pdf",
                    "file_extension": ".pdf",
                    "attachment_context_type_id": "SALES_INVOICE",
                    "attachment_context_id": external_id,
                }
            },
        )

    @staticmethod
    def _lines(doc: InvoiceDoc | CreditNoteDoc) -> list[dict[str, Any]]:
        return [
            {
                "description": line.description[:200],
                "ledger_account_id": line.account,
                "quantity": str(line.quantity),
                "unit_price": str(
                    line.unit_amount if line.unit_amount is not None else line.net / line.quantity
                ),
                "net_amount": _money(line.net),
                "tax_rate_id": line.tax_code or None,
                "tax_amount": _money(line.tax),
                "total_amount": _money(line.gross),
            }
            for line in doc.lines
        ]

    def _push_contact(
        self, creds: Credentials, doc: ContactDoc, external_id: str, key: str
    ) -> Pushed:
        if not external_id:
            found = self._call(creds, "GET", "/contacts", params={"search": doc.ref}).get("$items")
            external_id = str(found[0]["id"]) if found else ""
        body = {
            "contact": {
                "name": doc.name[:100],
                "reference": doc.ref[:50],
                "contact_type_ids": ["VENDOR" if doc.supplier else "CUSTOMER"],
                "email": doc.email or None,
                "main_address": {
                    "address_line_1": doc.address.get("line1", ""),
                    "city": doc.address.get("city", ""),
                    "postal_code": doc.address.get("postcode", ""),
                }
                if doc.address
                else None,
            }
        }
        if external_id:
            self._call(creds, "PUT", f"/contacts/{external_id}", body)
            return Pushed(external_id, created=False)
        created = self._call(creds, "POST", "/contacts", body)
        return Pushed(str(created["id"]))

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
            "sales_invoice": {
                "contact_id": doc.contact,
                "date": doc.date,
                "due_date": doc.due_date or doc.date,
                "invoice_number_prefix": "",
                "reference": doc.number[:25],
                "vendor_reference": doc.reference[:25],
                "currency_id": doc.currency,
                "notes": doc.note[:2000],
                "invoice_lines": self._lines(doc),
            }
        }
        if external_id:
            self._call(creds, "PUT", f"/sales_invoices/{external_id}", body)
            return Pushed(external_id, number=doc.number, created=False)
        created = self._call(creds, "POST", "/sales_invoices", body)
        return Pushed(str(created["id"]), number=str(created.get("invoice_number", doc.number)))

    def _push_bill(self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str) -> Pushed:
        body = {
            "purchase_invoice": {
                "contact_id": doc.contact,
                "date": doc.date,
                "due_date": doc.due_date or doc.date,
                "vendor_reference": doc.number[:25],
                "currency_id": doc.currency,
                "invoice_lines": self._lines(doc),
            }
        }
        if external_id:
            self._call(creds, "PUT", f"/purchase_invoices/{external_id}", body)
            return Pushed(external_id, number=doc.number, created=False)
        created = self._call(creds, "POST", "/purchase_invoices", body)
        return Pushed(str(created["id"]), number=doc.number)

    def _push_credit_note(
        self, creds: Credentials, doc: CreditNoteDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)  # issued once
        created = self._call(
            creds,
            "POST",
            "/sales_credit_notes",
            {
                "sales_credit_note": {
                    "contact_id": doc.contact,
                    "date": doc.date,
                    "reference": doc.number[:25],
                    "currency_id": doc.currency,
                    "notes": (doc.reason or doc.note)[:2000],
                    "credit_note_lines": self._lines(doc),
                }
            },
        )
        credit_id = str(created["id"])
        if doc.invoice and doc.allocate:
            self._call(
                creds,
                "POST",
                "/contact_allocations",
                {
                    "contact_allocation": {
                        "transaction_type_id": "CUSTOMER_ALLOCATION",
                        "contact_id": doc.contact,
                        "date": doc.date,
                        "allocated_artefacts": [
                            {"artefact_id": doc.invoice, "amount": _money(doc.allocate)},
                            {"artefact_id": credit_id, "amount": _money(-doc.allocate)},
                        ],
                    }
                },
            )
        return Pushed(credit_id, number=doc.number)

    _push_write_off = _push_credit_note

    def _push_payment(
        self, creds: Credentials, doc: PaymentDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        created = self._call(
            creds,
            "POST",
            "/contact_payments",
            {
                "contact_payment": {
                    "transaction_type_id": "VENDOR_PAYMENT" if doc.bill else "CUSTOMER_RECEIPT",
                    "contact_id": doc.contact,
                    "bank_account_id": doc.account,
                    "date": doc.date,
                    "total_amount": _money(doc.amount),
                    "reference": doc.reference[:25],
                    "allocated_artefacts": [
                        {"artefact_id": target, "amount": _money(amount)}
                        for target, amount in doc.allocations
                    ],
                }
            },
        )
        return Pushed(str(created["id"]))

    _push_bill_payment = _push_payment

    def _push_refund(
        self, creds: Credentials, doc: RefundDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        artefacts = [
            {"artefact_id": target, "amount": _money(amount)}
            for target, amount in doc.from_invoices
        ]
        if doc.credit_note:
            artefacts.append({"artefact_id": doc.credit_note, "amount": _money(doc.amount)})
        created = self._call(
            creds,
            "POST",
            "/contact_payments",
            {
                "contact_payment": {
                    "transaction_type_id": "CUSTOMER_REFUND",
                    "contact_id": doc.contact,
                    "bank_account_id": doc.account,
                    "date": doc.date,
                    "total_amount": _money(doc.amount),
                    "reference": doc.reference[:25],
                    "allocated_artefacts": artefacts,
                }
            },
        )
        return Pushed(str(created["id"]))

    def _push_provider_payout(
        self, creds: Credentials, doc: PayoutDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        transfer = self._call(
            creds,
            "POST",
            "/bank_transfers",
            {
                "bank_transfer": {
                    "from_bank_account_id": doc.clearing_account,
                    "to_bank_account_id": doc.bank_account,
                    "date": doc.date,
                    "amount": _money(doc.net),
                    "reference": doc.reference[:25],
                }
            },
        )
        meta: dict[str, Any] = {}
        if doc.fees:
            fee = self._call(
                creds,
                "POST",
                "/other_payments",
                {
                    "other_payment": {
                        "transaction_type_id": "OTHER_PAYMENT",
                        "bank_account_id": doc.clearing_account,
                        "date": doc.date,
                        "total_amount": _money(doc.fees),
                        "reference": doc.reference[:25],
                        "payment_lines": [
                            {
                                "ledger_account_id": doc.fee_account,
                                "total_amount": _money(doc.fees),
                                "net_amount": _money(doc.fees),
                                "tax_rate_id": doc.fee_tax_code or None,
                                "details": "Payment provider fees",
                            }
                        ],
                    }
                },
            )
            meta["fees"] = str(fee.get("id", ""))
        return Pushed(str(transfer["id"]), meta=meta)

    def _push_journal(
        self, creds: Credentials, doc: JournalDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        created = self._call(
            creds,
            "POST",
            "/journals",
            {
                "journal": {
                    "date": doc.date,
                    "reference": doc.narration[:25],
                    "description": doc.narration[:200],
                    "journal_lines": [
                        {
                            "ledger_account_id": line.account,
                            "debit": _money(line.debit),
                            "credit": _money(line.credit),
                            "details": line.description[:200],
                        }
                        for line in doc.lines
                    ],
                }
            },
        )
        return Pushed(str(created["id"]))
