"""The real Xero and QuickBooks clients' requests (no network: ``http.request`` is
replaced), and the framework extensions E23 added (QuickBooks ``realmId`` on the OAuth
redirect, validation messages, provider-specific manage permissions)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from tutortrack.accounting.documents import InvoiceDoc, Line, PaymentDoc, PayoutDoc
from tutortrack.accounting.providers import quickbooks, xero
from tutortrack.integrations.providers import Credentials, http


class Recorder:
    def __init__(self, replies: dict[tuple[str, str], Any]):
        self.replies = replies
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> http.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        for (m, fragment), reply in self.replies.items():
            if m == method and fragment in url:
                return http.Response(200, None, json.dumps(reply).encode())  # type: ignore[arg-type]
        return http.Response(200, None, b"{}")  # type: ignore[arg-type]


CREDS = Credentials(access_token="t", account_id="tenant-1")
INVOICE = InvoiceDoc(
    kind="invoice",
    ref="ours",
    date="2026-10-01",
    currency="GBP",
    number="INV-000042",
    contact="c-1",
    due_date="2026-10-15",
    lines=(
        Line(
            description="Tuition",
            account="acc-200",
            account_code="200",
            net=Decimal("100.00"),
            tax=Decimal("20.00"),
            tax_code="OUTPUT2",
            tracking=(("trk", "opt"),),
        ),
    ),
    total=Decimal("120.00"),
)


def test_xero_invoice_is_an_authorised_accrec_with_an_idempotency_key(monkeypatch):
    recorder = Recorder({("PUT", "/Invoices"): {"Invoices": [{"InvoiceID": "x-inv"}]}})
    monkeypatch.setattr(http, "request", recorder)
    pushed = xero.XeroClient().push(CREDS, INVOICE, idempotency_key="tt-1")
    assert pushed.external_id == "x-inv"
    call = recorder.calls[0]
    assert call["headers"]["Xero-tenant-id"] == "tenant-1"
    assert call["headers"]["Idempotency-Key"] == "tt-1"
    body = call["json_body"]["Invoices"][0]
    assert (body["Type"], body["Status"], body["InvoiceNumber"]) == (
        "ACCREC",
        "AUTHORISED",
        "INV-000042",
    )
    line = body["LineItems"][0]
    assert (line["AccountCode"], line["TaxType"], line["LineAmount"]) == (
        "200",
        "OUTPUT2",
        "100.00",
    )
    assert line["Tracking"] == [{"TrackingCategoryID": "trk", "TrackingOptionID": "opt"}]


def test_xero_payment_splits_per_invoice_and_keeps_the_rest_as_an_overpayment(monkeypatch):
    recorder = Recorder(
        {
            ("PUT", "/Payments"): {"Payments": [{"PaymentID": "p-1"}]},
            ("PUT", "/BankTransactions"): {"BankTransactions": [{"OverpaymentID": "o-1"}]},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    doc = PaymentDoc(
        kind="payment",
        date="2026-10-02",
        currency="GBP",
        contact="c-1",
        account="acc-091",
        amount=Decimal("80.00"),
        reference="pi_1 INV-000042",
        allocations=(("x-inv", Decimal("50.00")),),
        unallocated=Decimal("30.00"),
    )
    pushed = xero.XeroClient().push(CREDS, doc, idempotency_key="tt-2")
    assert pushed.meta["parts"] == [["x-inv", "p-1", "50.00"], ["overpayment", "o-1", "30.00"]]
    overpayment = recorder.calls[1]["json_body"]["BankTransactions"][0]
    assert overpayment["Type"] == "RECEIVE-OVERPAYMENT"


def test_xero_payout_is_one_transfer_and_fees_spent_from_clearing(monkeypatch):
    recorder = Recorder(
        {
            ("PUT", "/BankTransfers"): {"BankTransfers": [{"BankTransferID": "bt-1"}]},
            ("GET", "/Contacts"): {"Contacts": [{"ContactID": "stripe"}]},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    doc = PayoutDoc(
        kind="provider_payout",
        date="2026-10-03",
        currency="GBP",
        reference="po_1",
        clearing_account="clr",
        bank_account="bank",
        fee_account="fees",
        net=Decimal("98.00"),
        fees=Decimal("2.00"),
    )
    assert xero.XeroClient().push(CREDS, doc, idempotency_key="tt-3").external_id == "bt-1"
    transfer = recorder.calls[0]["json_body"]["BankTransfers"][0]
    assert transfer["Amount"] == "98.00"
    spend = recorder.calls[-1]["json_body"]["BankTransactions"][0]
    assert (spend["Type"], spend["LineItems"][0]["LineAmount"]) == ("SPEND", "2.00")


def test_xero_dates_and_lock_date():
    assert xero.parse_date("/Date(1711843200000+0000)/") == date(2024, 3, 31)
    assert xero.parse_date("2026-03-31T00:00:00") == date(2026, 3, 31)
    assert xero.parse_date(None) is None


def test_quickbooks_invoice_posts_through_items_with_a_request_id(monkeypatch):
    recorder = Recorder(
        {
            ("GET", "/query"): {"QueryResponse": {}},
            ("POST", "/item"): {"Item": {"Id": "item-9"}},
            ("POST", "/invoice"): {"Invoice": {"Id": "qb-inv"}},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    pushed = quickbooks.QuickBooksClient().push(CREDS, INVOICE, idempotency_key="tt-4")
    assert pushed.external_id == "qb-inv"
    invoice_call = next(c for c in recorder.calls if c["url"].endswith("/invoice"))
    assert invoice_call["params"]["requestid"] == "tt-4"
    assert "/tenant-1/" in invoice_call["url"]
    body = invoice_call["json_body"]
    assert body["DocNumber"] == "INV-000042"
    detail = body["Line"][0]["SalesItemLineDetail"]
    assert detail["ItemRef"] == {"value": "item-9"}
    assert detail["TaxCodeRef"] == {"value": "OUTPUT2"}


def test_quickbooks_payout_is_a_deposit_with_a_negative_fee_line(monkeypatch):
    recorder = Recorder({("POST", "/deposit"): {"Deposit": {"Id": "dep-1"}}})
    monkeypatch.setattr(http, "request", recorder)
    doc = PayoutDoc(
        kind="provider_payout",
        date="2026-10-03",
        currency="GBP",
        reference="po_1",
        clearing_account="clr",
        bank_account="bank",
        fee_account="fees",
        net=Decimal("98.00"),
        fees=Decimal("2.00"),
    )
    quickbooks.QuickBooksClient().push(CREDS, doc, idempotency_key="tt-5")
    lines = recorder.calls[0]["json_body"]["Line"]
    assert [line["Amount"] for line in lines] == [100.0, -2.0]


def test_provider_validation_messages_are_kept():
    xero_body = json.dumps(
        {
            "Message": "A validation exception occurred",
            "Elements": [
                {
                    "ValidationErrors": [
                        {"Message": "Account code '200' has been archived, or has been deleted."}
                    ]
                }
            ],
        }
    ).encode()
    assert "Account code '200'" in http._message(xero_body, "x")
    qbo_body = json.dumps(
        {
            "Fault": {
                "Error": [{"Message": "Duplicate", "Detail": "Duplicate Document Number Error"}]
            }
        }
    ).encode()
    assert http._message(qbo_body, "x") == "Duplicate Document Number Error"


@pytest.mark.django_db
def test_the_oauth_callback_forwards_the_quickbooks_company(org):
    from tutortrack.core.testing import client_for
    from tutortrack.integrations import oauth

    token, _state = oauth.make_state(
        organisation_id=org.pk,
        user_id="u",
        provider="quickbooks",
        level="organisation",
        next_path="/settings/accounting",
    )
    response = client_for(org).get(
        "/api/v1/integrations/oauth/callback",
        {"code": "abc", "state": token, "realmId": "9130350"},
    )
    assert response.status_code == 302
    assert "account_id=9130350" in response["Location"]
    assert response["Location"].split("?")[0].endswith("/settings/accounting")
