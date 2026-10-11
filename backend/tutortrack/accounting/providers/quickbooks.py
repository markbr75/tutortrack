"""QuickBooks Online (accounting API v3) client (E23-T05).

Translation of our documents:

* contact → ``Customer`` (or ``Vendor`` for tutors), matched on ``DisplayName``;
* invoice → ``Invoice``; QuickBooks posts sales lines through items, so each revenue
  account gets a service item "TutorTrack: <account>" (created on first use); void →
  ``operation=void``; client credit applied → linked in a zero ``ReceivePayment``;
* credit note / write-off → ``CreditMemo`` applied to the invoice with a zero payment;
* payment → ``ReceivePayment`` linked to the invoices it pays (the rest stays unapplied);
* refund → the payment is reduced (sparse update), reopening what it paid, so the
  QuickBooks invoice balance keeps matching ours;
* provider payout → one ``Deposit`` of the gross from the clearing account with a
  negative fee line, so the deposit equals the bank feed line;
* tutor bill → ``Bill`` (account-based lines); payout → ``BillPayment`` (cheque);
* summary journal → ``JournalEntry``.

Creates pass ``requestid`` (QuickBooks' idempotency key). The company id (``realmId``) is
the connection's ``external_account_id``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings

from tutortrack.integrations.providers import Credentials, http
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

SCOPES = ("com.intuit.quickbooks.accounting", "openid", "email")
MINOR_VERSION = "73"
TYPES = {
    "Income": "revenue",
    "Other Income": "revenue",
    "Expense": "expense",
    "Other Expense": "expense",
    "Cost of Goods Sold": "direct_costs",
    "Bank": "bank",
    "Other Current Asset": "current_asset",
    "Accounts Receivable": "current_asset",
    "Accounts Payable": "liability",
    "Other Current Liability": "liability",
    "Long Term Liability": "liability",
    "Equity": "equity",
}


def base_url() -> str:
    if settings.INTEGRATIONS.get("QUICKBOOKS_SANDBOX"):
        return "https://sandbox-quickbooks.api.intuit.com/v3/company"
    return "https://quickbooks.api.intuit.com/v3/company"


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="quickbooks",
        authorize_endpoint="https://appcenter.intuit.com/connect/oauth2",
        token_endpoint="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",  # noqa: S106
        revoke_endpoint="https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
        client_id=config["QUICKBOOKS_CLIENT_ID"],
        client_secret=config["QUICKBOOKS_CLIENT_SECRET"],
        basic_auth=True,
    )


def _money(value: Decimal) -> float:
    # QuickBooks' JSON wants numbers; two decimals are exact in a float's repr.
    return float(f"{value:.2f}")


class QuickBooksClient:
    provider = "quickbooks"
    rate_limit = 400  # QuickBooks allows 500 a minute per company

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], str] = {}

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
        query = {"minorversion": MINOR_VERSION, **(params or {})}
        if key:
            query["requestid"] = key[:50]
        headers = {"Content-Type": content_type} if content_type else None
        return http.request(
            method,
            f"{base_url()}/{creds.account_id}{path}",
            token=creds.access_token,
            json_body=body,
            body=raw,
            params=query,
            headers=headers,
            provider="quickbooks",
        ).json()

    def _query(self, creds: Credentials, sql: str) -> dict[str, Any]:
        result: dict[str, Any] = self._call(creds, "GET", "/query", params={"query": sql}).get(
            "QueryResponse", {}
        )
        return result

    # --- reads ------------------------------------------------------------------------------

    def info(self, creds: Credentials) -> LedgerInfo:
        company = self._call(creds, "GET", f"/companyinfo/{creds.account_id}").get(
            "CompanyInfo", {}
        )
        prefs = self._call(creds, "GET", "/preferences").get("Preferences", {})
        close = (prefs.get("AccountingInfoPrefs") or {}).get("BookCloseDate")
        currency = ((prefs.get("CurrencyPrefs") or {}).get("HomeCurrency") or {}).get("value", "")
        return LedgerInfo(
            name=str(company.get("CompanyName", "")),
            base_currency=str(currency),
            country=str(company.get("Country", "")),
            lock_date=date.fromisoformat(str(close)[:10]) if close else None,
        )

    def chart(self, creds: Credentials) -> Chart:
        accounts = [
            LedgerAccount(
                id=str(a["Id"]),
                code=str(a.get("AcctNum", "")),
                name=str(a.get("Name", "")),
                type=TYPES.get(str(a.get("AccountType", "")), "other"),
                active=bool(a.get("Active", True)),
            )
            for a in self._query(creds, "select * from Account maxresults 1000").get("Account", [])
        ]
        taxes = [
            LedgerTaxCode(
                id=str(t["Id"]),
                name=str(t.get("Name", "")),
                rate="",
                active=bool(t.get("Active", True)),
            )
            for t in self._query(creds, "select * from TaxCode").get("TaxCode", [])
        ]
        classes = self._query(creds, "select * from Class").get("Class", [])
        tracking = [
            TrackingCategory(
                "class", "Class", tuple((str(c["Id"]), str(c.get("Name", ""))) for c in classes)
            )
        ]
        return Chart(accounts=accounts, tax_codes=taxes, tracking=tracking)

    def balance(self, creds: Credentials, kind: str, external_id: str) -> str | None:
        entity = "bill" if kind == "bill" else "invoice"
        found = self._call(creds, "GET", f"/{entity}/{external_id}")
        record = found.get("Bill" if kind == "bill" else "Invoice")
        return str(record.get("Balance")) if record else None

    # --- writes -----------------------------------------------------------------------------

    def push(
        self, creds: Credentials, doc: Document, external_id: str = "", *, idempotency_key: str
    ) -> Pushed:
        handler = getattr(self, f"_push_{doc.kind}")
        result: Pushed = handler(creds, doc, external_id, idempotency_key)
        return result

    def _read(self, creds: Credentials, entity: str, external_id: str) -> dict[str, Any]:
        found: dict[str, Any] = self._call(creds, "GET", f"/{entity.lower()}/{external_id}")[entity]
        return found

    def void(self, creds: Credentials, kind: str, external_id: str) -> None:
        invoice = self._read(creds, "Invoice", external_id)
        self._call(
            creds,
            "POST",
            "/invoice",
            {"Id": external_id, "SyncToken": invoice["SyncToken"]},
            params={"operation": "void"},
        )

    def attach(
        self, creds: Credentials, kind: str, external_id: str, filename: str, content: bytes
    ) -> None:
        import json
        import secrets

        boundary = secrets.token_hex(12)
        meta = {
            "AttachableRef": [{"EntityRef": {"type": "Invoice", "value": external_id}}],
            "FileName": filename,
            "ContentType": "application/pdf",
        }
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file_metadata_01"\r\n'
                f"Content-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
                f'--{boundary}\r\nContent-Disposition: form-data; name="file_content_01"; '
                f'filename="{filename}"\r\nContent-Type: application/pdf\r\n\r\n'
            ).encode()
            + content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        self._call(
            creds,
            "POST",
            "/upload",
            raw=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def _push_contact(
        self, creds: Credentials, doc: ContactDoc, external_id: str, key: str
    ) -> Pushed:
        entity = "Vendor" if doc.supplier else "Customer"
        name = doc.name.replace("'", "\\'")[:100]
        sync_token = None
        if external_id:
            sync_token = self._read(creds, entity, external_id)["SyncToken"]
        else:
            sql = f"select * from {entity} where DisplayName = '{name}'"  # noqa: S608 - escaped
            found = self._query(creds, sql).get(entity, [])
            if found:
                external_id, sync_token = str(found[0]["Id"]), found[0]["SyncToken"]
        body: dict[str, Any] = {
            "DisplayName": doc.name[:100],
            "PrimaryEmailAddr": {"Address": doc.email} if doc.email else None,
            "PrimaryPhone": {"FreeFormNumber": doc.phone} if doc.phone else None,
            "Notes": f"TutorTrack {doc.ref}",
        }
        if doc.address:
            body["BillAddr"] = {
                "Line1": doc.address.get("line1", ""),
                "Line2": doc.address.get("line2", ""),
                "City": doc.address.get("city", ""),
                "CountrySubDivisionCode": doc.address.get("region", ""),
                "PostalCode": doc.address.get("postcode", ""),
                "Country": doc.address.get("country", ""),
            }
        body = {k: v for k, v in body.items() if v is not None}
        if external_id:
            body.update(Id=external_id, SyncToken=sync_token, sparse=True)
        result = self._call(
            creds, "POST", f"/{entity.lower()}", body, key="" if external_id else key
        )
        return Pushed(str(result[entity]["Id"]), created=not external_id)

    def _item_for(self, creds: Credentials, account: str, label: str) -> str:
        """A service item posting to ``account`` (QuickBooks sales lines need items)."""
        cache_key = (creds.account_id, account)
        if cache_key in self._items:
            return self._items[cache_key]
        name = f"TutorTrack {label or account}"[:100].replace("'", "")
        sql = f"select * from Item where Name = '{name}'"  # noqa: S608 - quotes stripped
        found = self._query(creds, sql).get("Item", [])
        if found:
            item_id = str(found[0]["Id"])
        else:
            result = self._call(
                creds,
                "POST",
                "/item",
                {"Name": name, "Type": "Service", "IncomeAccountRef": {"value": account}},
            )
            item_id = str(result["Item"]["Id"])
        self._items[cache_key] = item_id
        return item_id

    def _sales_lines(self, creds: Credentials, doc: InvoiceDoc | CreditNoteDoc) -> list[Any]:
        out = []
        for line in doc.lines:
            detail: dict[str, Any] = {
                "ItemRef": {"value": self._item_for(creds, line.account, line.account_code)},
                "Qty": float(line.quantity),
                "UnitPrice": float(
                    line.unit_amount if line.unit_amount is not None else line.net / line.quantity
                ),
            }
            if line.tax_code:
                detail["TaxCodeRef"] = {"value": line.tax_code}
            if line.tracking:
                detail["ClassRef"] = {"value": line.tracking[0][1]}
            out.append(
                {
                    "DetailType": "SalesItemLineDetail",
                    "Amount": _money(line.net),
                    "Description": line.description[:4000],
                    "SalesItemLineDetail": detail,
                }
            )
        return out

    def _link(
        self, creds: Credentials, doc: Document, contact: str, links: list[tuple[str, str, Decimal]]
    ) -> str:
        """A zero ``ReceivePayment`` linking credit memos/credit to invoices."""
        lines = [
            {"Amount": _money(amount), "LinkedTxn": [{"TxnId": txn, "TxnType": kind}]}
            for txn, kind, amount in links
        ]
        result = self._call(
            creds,
            "POST",
            "/payment",
            {"CustomerRef": {"value": contact}, "TotalAmt": 0, "TxnDate": doc.date, "Line": lines},
        )
        return str(result["Payment"]["Id"])

    def _push_invoice(
        self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str
    ) -> Pushed:
        if doc.bill:
            return self._push_bill(creds, doc, external_id, key)
        if not external_id:
            body = {
                "CustomerRef": {"value": doc.contact},
                "DocNumber": doc.number[:21],
                "TxnDate": doc.date,
                "DueDate": doc.due_date or doc.date,
                "CurrencyRef": {"value": doc.currency},
                "PrivateNote": (doc.reference or doc.note)[:4000],
                "GlobalTaxCalculation": "TaxExcluded",
                "Line": self._sales_lines(creds, doc),
            }
            external_id = str(self._call(creds, "POST", "/invoice", body, key=key)["Invoice"]["Id"])
            created = True
        else:
            created = False
        if doc.credit_applied:
            invoice = self._read(creds, "Invoice", external_id)
            applied = Decimal(str(invoice.get("TotalAmt", 0))) - Decimal(
                str(invoice.get("Balance", 0))
            )
            needed = doc.credit_applied - applied
            credits = self._query(
                creds,
                f"select * from Payment where CustomerRef = '{doc.contact}' "  # noqa: S608 - an id
                "and UnappliedAmt > '0'",
            ).get("Payment", [])
            for credit in credits:
                if needed <= 0:
                    break
                take = min(needed, Decimal(str(credit.get("UnappliedAmt", 0))))
                lines = [
                    *credit.get("Line", []),
                    {
                        "Amount": _money(take),
                        "LinkedTxn": [{"TxnId": external_id, "TxnType": "Invoice"}],
                    },
                ]
                self._call(
                    creds,
                    "POST",
                    "/payment",
                    {
                        "Id": credit["Id"],
                        "SyncToken": credit["SyncToken"],
                        "sparse": True,
                        "Line": lines,
                    },
                )
                needed -= take
        return Pushed(external_id, doc.number, created=created)

    def _push_credit_note(
        self, creds: Credentials, doc: CreditNoteDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, doc.number, created=False)
        body = {
            "CustomerRef": {"value": doc.contact},
            "DocNumber": doc.number[:21],
            "TxnDate": doc.date,
            "CurrencyRef": {"value": doc.currency},
            "PrivateNote": (doc.reason or doc.note)[:4000],
            "GlobalTaxCalculation": "TaxExcluded",
            "Line": self._sales_lines(creds, doc),
        }
        memo = str(self._call(creds, "POST", "/creditmemo", body, key=key)["CreditMemo"]["Id"])
        if doc.allocate:
            self._link(
                creds,
                doc,
                doc.contact,
                [(doc.invoice, "Invoice", doc.allocate), (memo, "CreditMemo", doc.allocate)],
            )
        return Pushed(memo, doc.number)

    _push_write_off = _push_credit_note

    def _push_payment(
        self, creds: Credentials, doc: PaymentDoc, external_id: str, key: str
    ) -> Pushed:
        if doc.bill:
            return self._push_bill_payment(creds, doc, external_id, key)
        if external_id:
            return Pushed(external_id, created=False)
        body = {
            "CustomerRef": {"value": doc.contact},
            "TotalAmt": _money(doc.amount),
            "TxnDate": doc.date,
            "CurrencyRef": {"value": doc.currency},
            "DepositToAccountRef": {"value": doc.account},
            "PaymentRefNum": doc.reference[:21],
            "PrivateNote": doc.reference[:4000],
            "Line": [
                {"Amount": _money(amount), "LinkedTxn": [{"TxnId": txn, "TxnType": "Invoice"}]}
                for txn, amount in doc.allocations
            ],
        }
        result = self._call(creds, "POST", "/payment", body, key=key)
        return Pushed(str(result["Payment"]["Id"]))

    def _push_refund(
        self, creds: Credentials, doc: RefundDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        payment = self._read(creds, "Payment", doc.payment)
        taken = dict(doc.from_invoices)
        lines = []
        for line in payment.get("Line", []):
            linked = (line.get("LinkedTxn") or [{}])[0].get("TxnId", "")
            amount = Decimal(str(line.get("Amount", 0))) - taken.get(linked, Decimal(0))
            if amount > 0:
                lines.append({**line, "Amount": _money(amount)})
        total = Decimal(str(payment.get("TotalAmt", 0))) - doc.amount
        self._call(
            creds,
            "POST",
            "/payment",
            {
                "Id": doc.payment,
                "SyncToken": payment["SyncToken"],
                "sparse": True,
                "TotalAmt": _money(total),
                "Line": lines,
                "PrivateNote": f"{payment.get('PrivateNote', '')} Refunded {doc.amount}: "
                f"{doc.reference}"[:4000],
            },
        )
        return Pushed(f"{doc.payment}:refund:{doc.ref}")

    def _push_provider_payout(
        self, creds: Credentials, doc: PayoutDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        lines: list[dict[str, Any]] = [
            {
                "Amount": _money(doc.net + doc.fees),
                "DetailType": "DepositLineDetail",
                "Description": f"Payout {doc.reference}",
                "DepositLineDetail": {"AccountRef": {"value": doc.clearing_account}},
            }
        ]
        if doc.fees:
            lines.append(
                {
                    "Amount": _money(-doc.fees),
                    "DetailType": "DepositLineDetail",
                    "Description": f"Fees {doc.reference}",
                    "DepositLineDetail": {"AccountRef": {"value": doc.fee_account}},
                }
            )
        body = {
            "DepositToAccountRef": {"value": doc.bank_account},
            "TxnDate": doc.date,
            "CurrencyRef": {"value": doc.currency},
            "PrivateNote": doc.reference,
            "Line": lines,
        }
        return Pushed(str(self._call(creds, "POST", "/deposit", body, key=key)["Deposit"]["Id"]))

    def _push_bill(self, creds: Credentials, doc: InvoiceDoc, external_id: str, key: str) -> Pushed:
        lines = []
        for line in doc.lines:
            detail: dict[str, Any] = {"AccountRef": {"value": line.account}}
            if line.tax_code:
                detail["TaxCodeRef"] = {"value": line.tax_code}
            if line.tracking:
                detail["ClassRef"] = {"value": line.tracking[0][1]}
            lines.append(
                {
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "Amount": _money(line.net),
                    "Description": line.description[:4000],
                    "AccountBasedExpenseLineDetail": detail,
                }
            )
        body: dict[str, Any] = {
            "VendorRef": {"value": doc.contact},
            "DocNumber": doc.number[:21],
            "TxnDate": doc.date,
            "DueDate": doc.due_date or doc.date,
            "CurrencyRef": {"value": doc.currency},
            "GlobalTaxCalculation": "TaxExcluded",
            "PrivateNote": (doc.reference or doc.note)[:4000],
            "Line": lines,
        }
        if external_id:
            bill = self._read(creds, "Bill", external_id)
            body.update(Id=external_id, SyncToken=bill["SyncToken"])
        result = self._call(creds, "POST", "/bill", body, key="" if external_id else key)
        return Pushed(str(result["Bill"]["Id"]), doc.number, created=not external_id)

    def _push_bill_payment(
        self, creds: Credentials, doc: PaymentDoc, external_id: str, key: str
    ) -> Pushed:
        if external_id:
            return Pushed(external_id, created=False)
        body = {
            "VendorRef": {"value": doc.contact},
            "PayType": "Check",
            "CheckPayment": {"BankAccountRef": {"value": doc.account}},
            "TotalAmt": _money(doc.amount),
            "TxnDate": doc.date,
            "CurrencyRef": {"value": doc.currency},
            "PrivateNote": doc.reference,
            "Line": [
                {"Amount": _money(amount), "LinkedTxn": [{"TxnId": txn, "TxnType": "Bill"}]}
                for txn, amount in doc.allocations
            ],
        }
        result = self._call(creds, "POST", "/billpayment", body, key=key)
        return Pushed(str(result["BillPayment"]["Id"]))

    def _push_journal(
        self, creds: Credentials, doc: JournalDoc, external_id: str, key: str
    ) -> Pushed:
        lines = []
        for line in doc.lines:
            debit = line.debit > 0
            detail: dict[str, Any] = {
                "PostingType": "Debit" if debit else "Credit",
                "AccountRef": {"value": line.account},
            }
            if line.tracking:
                detail["ClassRef"] = {"value": line.tracking[0][1]}
            lines.append(
                {
                    "DetailType": "JournalEntryLineDetail",
                    "Amount": _money(line.debit if debit else line.credit),
                    "Description": line.description[:4000],
                    "JournalEntryLineDetail": detail,
                }
            )
        body: dict[str, Any] = {
            "TxnDate": doc.date,
            "CurrencyRef": {"value": doc.currency},
            "PrivateNote": doc.narration[:4000],
            "Line": lines,
        }
        if external_id:
            entry = self._read(creds, "JournalEntry", external_id)
            body.update(Id=external_id, SyncToken=entry["SyncToken"])
        result = self._call(creds, "POST", "/journalentry", body, key="" if external_id else key)
        return Pushed(str(result["JournalEntry"]["Id"]), created=not external_id)
