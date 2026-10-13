"""E11 Phase 2: GoCardless (T11), PayPal (T12), bank statement import and Open Banking with
a matching queue (T13), split payments across clients (T14), provider migration and the
payment-at-booking hook."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from tutortrack.billing import services as billing
from tutortrack.billing.models import ClientLedgerEntry
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.payments import bank, provider_migration, services, statements
from tutortrack.payments.bank_feeds import set_transactions
from tutortrack.payments.models import (
    AccountRoute,
    BankTransaction,
    Dispute,
    Payment,
    PaymentGroup,
    ProviderAccount,
    ProviderMigration,
    ProviderPayout,
    ProviderWebhookEvent,
)
from tutortrack.payments.providers import get_provider
from tutortrack.payments.providers.base import MethodDetails
from tutortrack.payments.tasks import process_webhook
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db
HOST = f"{{slug}}.{settings.TENANT_BASE_DOMAIN}"


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), "GBP")


@pytest.fixture(autouse=True)
def fresh_providers():
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


@pytest.fixture
def finance(org):
    return client_for(org, MembershipFactory(organisation=org, role="finance").user)


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
    with tenant_context(org):
        client.billing_contact = contact
        client.save()
    student = StudentFactory(organisation=org, client=client)
    return {"client": client, "student": student}


def connected(org, provider, ref):
    with tenant_context(org):
        account = ProviderAccount.objects.create(
            provider=provider, account_ref=ref, status="active", charges_enabled=True,
            payouts_enabled=True, access_token="gc-token",
        )  # fmt: skip
        AccountRoute.objects.create(provider=provider, account_ref=ref, organisation_id=org.pk)
    return account


@pytest.fixture
def gocardless(org):
    return connected(org, "gocardless", "OR_live1")


@pytest.fixture
def paypal(org):
    return connected(org, "paypal", "MERCHANT1")


def issue(org, client, amount="40.00"):
    with tenant_context(org), transaction.atomic():
        billing.create_ad_hoc_charge(client=client, description="Tuition", unit_price=gbp(amount))
        return billing.issue_invoice(billing.create_draft(client), send=False)


def gc_webhook(api_client, *events, secret=b"fake-gocardless-secret"):
    body = json.dumps({"events": list(events)}).encode()
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return api_client.post(
        "/webhooks/gocardless",
        data=body,
        content_type="application/json",
        HTTP_WEBHOOK_SIGNATURE=signature,
    )


def gc_event(event_id, resource, action, **links):
    return {
        "id": event_id,
        "resource_type": resource,
        "action": action,
        "links": {"organisation": "OR_live1", **links},
        "details": {},
    }


def paypal_webhook(api_client, event_type, resource, *, event_id="WH-1", sig="fake-signature"):
    body = {"id": event_id, "event_type": event_type, "resource": resource}
    return api_client.post(
        "/webhooks/paypal",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_PAYPAL_TRANSMISSION_SIG=sig,
    )


def run_webhooks(org):
    with tenant_context(org):
        ids = list(
            ProviderWebhookEvent.objects.filter(processed_at__isnull=True).values_list(
                "pk", flat=True
            )
        )
    for pk in ids:
        process_webhook(organisation_id=str(org.pk), event_id=str(pk))


def query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# --- connecting (T11/T12) ---------------------------------------------------------------------


@pytest.mark.parametrize(("provider", "code_key"), [("gocardless", "code"),
                                                     ("paypal", "merchantIdInPayPal")])  # fmt: skip
def test_partner_connect_and_complete(org, finance, provider, code_key):
    started = finance.post(f"/api/v1/payments/providers/{provider}/connect", {}, format="json")
    assert started.status_code == 200, started.content
    back = query(started.json()["url"])
    assert started.json()["account"]["status"] == "pending"
    bad = finance.post(
        f"/api/v1/payments/providers/{provider}/complete",
        {"state": "forged", "code": back[code_key]},
        format="json",
    )
    assert bad.status_code == 422
    done = finance.post(
        f"/api/v1/payments/providers/{provider}/complete",
        {"state": back["state"], "code": back[code_key]},
        format="json",
    )
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "active"
    with tenant_context(org):
        account = ProviderAccount.objects.get(provider=provider)
        assert AccountRoute.objects.filter(provider=provider, account_ref=account.account_ref)
        assert account.connect_state == ""
    if provider == "gocardless":
        assert account.access_token.startswith("gc-token-")


# --- GoCardless mandates, collection, webhooks and payouts (T11) ------------------------------


def test_setup_link_saves_a_gocardless_mandate(org, finance, client, gocardless, family):
    created = finance.post(f"/api/v1/clients/{family['client'].pk}/payment-methods/setup-link")
    token = created.json()["url"].rsplit("/", 1)[1]
    host = HOST.format(slug=org.slug)
    page = client.get(f"/api/v1/pay/setup/{token}", HTTP_HOST=host).json()
    assert (page["provider"], page["providers"]) == ("gocardless", ["gocardless"])
    assert query(page["redirect_url"])["intent"] == page["intent"]
    done = client.post(
        f"/api/v1/pay/setup/{token}",
        {"intent": page["intent"], "autopay": True, "provider": "gocardless"},
        format="json",
        HTTP_HOST=host,
    )
    assert done.status_code == 200, done.content
    assert (done.json()["method"]["type"], done.json()["auto_pay"]) == ("bacs_debit", True)


def mandate(org, family, account, ref="MD_live1"):
    with tenant_context(org), transaction.atomic():
        method = services.save_method(
            family["client"], account, MethodDetails(ref, "bacs_debit", "", "1234",
                                                     mandate_status="active"))  # fmt: skip
        services.give_consent(family["client"], method, ip_address=None, user_agent="")
    return method


def test_gocardless_debit_is_pending_until_the_webhook_confirms(org, client, gocardless, family):
    mandate(org, family, gocardless)
    invoice = issue(org, family["client"])
    with tenant_context(org):
        assert services.attempt_collection(invoice.pk, 1, "collect-1") == "processing"
        payment = Payment.objects.get()
        assert (payment.provider, payment.status, payment.method) == (
            "gocardless", "pending", "direct_debit",
        )  # fmt: skip
    event = gc_event("EV1", "payments", "confirmed", payment=payment.provider_ref)
    assert gc_webhook(client, event).status_code == 200
    assert gc_webhook(client, event).status_code == 200  # redelivered: stored once
    run_webhooks(org)
    with tenant_context(org):
        payment.refresh_from_db()
        invoice.refresh_from_db()
        assert ProviderWebhookEvent.objects.filter(provider="gocardless").count() == 1
    assert (payment.status, invoice.status) == ("succeeded", "paid")


def test_gocardless_webhooks_need_the_signature(org, client, gocardless):
    event = gc_event("EV2", "payments", "confirmed", payment="PM1")
    assert gc_webhook(client, event, secret=b"wrong").status_code == 498


def test_failed_debit_and_cancelled_mandate(org, client, gocardless, family):
    method = mandate(org, family, gocardless)
    invoice = issue(org, family["client"])
    with tenant_context(org):
        services.attempt_collection(invoice.pk, 1, "collect-2")
        payment = Payment.objects.get()
    gc_webhook(
        client,
        gc_event("EV3", "payments", "failed", payment=payment.provider_ref),
        gc_event("EV4", "mandates", "cancelled", mandate=method.provider_ref),
    )
    run_webhooks(org)
    with tenant_context(org):
        payment.refresh_from_db()
        method.refresh_from_db()
        invoice.refresh_from_db()
        from tutortrack.core.models import OutboxEvent

        assert OutboxEvent.objects.filter(event_type="mandate.cancelled").exists()
    assert payment.status == "failed"
    assert (method.status, method.mandate_status) == ("removed", "cancelled")
    assert invoice.status == "issued"


def test_payouts_record_gocardless_fees_on_the_payments(org, client, gocardless, family):
    mandate(org, family, gocardless)
    invoice = issue(org, family["client"], "100.00")
    with tenant_context(org):
        services.attempt_collection(invoice.pk, 1, "collect-3")
        payment = Payment.objects.get()
    gc_webhook(client, gc_event("EV5", "payments", "confirmed", payment=payment.provider_ref))
    run_webhooks(org)
    fake = get_provider("gocardless")
    fake.add_payout("PO1", [payment.provider_ref])
    gc_webhook(client, gc_event("EV6", "payouts", "paid", payout="PO1"))
    run_webhooks(org)
    with tenant_context(org):
        payment.refresh_from_db()
        payout = ProviderPayout.objects.get()
    assert payment.fee == gbp("1.20")  # 1% + 20p
    assert payment.net == gbp("98.80")
    assert (payout.provider_ref, payout.amount) == ("PO1", gbp("98.80"))


def test_pay_page_bank_payment_with_gocardless(org, client, gocardless, family):
    invoice = issue(org, family["client"])
    host = HOST.format(slug=org.slug)
    page = client.get(f"/api/v1/pay/{invoice.pay_token}", HTTP_HOST=host).json()
    assert page["providers"] == ["gocardless"]
    started = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent",
        {"provider": "gocardless"},
        format="json",
        HTTP_HOST=host,
    ).json()
    assert query(started["redirect_url"])["intent"] == started["intent"]
    confirm = client.post(
        f"/api/v1/pay/{invoice.pay_token}/confirm",
        {"intent": started["intent"], "provider": "gocardless"},
        format="json",
        HTTP_HOST=host,
    )
    assert confirm.json() == {"status": "processing"}
    with tenant_context(org):
        payment = Payment.objects.get()
    gc_webhook(client, gc_event("EV7", "payments", "confirmed", payment=payment.provider_ref))
    run_webhooks(org)
    with tenant_context(org):
        invoice.refresh_from_db()
    assert invoice.status == "paid"


# --- PayPal (T12) -----------------------------------------------------------------------------


def test_paypal_checkout_is_captured_once_with_its_fee(org, client, paypal, family):
    invoice = issue(org, family["client"])
    host = HOST.format(slug=org.slug)
    started = client.post(
        f"/api/v1/pay/{invoice.pay_token}/intent",
        {"provider": "paypal"},
        format="json",
        HTTP_HOST=host,
    ).json()
    assert query(started["redirect_url"])["token"] == started["intent"]
    for _ in range(2):  # the page and a retry: one payment
        confirmed = client.post(
            f"/api/v1/pay/{invoice.pay_token}/confirm",
            {"intent": started["intent"], "provider": "paypal"},
            format="json",
            HTTP_HOST=host,
        )
        assert confirmed.json() == {"status": "succeeded"}
    with tenant_context(org):
        payment = Payment.objects.get()
        invoice.refresh_from_db()
    assert (payment.method, payment.provider, invoice.status) == ("paypal", "paypal", "paid")
    assert payment.fee == gbp("1.46")  # 2.9% + 30p
    with tenant_context(org), transaction.atomic():
        refund = services.refund_payment(payment, amount=gbp("10.00"), reason="Goodwill")
    assert refund.provider_ref.startswith("RF_")


def test_paypal_webhook_records_a_capture_the_page_missed(org, client, paypal, family):
    invoice = issue(org, family["client"])
    resource = {
        "id": "CAPWEB1",
        "amount": {"currency_code": "GBP", "value": "40.00"},
        "custom_id": f"invoice_id={invoice.pk}&organisation_id={org.pk}",
        "payee": {"merchant_id": "MERCHANT1"},
    }
    assert (
        paypal_webhook(client, "PAYMENT.CAPTURE.COMPLETED", resource, sig="bad").status_code == 400
    )
    assert paypal_webhook(client, "PAYMENT.CAPTURE.COMPLETED", resource).status_code == 200
    run_webhooks(org)
    with tenant_context(org):
        invoice.refresh_from_db()
    assert invoice.status == "paid"
    dispute = {
        "dispute_id": "PP-D-1",
        "disputed_transactions": [{"seller_transaction_id": "CAPWEB1"}],
        "dispute_amount": {"currency_code": "GBP", "value": "40.00"},
        "payee": {"merchant_id": "MERCHANT1"},
    }
    paypal_webhook(client, "CUSTOMER.DISPUTE.CREATED", dispute, event_id="WH-2")
    paypal_webhook(
        client,
        "CUSTOMER.DISPUTE.RESOLVED",
        {**dispute, "dispute_outcome": {"outcome_code": "RESOLVED_BUYER_FAVOUR"}},
        event_id="WH-3",
    )
    run_webhooks(org)
    with tenant_context(org):
        invoice.refresh_from_db()
        assert Dispute.objects.get().status == "lost"
    assert invoice.status == "issued"  # reopened


def test_paypal_cannot_be_saved_for_autopay(org, paypal, family):
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        services.start_setup(family["client"], provider="paypal")


# --- split payments (T14) ---------------------------------------------------------------------


def test_one_receipt_split_across_clients(org, finance, family):
    other = ClientFactory(organisation=org, display_name="The Okafors")
    first = issue(org, family["client"], "60.00")
    second = issue(org, other, "40.00")
    response = finance.post(
        "/api/v1/payments/split",
        {
            "payer_name": "Hillside School",
            "amount": {"amount": "110.00", "currency": "GBP"},
            "method": "bank_transfer",
            "reference": "HS-OCT",
            "parts": [
                {"client": str(family["client"].pk), "amount": "60.00"},
                {"client": str(other.pk), "amount": "50.00"},
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert len(body["payments"]) == 2
    with tenant_context(org):
        first.refresh_from_db()
        second.refresh_from_db()
        credit = ClientLedgerEntry.objects.filter(client=other, type="payment").get()
        group = PaymentGroup.objects.get()
        assert group.payments.count() == 2
    assert (first.status, second.status) == ("paid", "paid")
    assert credit.amount == gbp("-50.00")  # £10 stays as the Okafors' credit


def test_split_parts_must_add_up(org, finance, family):
    other = ClientFactory(organisation=org)
    response = finance.post(
        "/api/v1/payments/split",
        {"payer_name": "School", "amount": {"amount": "100.00", "currency": "GBP"},
         "method": "bank_transfer",
         "parts": [{"client": str(family["client"].pk), "amount": "60.00"},
                   {"client": str(other.pk), "amount": "30.00"}]},
        format="json",
    )  # fmt: skip
    assert response.status_code == 422


# --- bank statements and the matching queue (T13) ---------------------------------------------


CSV = (
    "Date,Description,Reference,Amount\n"
    "{day},FASTER PAYMENT PATEL,INV-000001,40.00\n"
    "{day},SCHOOL BACS,HILLSIDE,110.00\n"
    "{day},CARD FEES,,-12.50\n"
)


def upload(api, content, name="statement.csv", **extra):
    return api.post(
        "/api/v1/bank-reconciliation/imports",
        {"file": SimpleUploadedFile(name, content.encode()), **extra},
        format="multipart",
    )


def test_csv_import_suggests_invoice_matches_and_is_idempotent(org, finance, family):
    invoice = issue(org, family["client"])
    content = CSV.format(day=now().date().strftime("%d/%m/%Y"))
    imported = upload(finance, content)
    assert imported.status_code == 201, imported.content
    assert imported.json()["stats"] == {"rows": 3, "new": 3, "duplicates": 0, "suggested": 1,
                                        "auto_matched": 0}  # fmt: skip
    again = upload(finance, content).json()
    assert (again["stats"]["new"], again["stats"]["duplicates"]) == (0, 3)
    queue = finance.get("/api/v1/bank-reconciliation/transactions", {"status": "suggested"}).json()
    [line] = queue["results"]
    [match] = line["matches"]
    assert (match["kind"], match["score"], match["invoice_number"]) == (
        "invoice",
        100,
        "INV-000001",
    )
    done = finance.post(
        f"/api/v1/bank-reconciliation/transactions/{line['id']}/confirm",
        {"match": match["id"]},
        format="json",
    )
    assert done.status_code == 200, done.content
    assert done.json()["status"] == "matched"
    with tenant_context(org):
        invoice.refresh_from_db()
        payment = Payment.objects.get()
    assert invoice.status == "paid"
    assert (payment.method, payment.reference) == ("bank_transfer", "INV-000001")


def test_bank_line_split_between_clients_and_ignore(org, finance, family):
    other = ClientFactory(organisation=org)
    upload(finance, CSV.format(day=now().date().isoformat()))
    with tenant_context(org):
        school = BankTransaction.objects.get(amount_amount=Decimal("110.00"))
        fees = BankTransaction.objects.get(amount_amount=Decimal("-12.50"))
    split = finance.post(
        f"/api/v1/bank-reconciliation/transactions/{school.pk}/split",
        {"parts": [{"client": str(family["client"].pk), "amount": "70.00"},
                   {"client": str(other.pk), "amount": "40.00"}]},
        format="json",
    )  # fmt: skip
    assert split.status_code == 200, split.content
    assert split.json()["payment_group"]
    ignored = finance.post(f"/api/v1/bank-reconciliation/transactions/{fees.pk}/ignore")
    assert ignored.json()["status"] == "ignored"
    reopened = finance.post(f"/api/v1/bank-reconciliation/transactions/{fees.pk}/reopen")
    assert reopened.json()["status"] == "unmatched"


def test_payouts_and_recorded_payments_are_suggested(org, family, gocardless):
    today = now().date()
    with tenant_context(org):
        payout = ProviderPayout.objects.create(
            account=gocardless, provider_ref="PO9", currency="GBP", amount=gbp("98.80"),
            status="paid", arrival_date=today,
        )  # fmt: skip
        services.record_manual_payment(
            client=family["client"], amount=gbp("25.00"), method="bank_transfer"
        )
        parsed = statements.Parsed(rows=[
            statements.Row(today, Decimal("98.80"), "GOCARDLESS PAYOUT"),
            statements.Row(today, Decimal("25.00"), "PATEL"),
        ])  # fmt: skip
        with transaction.atomic():
            bank.import_rows(parsed, source="csv", currency="GBP")
        kinds = {
            t.amount.amount: [m.kind for m in t.matches.all()]
            for t in BankTransaction.objects.all()
        }
        line = BankTransaction.objects.get(amount_amount=Decimal("98.80"))
        with transaction.atomic():
            bank.confirm(line, line.matches.get())
        line.refresh_from_db()
    assert kinds == {Decimal("98.80"): ["payout"], Decimal("25.00"): ["payment"]}
    assert line.payout_id == payout.pk


def test_ofx_and_camt_parsing():
    ofx = b"""OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>GBP<BANKACCTFROM><ACCTID>12345678
<BANKTRANLIST><STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261005120000<TRNAMT>40.00<FITID>F1
<NAME>PATEL<MEMO>INV-000001</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261006<TRNAMT>-5.00<FITID>F2<NAME>FEE</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    parsed = statements.parse("ofx", ofx)
    assert [(r.amount, r.external_id) for r in parsed.rows] == [
        (Decimal("40.00"), "ofx:F1"), (Decimal("-5.00"), "ofx:F2"),
    ]  # fmt: skip
    assert parsed.currency == "GBP"
    camt = b"""<?xml version="1.0"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
<Acct><Id><IBAN>GB00TEST12345678</IBAN></Id><Ccy>EUR</Ccy></Acct>
<Ntry><Amt Ccy="EUR">55.50</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-10-05</Dt></BookgDt>
<AcctSvcrRef>REF1</AcctSvcrRef><NtryDtls><TxDtls><RmtInf><Ustrd>INV-000002</Ustrd></RmtInf>
<RltdPties><Dbtr><Nm>J SMITH</Nm></Dbtr></RltdPties></TxDtls></NtryDtls></Ntry>
</Stmt></BkToCstmrStmt></Document>"""
    [row] = statements.parse("camt", camt).rows
    assert (row.amount, row.currency, row.reference, row.counterparty) == (
        Decimal("55.50"), "EUR", "INV-000002", "J SMITH",
    )  # fmt: skip
    with pytest.raises(statements.StatementError):
        statements.parse("camt", b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')
    assert statements.detect("x.qfx", b"") == "ofx"
    us = statements.parse_csv(b"Date,Amount,Description\n10/05/2026,1.234,X\n", month_first=True)
    assert us.rows[0].booked_on.month == 10


def test_open_banking_feed_imports_and_matches(org, family):
    from tutortrack.integrations import services as integrations

    invoice = issue(org, family["client"])
    set_transactions("acc-1", [{
        "transactionId": "t-1", "bookingDate": now().date().isoformat(),
        "transactionAmount": {"amount": "40.00", "currency": "GBP"},
        "remittanceInformationUnstructured": f"PAYMENT {invoice.number}", "debtorName": "PATEL",
    }])  # fmt: skip
    with tenant_context(org):
        user = MembershipFactory(organisation=org, role="owner").user
        connection = integrations.connect_with_credentials(
            user, provider="open_banking", level="organisation", username="acc-1",
            api_key="secret-id:secret-key",
        )  # fmt: skip
        with transaction.atomic():
            statement = bank.sync_feed(connection.pk)
        line = BankTransaction.objects.get()
    assert statement.source == "open_banking"
    assert (line.status, line.external_id) == ("suggested", "ob:t-1")


class TestBankTransactionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/bank-reconciliation/transactions"

    def make_object(self, organisation):
        with tenant_context(organisation), transaction.atomic():
            statement = bank.import_rows(
                statements.Parsed(rows=[statements.Row(now().date(), Decimal("1"), "x")]),
                source="csv",
                currency="GBP",
            )
            return statement.transactions.get()


class TestBankImportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/bank-reconciliation/imports"

    def make_object(self, organisation):
        with tenant_context(organisation), transaction.atomic():
            return bank.import_rows(statements.Parsed(), source="csv", currency="GBP")


# --- provider migration and the booking hook --------------------------------------------------


def test_provider_migration_steps(org, finance, gocardless, family):
    stripe = connected(org, "stripe", "acct_1")
    with tenant_context(org), transaction.atomic():
        old = services.save_method(
            family["client"], stripe, MethodDetails("pm_card_visa", "card", "visa", "4242")
        )
    response = finance.post(
        f"/api/v1/clients/{family['client'].pk}/provider-migration",
        {"to_provider": "gocardless"},
        format="json",
    )
    assert response.status_code == 201, response.content
    migration_id = response.json()["id"]
    again = finance.post(
        f"/api/v1/clients/{family['client'].pk}/provider-migration",
        {"to_provider": "gocardless"},
        format="json",
    )
    assert again.status_code == 422
    with tenant_context(org):
        assert provider_migration.send_link(migration_id, key="k1")
        assert "/pay/setup/" in mail.outbox[-1].body
        new = mandate(org, family, gocardless)
        assert provider_migration.switch_default(migration_id, str(new.pk))
        assert provider_migration.in_flight(migration_id) == 0
        assert provider_migration.finish(migration_id, "completed") == "completed"
        old.refresh_from_db()
        new.refresh_from_db()
        migration = ProviderMigration.objects.get(pk=migration_id)
    assert (old.status, new.is_default, migration.status) == ("removed", True, "completed")


def test_booking_payment_hook_returns_a_pay_link(org, family):
    with tenant_context(org):
        out = services.request_booking_payment(
            client=family["client"], amount=gbp("45.00"), description="Trial lesson"
        )
    assert out["pay_url"].endswith(out["pay_token"])
    assert out["amount"] == gbp("45.00")


def test_accounting_and_pay_page_know_the_new_providers(org, gocardless, paypal):
    from tutortrack.accounting.api.views import _keys

    with tenant_context(org):
        clearing = {k["key"] for k in _keys()["clearing_keys"]}
        assert services.pay_providers(None) == ["gocardless", "paypal"]
        assert services.setup_providers(None) == ["gocardless"]
    assert {"provider:gocardless", "provider:paypal", "method:paypal"} <= clearing
