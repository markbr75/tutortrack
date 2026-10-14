"""E23-T09: read-back of payments recorded directly in Xero or QuickBooks (FR-23-4): only
payments TutorTrack didn't send are imported, as E11 manual payments allocated to the
invoice, once; the sync engine never pushes them back; misfits are skipped with a reason;
the real clients' requests; API and isolation."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tutortrack.accounting import readback, services
from tutortrack.accounting.models import ExternalRecordLink, LedgerPaymentImport, SyncLogEntry
from tutortrack.accounting.providers import quickbooks, xero
from tutortrack.accounting.providers.fake import FakeLedger
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.integrations.providers import Credentials, http
from tutortrack.payments import services as payments
from tutortrack.payments.models import Payment

from .conftest import enabled, gbp, issue

pytestmark = pytest.mark.django_db


def ledger(conn) -> FakeLedger:
    return FakeLedger(conn.connection.external_account_id)


def synced_invoice(org, world, conn, amount="100.00"):
    invoice = issue(org, world, amount, vat=False)
    with tenant_context(org):
        assert services.sync("invoice", str(invoice.pk), inline=True) == "synced"
        external = ExternalRecordLink.objects.get(
            object_type="invoice", object_id=str(invoice.pk)
        ).external_id
    return invoice, external


def read_back(org, conn) -> dict[str, int]:
    with tenant_context(org):
        conn.refresh_from_db()
        return readback.read_back(conn)


@pytest.mark.parametrize("provider", ["xero", "quickbooks"])
def test_payment_recorded_in_the_ledger_is_imported_once(
    org, world, provider, django_capture_on_commit_callbacks
):
    conn = enabled(org, world, provider, import_payments=True)
    invoice, external = synced_invoice(org, world, conn)
    paid_id = ledger(conn).record_payment(external, "60.00", "2026-10-12", reference="BACS 991")
    result = read_back(org, conn)
    assert result == {"checked": 1, "imported": 1, "skipped": 0}
    with tenant_context(org):
        invoice.refresh_from_db()
        assert (invoice.status, invoice.balance_due) == ("partially_paid", gbp("40.00"))
        payment = Payment.objects.get(client=world["client"])
        assert (payment.amount, payment.method, payment.reference) == (
            gbp("60.00"),
            "bank_transfer",
            "BACS 991",
        )
        assert payment.received_at.date().isoformat() == "2026-10-12"
        record = LedgerPaymentImport.objects.get()
        assert (record.status, record.external_id, record.payment_id) == (
            "imported",
            paid_id,
            payment.pk,
        )
        payment_link = ExternalRecordLink.objects.get(
            object_type="payment", object_id=str(payment.pk)
        )
        assert (payment_link.status, payment_link.external_id) == ("synced", paid_id)
        assert SyncLogEntry.objects.filter(outcome="imported").count() == 1
        assert OutboxEvent.objects.filter(event_type="accounting.payment_imported").count() == 1
        # The sync engine must not post it back to the ledger.
        assert services.sync("payment", str(payment.pk), inline=True) == "synced"
    assert len(ledger(conn).records("payments")) == 1
    # Ledger and TutorTrack agree, and a second read-back changes nothing.
    assert ledger(conn).amount_due("invoices", external) == invoice.balance_due.amount
    assert read_back(org, conn) == {"checked": 1, "imported": 0, "skipped": 0}
    with tenant_context(org):
        assert Payment.objects.count() == 1


def test_payments_tutortrack_sent_are_not_imported(org, world):
    conn = enabled(org, world, import_payments=True)
    invoice, _external = synced_invoice(org, world, conn)
    with tenant_context(org):
        ours = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("30.00"),
            method="bank_transfer",
            allocations=[(invoice, gbp("30.00"))],
        )
        assert services.sync("payment", str(ours.pk), inline=True) == "synced"
    assert read_back(org, conn) == {"checked": 1, "imported": 0, "skipped": 0}
    with tenant_context(org):
        assert not LedgerPaymentImport.objects.exists()


def test_payments_that_do_not_fit_are_skipped_with_a_reason(org, world):
    conn = enabled(org, world, import_payments=True)
    _invoice, external = synced_invoice(org, world, conn, "50.00")
    with tenant_context(org):
        link = ExternalRecordLink.objects.get(external_id=external)
    # The ledger shows more paid than TutorTrack says is owed (bad data entry).
    over = ledger(conn).record_payment(external, "50.00", "2026-10-12")
    from tutortrack.accounting.providers.base import LedgerPayment

    bigger = LedgerPayment(id="pay-manual", amount="75.00", date="2026-10-12")
    with tenant_context(org):
        conn.refresh_from_db()
        assert readback.import_payment(conn, link, bigger) == "skipped"
        assert readback.import_payment(conn, link, bigger) == "skipped"  # idempotent
        skipped = LedgerPaymentImport.objects.get(external_id="pay-manual")
        assert "more than TutorTrack says is owed" in skipped.reason
        assert link.log.filter(outcome="skipped").exists()
        assert not Payment.objects.exists()
    assert read_back(org, conn)["imported"] == 1  # the 50.00 one fits exactly
    with tenant_context(org):
        assert LedgerPaymentImport.objects.get(external_id=over).status == "imported"


def test_read_back_is_off_unless_switched_on(org, world):
    conn = enabled(org, world)
    _invoice, external = synced_invoice(org, world, conn)
    ledger(conn).record_payment(external, "10.00", "2026-10-12")
    assert read_back(org, conn) == {"checked": 0, "imported": 0, "skipped": 0}
    response = world["api"].post(f"/api/v1/accounting/connections/{conn.pk}/read-back")
    assert response.status_code == 422


def test_daily_run_reads_back_before_reconciling(org, world):
    conn = enabled(org, world, import_payments=True)
    _invoice, external = synced_invoice(org, world, conn)
    ledger(conn).record_payment(external, "100.00", "2026-10-12")
    with tenant_context(org):
        result = services.daily(str(conn.pk))
    assert (result["imported"], result["drift"]) == (1, 0)


def test_api_check_now_and_list(org, world):
    api = world["api"]
    conn = enabled(org, world, import_payments=True)
    detail = api.get(f"/api/v1/accounting/connections/{conn.pk}").json()
    assert detail["import_payments"] is True
    _invoice, external = synced_invoice(org, world, conn)
    ledger(conn).record_payment(external, "25.00", "2026-10-12", reference="Cheque 12")
    checked = api.post(f"/api/v1/accounting/connections/{conn.pk}/read-back").json()
    assert checked == {"checked": 1, "imported": 1, "skipped": 0}
    rows = api.get("/api/v1/accounting/payment-imports").json()["results"]
    assert [(r["status"], r["reference"], r["amount"]["amount"]) for r in rows] == [
        ("imported", "Cheque 12", "25.00")
    ]
    assert (
        api.get("/api/v1/accounting/payment-imports", {"status": "skipped"}).json()["results"] == []
    )
    assert api.get(f"/api/v1/accounting/connections/{conn.pk}").json()["payments_checked_at"]
    from tutortrack.identity.tests.factories import MembershipFactory

    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/accounting/payment-imports").status_code == 403


class TestPaymentImportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/accounting/payment-imports"

    def make_object(self, organisation):
        from tutortrack.accounting.models import AccountingConnection
        from tutortrack.billing.models import Invoice
        from tutortrack.integrations.models import IntegrationConnection
        from tutortrack.people.tests.factories import ClientFactory

        with tenant_context(organisation):
            family = ClientFactory(organisation=organisation)
            invoice = Invoice.objects.create(client=family, currency="GBP", status="issued")
            framework = IntegrationConnection.objects.create(
                provider="xero", external_account_id=f"t-{organisation.slug}"
            )
            conn = AccountingConnection.objects.create(connection=framework, provider="xero")
            record = LedgerPaymentImport(
                connection=conn,
                provider="xero",
                external_id="pay-1",
                invoice=invoice,
                currency="GBP",
                status="skipped",
                reason="test",
                paid_on=now().date(),
            )
            record.amount = gbp("1.00")
            record.save()
            return record


# --- the real clients (no network) ---------------------------------------------------------------


class Recorder:
    def __init__(self, replies: list[tuple[str, Any]]):
        self.replies = replies
        self.calls: list[str] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> http.Response:
        self.calls.append(url)
        for fragment, reply in self.replies:
            if fragment in url:
                return http.Response(200, None, json.dumps(reply).encode())  # type: ignore[arg-type]
        return http.Response(200, None, b"{}")  # type: ignore[arg-type]


CREDS = Credentials(access_token="t", account_id="tenant-1")


def test_xero_reads_the_invoice_payments(monkeypatch):
    recorder = Recorder(
        [
            (
                "/Invoices/x-inv",
                {
                    "Invoices": [
                        {
                            "Payments": [
                                {
                                    "PaymentID": "p-1",
                                    "Date": "/Date(1760227200000+0000)/",
                                    "Amount": 60.0,
                                    "Reference": "BACS",
                                },
                                {"PaymentID": "p-2", "Amount": 5, "Status": "DELETED"},
                            ]
                        }
                    ]
                },
            )
        ]
    )
    monkeypatch.setattr(http, "request", recorder)
    [payment] = xero.XeroClient().invoice_payments(CREDS, "x-inv")
    assert (payment.id, payment.amount, payment.date, payment.reference) == (
        "p-1",
        "60.0",
        "2025-10-12",
        "BACS",
    )


def test_quickbooks_reads_linked_payments_and_the_amount_applied(monkeypatch):
    recorder = Recorder(
        [
            (
                "/invoice/q-inv",
                {"Invoice": {"Id": "q-inv", "LinkedTxn": [{"TxnId": "77", "TxnType": "Payment"}]}},
            ),
            (
                "/payment/77",
                {
                    "Payment": {
                        "Id": "77",
                        "TxnDate": "2026-10-12",
                        "PaymentRefNum": "CHQ 5",
                        "DepositToAccountRef": {"value": "35"},
                        "Line": [
                            {
                                "Amount": 40,
                                "LinkedTxn": [{"TxnId": "q-inv", "TxnType": "Invoice"}],
                            },
                            {
                                "Amount": 15,
                                "LinkedTxn": [{"TxnId": "other", "TxnType": "Invoice"}],
                            },
                        ],
                    }
                },
            ),
        ]
    )
    monkeypatch.setattr(http, "request", recorder)
    [payment] = quickbooks.QuickBooksClient().invoice_payments(CREDS, "q-inv")
    assert (payment.id, payment.amount, payment.date, payment.reference, payment.account) == (
        "77",
        "40",
        "2026-10-12",
        "CHQ 5",
        "35",
    )


def test_read_back_is_only_offered_for_ledgers_that_support_it(org, world):
    """Sage and FreeAgent (Phase 3) can't list an invoice's payments yet."""
    assert readback.supported("xero")
    assert readback.supported("quickbooks")
    assert not readback.supported("sage")
    assert not readback.supported("freeagent")
    conn = enabled(org, world)
    with tenant_context(org):
        type(conn).objects.filter(pk=conn.pk).update(provider="sage")
        conn.refresh_from_db()
        with pytest.raises(services.BusinessRuleViolation):
            services.update_options(conn, import_payments=True)
