"""Xero (accounting API 2.0) client (E23-T02..T04).

Translation of our documents:

* contact → ``Contacts`` (``ContactNumber`` = our id, so a retried create adopts it);
* invoice → ``ACCREC`` invoice (``AUTHORISED``, line amounts exclusive of tax), credit
  applied → allocations of the contact's overpayments/prepayments; void → ``VOIDED``;
* credit note / write-off → ``ACCRECCREDIT`` credit note allocated to the invoice;
* payment → one ``Payment`` per invoice paid, the rest a ``RECEIVE-OVERPAYMENT`` bank
  transaction (unallocated client credit);
* refund → the credit portion is refunded from the overpayment; what it takes back from
  invoices replaces their payments with smaller ones (Xero has no negative payments), so
  each Xero invoice balance keeps matching ours;
* provider payout → one bank transfer of the net amount (matches the bank feed line) and
  a ``SPEND`` transaction for the fees, both from the clearing account;
* tutor bill → ``ACCPAY`` invoice; payout → ``Payment`` against it;
* summary journal → ``ManualJournals``.

Every create sends ``Idempotency-Key``. The tenant (organisation) id is the connection's
``external_account_id`` (picked from ``/connections`` when connecting).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
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
from .base import Chart, LedgerAccount, LedgerInfo, LedgerTaxCode, TrackingCategory

API = "https://api.xero.com/api.xro/2.0"
CONNECTIONS = "https://api.xero.com/connections"
SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "accounting.transactions",
    "accounting.contacts",
    "accounting.settings",
    "accounting.attachments",
)
TYPES = {
    "REVENUE": "revenue",
    "SALES": "revenue",
    "OTHERINCOME": "revenue",
    "EXPENSE": "expense",
    "OVERHEADS": "expense",
    "DIRECTCOSTS": "direct_costs",
    "BANK": "bank",
    "CURRENT": "current_asset",
    "CURRLIAB": "liability",
    "LIABILITY": "liability",
    "TERMLIAB": "liability",
    "EQUITY": "equity",
}


def _account(token: str) -> AccountInfo:
    """The first organisation the user authorised (the consent screen picks one)."""
    tenants = http.request("GET", CONNECTIONS, token=token, provider="xero").json() or []
    first = tenants[0] if tenants else {}
    return AccountInfo(str(first.get("tenantId", "")), str(first.get("tenantName", "")))


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="xero",
        authorize_endpoint="https://login.xero.com/identity/connect/authorize",
        token_endpoint="https://identity.xero.com/connect/token",  # noqa: S106 - a URL
        revoke_endpoint="https://identity.xero.com/connect/revocation",
        client_id=config["XERO_CLIENT_ID"],
        client_secret=config["XERO_CLIENT_SECRET"],
        basic_auth=True,
        account=_account,
    )


def parse_date(value: Any) -> date | None:
    """Xero dates: ``/Date(1711843200000+0000)/`` or ISO."""
    if not value:
        return None
    match = re.match(r"/Date\((-?\d+)", str(value))
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=UTC).date()
    return date.fromisoformat(str(value)[:10])


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class XeroClient:
    provider = "xero"
    rate_limit = 55  # Xero allows 60 calls a minute per organisation

    def _call(
        self,
        creds: Credentials,
        method: str,
        path: str,
        body: Any = None,
        *,
        key: str = "",
        params: dict[str, Any] | None = None,
        raw: bytes | None = None,
        content_type: str = "",
    ) -> Any:
        headers = {"Xero-tenant-id": creds.account_id}
        if key:
            headers["Idempotency-Key"] = key[:128]
        if content_type:
            headers["Content-Type"] = content_type
        return http.request(
            method,
            f"{API}{path}",
            token=creds.access_token,
            json_body=body,
            body=raw,
            params=params,
            headers=headers,
            provider="xero",
        ).json()

    # --- reads ------------------------------------------------------------------------------

    def info(self, creds: Credentials) -> LedgerInfo:
        org = (self._call(creds, "GET", "/Organisation").get("Organisations") or [{}])[0]
        locks = [parse_date(org.get("PeriodLockDate")), parse_date(org.get("EndOfYearLockDate"))]
        known = [d for d in locks if d]
        return LedgerInfo(
            name=str(org.get("Name", "")),
            base_currency=str(org.get("BaseCurrency", "")),
            country=str(org.get("CountryCode", "")),
            lock_date=max(known) if known else None,
        )

    def chart(self, creds: Credentials) -> Chart:
        accounts = [
            LedgerAccount(
                id=str(a["AccountID"]),
                code=str(a.get("Code", "")),
                name=str(a.get("Name", "")),
                type=TYPES.get(str(a.get("Type", "")), "other"),
                active=a.get("Status") == "ACTIVE",
            )
            for a in self._call(creds, "GET", "/Accounts").get("Accounts", [])
        ]
        taxes = [
            LedgerTaxCode(
                id=str(t["TaxType"]),
                name=str(t.get("Name", "")),
                rate=str(t.get("EffectiveRate", "0")),
                active=t.get("Status") == "ACTIVE",
            )
            for t in self._call(creds, "GET", "/TaxRates").get("TaxRates", [])
        ]
        tracking = [
            TrackingCategory(
                id=str(c["TrackingCategoryID"]),
                name=str(c.get("Name", "")),
                options=tuple(
                    (str(o["TrackingOptionID"]), str(o.get("Name", "")))
                    for o in c.get("Options", [])
                ),
            )
            for c in self._call(creds, "GET", "/TrackingCategories").get("TrackingCategories", [])
        ]
        return Chart(accounts=accounts, tax_codes=taxes, tracking=tracking)

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        found = self._call(creds, "GET", f"/Invoices/{external_id}").get("Invoices") or []
        return str(found[0].get("AmountDue")) if found else None

    # --- writes -----------------------------------------------------------------------------

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed:
        handler = getattr(self, f"_push_{doc.kind}")
        result: Pushed = handler(creds, doc, external_id, idempotency_key)
        return result

    def void(self, creds: Credentials, kind: str, external_id: str) -> None:
        self._call(
            creds,
            "POST",
            f"/Invoices/{external_id}",
            {"Invoices": [{"InvoiceID": external_id, "Status": "VOIDED"}]},
        )

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None:
        self._call(
            creds,
            "PUT",
            f"/Invoices/{external_id}/Attachments/{filename}",
            raw=content,
            content_type="application/pdf",
            params={"IncludeOnline": "true"},
        )

    @staticmethod
    def _lines(doc: InvoiceDoc | CreditNoteDoc) -> list[dict[str, Any]]:
        return [
            {
                "Description": line.description[:4000],
                "Quantity": str(line.quantity),
                "UnitAmount": str(
                    line.unit_amount if line.unit_amount is not None else line.net / line.quantity
                ),
                "LineAmount": _money(line.net),
                "AccountCode": line.account_code,
                "TaxType": line.tax_code or "NONE",
                "TaxAmount": _money(line.tax),
                "Tracking": [
                    {"TrackingCategoryID": c, "TrackingOptionID": o} for c, o in line.tracking
                ],
            }
            for line in doc.lines
        ]

    def _push_contact(
        self, creds: Credentials, doc: ContactDoc, external_id: str, key: str
    ) -> Pushed:
        if not external_id:
            found = self._call(
                creds, "GET", "/Contacts", params={"where": f'ContactNumber=="{doc.ref}"'}
            ).get("Contacts")
            external_id = str(found[0]["ContactID"]) if found else ""
        body: dict[str, Any] = {
            "Name": doc.name[:255],
            "ContactNumber": doc.ref,
            "EmailAddress": doc.email,
            "IsSupplier": doc.supplier,
            "IsCustomer": not doc.supplier,
        }
        if doc.address:
            body["Addresses"] = [
                {
                    "AddressType": "POBOX",
                    "AddressLine1": doc.address.get("line1", ""),
                    "AddressLine2": doc.address.get("line2", ""),
                    "City": doc.address.get("city", ""),
                    "Region": doc.address.get("region", ""),
                    "PostalCode": doc.address.get("postcode", ""),
                    "Country": doc.address.get("country", ""),
                }
            ]
        if doc.phone:
            body["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": doc.phone}]
        if external_id:
            body["ContactID"] = external_id
        result = self._call(creds, "POST", "/Contacts", {"Contacts": [body]}, key=key)
        return Pushed(str(result["Contacts"][0]["ContactID"]), created=not external_id)

    def _push_invoice(
        self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            self._apply_credit(creds, doc, external_id)
            return Pushed(external_id, doc.number, created=False)
        body = {
            "Type": "ACCPAY" if doc.bill else "ACCREC",
            "Contact": {"ContactID": doc.contact},
            "Date": doc.date,
            "DueDate": doc.due_date or doc.date,
            "InvoiceNumber": doc.number,
            "Reference": (doc.reference or doc.note)[:255],
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",
            "LineAmountTypes": "Exclusive",
            "LineItems": self._lines(doc),
        }
        result = self._call(creds, "PUT", "/Invoices", {"Invoices": [body]}, key=key)
        invoice_id = str(result["Invoices"][0]["InvoiceID"])
        self._apply_credit(creds, doc, invoice_id)
        return Pushed(invoice_id, doc.number)

    _push_bill = _push_invoice

    def _apply_credit(self, creds: Credentials, doc: InvoiceDoc, invoice_id: str) -> None:
        """Allocate the contact's remaining overpayments to match ``credit_applied``."""
        if doc.bill or not doc.credit_applied:
            return
        invoice = self._call(creds, "GET", f"/Invoices/{invoice_id}")["Invoices"][0]
        already = sum(
            (Decimal(str(o.get("Amount", 0))) for o in invoice.get("Overpayments", [])),
            Decimal(0),
        )
        needed = doc.credit_applied - already
        if needed <= 0:
            return
        found = self._call(
            creds,
            "GET",
            "/Overpayments",
            params={"where": f'Contact.ContactID==guid("{doc.contact}") AND Status=="AUTHORISED"'},
        ).get("Overpayments", [])
        for over in found:
            if needed <= 0:
                break
            take = min(needed, Decimal(str(over.get("RemainingCredit", 0))))
            if take <= 0:
                continue
            self._call(
                creds,
                "PUT",
                f"/Overpayments/{over['OverpaymentID']}/Allocations",
                {
                    "Allocations": [
                        {
                            "Invoice": {"InvoiceID": invoice_id},
                            "Amount": _money(take),
                            "Date": doc.date,
                        }
                    ]
                },
            )
            needed -= take

    def _push_credit_note(
        self, creds: Credentials, doc: CreditNoteDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, doc.number, created=False)
        body = {
            "Type": "ACCRECCREDIT",
            "Contact": {"ContactID": doc.contact},
            "Date": doc.date,
            "CreditNoteNumber": doc.number,
            "Reference": (doc.reason or doc.note)[:255],
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",
            "LineAmountTypes": "Exclusive",
            "LineItems": self._lines(doc),
        }
        result = self._call(creds, "PUT", "/CreditNotes", {"CreditNotes": [body]}, key=key)
        note_id = str(result["CreditNotes"][0]["CreditNoteID"])
        if doc.allocate:
            self._call(
                creds,
                "PUT",
                f"/CreditNotes/{note_id}/Allocations",
                {
                    "Allocations": [
                        {
                            "Invoice": {"InvoiceID": doc.invoice},
                            "Amount": _money(doc.allocate),
                            "Date": doc.date,
                        }
                    ]
                },
            )
        return Pushed(note_id, doc.number)

    _push_write_off = _push_credit_note

    def _payment(
        self,
        creds: Credentials,
        *,
        target: str,
        account: str,
        amount: Decimal,
        day: str,
        reference: str,
        key: str,
    ) -> str:
        body = {
            "Invoice": {"InvoiceID": target},
            "Account": {"AccountID": account},
            "Date": day,
            "Amount": _money(amount),
            "Reference": reference[:255],
        }
        result = self._call(creds, "PUT", "/Payments", {"Payments": [body]}, key=key)
        return str(result["Payments"][0]["PaymentID"])

    def _push_payment(
        self, creds: Credentials, doc: PaymentDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        parts: list[list[str]] = []
        for n, (target, amount) in enumerate(doc.allocations):
            pid = self._payment(
                creds,
                target=target,
                account=doc.account,
                amount=amount,
                day=doc.date,
                reference=doc.reference,
                key=f"{key}:{n}",
            )
            parts.append([target, pid, str(amount)])
        if doc.unallocated:
            body = {
                "Type": "RECEIVE-OVERPAYMENT",
                "Contact": {"ContactID": doc.contact},
                "BankAccount": {"AccountID": doc.account},
                "Date": doc.date,
                "Reference": doc.reference[:255],
                "LineAmountTypes": "NoTax",
                "LineItems": [
                    {"Description": doc.reference[:4000], "LineAmount": _money(doc.unallocated)}
                ],
            }
            result = self._call(
                creds, "PUT", "/BankTransactions", {"BankTransactions": [body]}, key=f"{key}:over"
            )
            over = result["BankTransactions"][0].get("OverpaymentID", "")
            parts.append(["overpayment", str(over), str(doc.unallocated)])
        first = parts[0][1] if parts else ""
        return Pushed(first, meta={"parts": parts})

    _push_bill_payment = _push_payment

    def _push_refund(
        self, creds: Credentials, doc: RefundDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        ids: list[str] = []
        if doc.from_credit:
            over = next((p for p in doc.parts if p[0] == "overpayment"), None)
            if over is not None:
                body = {
                    "Overpayment": {"OverpaymentID": over[1]},
                    "Account": {"AccountID": doc.account},
                    "Date": doc.date,
                    "Amount": _money(doc.from_credit),
                    "Reference": doc.reference[:255],
                }
                result = self._call(creds, "PUT", "/Payments", {"Payments": [body]}, key=key)
                ids.append(str(result["Payments"][0]["PaymentID"]))
        for n, (invoice, amount) in enumerate(doc.from_invoices):
            part = next((p for p in doc.parts if p[0] == invoice), None)
            if part is None:
                continue
            self._call(
                creds,
                "POST",
                f"/Payments/{part[1]}",
                {"Payments": [{"PaymentID": part[1], "Status": "DELETED"}]},
            )
            remaining = Decimal(part[2]) - amount
            if remaining > 0:
                ids.append(
                    self._payment(
                        creds,
                        target=invoice,
                        account=doc.account,
                        amount=remaining,
                        day=doc.date,
                        reference=doc.reference,
                        key=f"{key}:{n}",
                    )
                )
        return Pushed(ids[0] if ids else f"refund:{doc.ref}", meta={"payments": ids})

    def _fees_contact(self, creds: Credentials, name: str) -> str:
        found = self._call(creds, "GET", "/Contacts", params={"where": f'Name=="{name}"'}).get(
            "Contacts"
        )
        if found:
            return str(found[0]["ContactID"])
        result = self._call(creds, "POST", "/Contacts", {"Contacts": [{"Name": name}]})
        return str(result["Contacts"][0]["ContactID"])

    def _push_provider_payout(
        self, creds: Credentials, doc: PayoutDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        transfer = {
            "FromBankAccount": {"AccountID": doc.clearing_account},
            "ToBankAccount": {"AccountID": doc.bank_account},
            "Amount": _money(doc.net),
            "Date": doc.date,
            "Reference": doc.reference[:255],
        }
        result = self._call(creds, "PUT", "/BankTransfers", {"BankTransfers": [transfer]}, key=key)
        transfer_id = str(result["BankTransfers"][0]["BankTransferID"])
        if doc.fees:
            spend = {
                "Type": "SPEND",
                "Contact": {"ContactID": self._fees_contact(creds, "Stripe")},
                "BankAccount": {"AccountID": doc.clearing_account},
                "Date": doc.date,
                "Reference": doc.reference[:255],
                "LineAmountTypes": "NoTax",
                "LineItems": [
                    {
                        "Description": f"Fees {doc.reference}"[:4000],
                        "LineAmount": _money(doc.fees),
                        "AccountID": doc.fee_account,
                        "TaxType": doc.fee_tax_code or "NONE",
                    }
                ],
            }
            self._call(
                creds, "PUT", "/BankTransactions", {"BankTransactions": [spend]}, key=f"{key}:fees"
            )
        return Pushed(transfer_id)

    def _push_journal(
        self, creds: Credentials, doc: JournalDoc, external_id: str, key: str
    ) -> Pushed:
        body: dict[str, Any] = {
            "Narration": doc.narration[:500],
            "Date": doc.date,
            "Status": "POSTED",
            "LineAmountTypes": "NoTax",
            "JournalLines": [
                {
                    "LineAmount": _money(line.debit - line.credit),
                    "AccountCode": line.account_code,
                    "Description": line.description[:500],
                    "TaxType": line.tax_code or "NONE",
                    "Tracking": [
                        {"TrackingCategoryID": c, "TrackingOptionID": o} for c, o in line.tracking
                    ],
                }
                for line in doc.lines
            ],
        }
        if external_id:
            body["ManualJournalID"] = external_id
        result = self._call(
            creds,
            "POST" if external_id else "PUT",
            "/ManualJournals",
            {"ManualJournals": [body]},
            key="" if external_id else key,
        )
        return Pushed(str(result["ManualJournals"][0]["ManualJournalID"]), created=not external_id)
