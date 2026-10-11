"""E23-T01..T08: connection and mappings, the sync engine (ordering, idempotency, status,
readable errors, lock dates, rate limits), Xero and QuickBooks documents (contacts,
invoices, credit notes, payments, refunds, payouts and fees, tutor bills and payouts),
summary journals, the sync dashboard API and GL exports."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest

from tutortrack.accounting import errors, ratelimit, services
from tutortrack.accounting.models import AccountingConnection, ExternalRecordLink, SyncLogEntry
from tutortrack.accounting.providers.fake import FakeLedger
from tutortrack.billing import services as billing
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import AuthError, RateLimited
from tutortrack.payments import services as payments
from tutortrack.payments.models import ProviderPayout

from .conftest import connect, enabled, gbp, issue, map_all

pytestmark = pytest.mark.django_db


def ledger(conn: AccountingConnection) -> FakeLedger:
    with tenant_context(conn.organisation_id):
        account = IntegrationConnection.objects.get(pk=conn.connection_id).external_account_id
    return FakeLedger(account)


def last_log(org, found: ExternalRecordLink) -> SyncLogEntry:
    with tenant_context(org):
        return found.log.first()


def today(org):
    with tenant_context(org):
        return billing.org_today()


def link(org, object_type: str, object_id) -> ExternalRecordLink:
    with tenant_context(org):
        return ExternalRecordLink.objects.get(object_type=object_type, object_id=str(object_id))


def sync(org, object_type: str, object_id) -> str:
    with tenant_context(org):
        return services.sync(object_type, str(object_id), inline=True)


def balance_matches(org, conn, invoice) -> None:
    with tenant_context(org):
        invoice.refresh_from_db()
    external = link(org, "invoice", invoice.pk).external_id
    assert ledger(conn).amount_due("invoices", external) == invoice.balance_due.amount


# --- connection and mappings (T02, T05) -----------------------------------------------------------


@pytest.mark.parametrize("provider", ["xero", "quickbooks"])
def test_connecting_fetches_the_chart_and_needs_complete_mappings(org, world, provider):
    """FR-23-1: OAuth connect per organisation, chart/tax/tracking fetched, and sync can't
    be switched on until the mappings are complete."""
    conn = connect(org, world, provider)
    api = world["api"]
    detail = api.get(f"/api/v1/accounting/connections/{conn.pk}").json()
    assert detail["provider"] == provider
    assert detail["simulated"] is True
    assert "demo company" in detail["company_name"]
    assert detail["base_currency"] == "GBP"
    chart = api.get(f"/api/v1/accounting/connections/{conn.pk}/chart").json()
    assert {"200", "091", "404"} <= {a["code"] for a in chart["accounts"]}
    assert "OUTPUT2" in {t["id"] for t in chart["tax_codes"]}
    assert chart["tracking"][0]["name"] == "Branch"
    kinds = {p["kind"] for p in detail["problems"]}
    assert {"revenue", "clearing", "bank", "fees", "tax"} <= kinds
    refused = api.post(f"/api/v1/accounting/connections/{conn.pk}/enable", {}, format="json")
    assert refused.status_code == 422
    assert refused.json()["errors"]["mappings"]
    mapping = map_all(org, world, provider)
    assert mapping["problems"] == []
    ok = api.post(f"/api/v1/accounting/connections/{conn.pk}/enable", {}, format="json").json()
    assert ok["enabled"] is True
    assert ok["start_date"] == str(today(org))
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="enable").exists()


def test_mapping_an_unknown_account_is_refused_and_archived_accounts_are_flagged(org, world):
    conn = connect(org, world)
    bad = world["api"].put(
        "/api/v1/accounting/mappings/xero",
        {
            "accounts": [{"kind": "revenue", "key": "default", "external_id": "nope"}],
            "taxes": [],
            "tracking": [],
        },
        format="json",
    )
    assert bad.status_code == 422
    map_all(org, world)
    ledger(conn).archive("200")
    world["api"].post(f"/api/v1/accounting/connections/{conn.pk}/refresh")
    detail = world["api"].get(f"/api/v1/accounting/connections/{conn.pk}").json()
    assert any("archived" in p["message"] for p in detail["problems"])


def test_only_finance_and_admins_connect_ledgers(org, world):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    response = client_for(org, coordinator).post(
        "/api/v1/integrations/oauth/start",
        {"provider": "xero", "level": "organisation", "next": "/settings/accounting"},
        format="json",
    )
    assert response.status_code == 403
    assert client_for(org, coordinator).get("/api/v1/accounting/connections").status_code == 403


def test_disconnecting_switches_sync_off(org, world):
    conn = enabled(org, world)
    response = world["api"].post(f"/api/v1/accounting/connections/{conn.pk}/disconnect")
    assert response.status_code == 200
    from tutortrack.core.events.dispatcher import dispatch_batch

    with tenant_context(org):
        event = OutboxEvent.objects.get(event_type="integration.disconnected")
    from tutortrack.accounting import handlers
    from tutortrack.core.events import EventEnvelope

    with tenant_context(org):
        handlers.disconnected(EventEnvelope.from_payload(event.payload))
        conn.refresh_from_db()
        assert conn.enabled is False
        assert services.active_connection() is None
    assert dispatch_batch is not None


# --- the AC: invoice, part card payment with a fee, refund, payout --------------------------------


@pytest.mark.parametrize("provider", ["xero", "quickbooks"])
def test_invoice_payment_refund_and_payout_keep_the_ledger_balance_in_step(org, world, provider):
    """AC FR-23-3: an invoice issued, part-paid by card (with a Stripe fee) and then
    refunded produces one invoice, one payment, one refund and fee entries on payout,
    with the ledger's invoice balance matching TutorTrack's at each step."""
    conn = enabled(org, world, provider)
    invoice = issue(org, world, "100.00")
    assert sync(org, "invoice", invoice.pk) == "synced"
    assert link(org, "contact", world["client"].pk).status == "synced"  # contact first
    balance_matches(org, conn, invoice)
    record = ledger(conn).get("invoices", link(org, "invoice", invoice.pk).external_id)
    assert record["number"] == invoice.number  # invoice numbers preserved
    assert Decimal(record["total"]) == invoice.total.amount
    with tenant_context(org):
        payment = payments.record_provider_payment(
            account=world["account"],
            client=world["client"],
            amount=gbp("60.00"),
            provider_ref="pi_e23",
            invoice=invoice,
            fee=gbp("1.45"),
        )
    assert sync(org, "payment", payment.pk) == "synced"
    balance_matches(org, conn, invoice)
    with tenant_context(org):
        refund = payments.refund_payment(payment, amount=gbp("20.00"), reason="Missed lesson")
    assert sync(org, "refund", refund.pk) == "synced"
    balance_matches(org, conn, invoice)
    with tenant_context(org):
        invoice.refresh_from_db()
        assert invoice.balance_due == gbp("80.00")
        payout = ProviderPayout.objects.create(
            account=world["account"],
            provider_ref="po_e23",
            currency="GBP",
            amount=gbp("38.55"),
            status="paid",
            arrival_date=billing.org_today(),
        )
    assert sync(org, "provider_payout", payout.pk) == "synced"
    books = ledger(conn)
    assert len(books.records("invoices")) == 1
    assert len(books.records("payments")) == 1
    assert len(books.records("refunds")) == 1
    assert [t["amount"] for t in books.records("transfers")] == ["38.55"]  # one bank line
    assert [s["amount"] for s in books.records("spend")] == ["1.45"]  # the fee
    paid = books.records("payments")[0]
    assert invoice.number in paid["reference"]  # FR-23-4: references carry invoice numbers
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="accounting.sync_succeeded").count() == 5


def test_syncing_again_is_a_no_op_and_changes_update(org, world):
    conn = enabled(org, world)
    invoice = issue(org, world)
    assert sync(org, "invoice", invoice.pk) == "synced"
    calls = ledger(conn).calls
    assert sync(org, "invoice", invoice.pk) == "synced"
    assert sync(org, "contact", world["client"].pk) == "synced"
    assert ledger(conn).calls == calls  # unchanged hash: nothing sent
    with tenant_context(org):
        client = world["client"]
        client.display_name = "The Patel Family"
        client.save()
    assert sync(org, "contact", client.pk) == "synced"
    contact = ledger(conn).get("contacts", link(org, "contact", client.pk).external_id)
    assert contact["name"] == "The Patel Family"
    with tenant_context(org):
        assert link(org, "contact", client.pk).log.filter(outcome="updated").exists()


def test_client_credit_applied_to_a_later_invoice(org, world):
    conn = enabled(org, world)
    first = issue(org, world, "50.00", vat=False)
    assert sync(org, "invoice", first.pk) == "synced"
    with tenant_context(org):
        overpaid = payments.record_manual_payment(
            client=world["client"], amount=gbp("80.00"), method="bank_transfer", reference="BACS"
        )
    assert sync(org, "payment", overpaid.pk) == "synced"
    contact = ledger(conn).get("contacts", link(org, "contact", world["client"].pk).external_id)
    assert Decimal(contact["credit"]) == Decimal("30.00")  # unallocated → overpayment
    with tenant_context(org):
        from tutortrack.tenancy import settings_service

        settings_service.update_settings("billing", {"billing.auto_apply_credit": True})
    second = issue(org, world, "20.00", vat=False)
    assert sync(org, "invoice", second.pk) == "synced"
    balance_matches(org, conn, second)
    balance_matches(org, conn, first)


def test_credit_note_and_write_off(org, world):
    conn = enabled(org, world)
    invoice = issue(org, world, "100.00")
    sync(org, "invoice", invoice.pk)
    with tenant_context(org):
        note = billing.create_credit_note(
            invoice,
            reason="Lesson cancelled",
            lines=[{"line": invoice.lines.get(), "amount": gbp("60.00")}],
        )
    assert sync(org, "credit_note", note.pk) == "synced"
    balance_matches(org, conn, invoice)
    with tenant_context(org):
        billing.write_off(invoice, reason="Family moved away")
    assert sync(org, "write_off", invoice.pk) == "synced"
    balance_matches(org, conn, invoice)
    notes = {r["kind"]: r for r in ledger(conn).records("credit_notes")}
    assert set(notes) == {"credit_note", "write_off"}
    assert Decimal(notes["write_off"]["total"]) == Decimal("60.00")


def test_voided_invoice_is_voided_in_the_ledger(org, world):
    conn = enabled(org, world)
    invoice = issue(org, world)
    sync(org, "invoice", invoice.pk)
    with tenant_context(org):
        billing.void_invoice(invoice, reason="Wrong family")
    assert sync(org, "invoice", invoice.pk) == "synced"
    record = ledger(conn).get("invoices", link(org, "invoice", invoice.pk).external_id)
    assert record["status"] == "VOIDED"
    assert last_log(org, link(org, "invoice", invoice.pk)).outcome == "voided"


# --- errors, retry, skip, lock dates, rate limits (T01, T07) --------------------------------------


def test_archived_account_is_a_readable_error_until_remapped(org, world):
    conn = enabled(org, world)
    invoice = issue(org, world)
    ledger(conn).archive("200")
    assert sync(org, "invoice", invoice.pk) == "error"
    failed = link(org, "invoice", invoice.pk)
    assert failed.status == "error"
    assert failed.error_code == "account_archived"
    assert failed.error.startswith("Account code 200 is archived in Xero")
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="accounting.sync_failed").count() == 1
    rows = world["api"].get("/api/v1/accounting/records?status=error").json()["results"]
    assert [r["object_id"] for r in rows] == [str(invoice.pk)]
    # re-map and retry
    world["api"].put(
        "/api/v1/accounting/mappings/xero",
        {
            **_mapping_body(world),
            "accounts": [
                *[a for a in _mapping_body(world)["accounts"] if a["kind"] != "revenue"],
                {"kind": "revenue", "key": "default", "external_id": "acc-210"},
            ],
        },
        format="json",
    )
    retried = world["api"].post(f"/api/v1/accounting/records/{failed.pk}/retry").json()
    assert retried["status"] == "pending"
    assert sync(org, "invoice", invoice.pk) == "synced"


def _mapping_body(world) -> dict:
    from .conftest import ACCOUNTS

    return {
        "accounts": [{"kind": k, "key": key, "external_id": e} for k, key, e in ACCOUNTS],
        "taxes": [
            {"tax_rate": None, "external_id": "NONE"},
            {"tax_rate": str(world["vat"].pk), "external_id": "OUTPUT2"},
        ],
        "tracking": [],
    }


def test_missing_mapping_waits_and_dependents_say_so(org, world):
    conn = enabled(org, world)
    with tenant_context(org):
        from tutortrack.accounting.models import TaxMapping

        TaxMapping.objects.filter(tax_rate=world["vat"]).delete()
    invoice = issue(org, world)
    assert sync(org, "invoice", invoice.pk) == "error"
    assert link(org, "invoice", invoice.pk).error_code == "tax_mapping_missing"
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"], amount=gbp("10.00"), method="cash"
        )
    assert sync(org, "payment", payment.pk) == "synced"  # paid nothing synced: credit
    assert conn.enabled


def test_skip_from_the_dashboard(org, world):
    enabled(org, world)
    invoice = issue(org, world)
    with tenant_context(org):
        services.record_error("invoice", str(invoice.pk), "Entered in Xero by hand")
    record = link(org, "invoice", invoice.pk)
    response = world["api"].post(
        f"/api/v1/accounting/records/{record.pk}/skip",
        {"reason": "Already in Xero"},
        format="json",
    )
    assert response.json()["status"] == "skipped"
    assert sync(org, "invoice", invoice.pk) == "skipped"  # stays out
    detail = world["api"].get(f"/api/v1/accounting/records/{record.pk}").json()
    assert detail["log"][0]["outcome"] == "skipped"


def test_drafts_and_records_before_the_start_date_are_skipped(org, world):
    enabled(org, world, start_date=str(today(org) + timedelta(days=1)))
    invoice = issue(org, world)
    assert sync(org, "invoice", invoice.pk) == "skipped"
    assert "start date" in link(org, "invoice", invoice.pk).error
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=world["client"], description="Books", unit_price=gbp("5.00")
        )
        draft = billing.create_draft(world["client"])
    assert sync(org, "invoice", draft.pk) == "skipped"


@pytest.mark.parametrize("behaviour", ["post_to_open", "hold"])
def test_lock_dates(org, world, behaviour):
    """FR-23-3: a locked period posts on the first open date with a note, or holds."""
    conn = enabled(org, world, lock_behaviour=behaviour)
    day = today(org)
    with tenant_context(org):
        AccountingConnection.objects.filter(pk=conn.pk).update(lock_date=day)
    invoice = issue(org, world)
    result = sync(org, "invoice", invoice.pk)
    found = link(org, "invoice", invoice.pk)
    if behaviour == "hold":
        assert result == "error"
        assert found.error_code == "period_locked"
    else:
        assert result == "synced"
        assert found.posted_date == day + timedelta(days=1)
        assert "period locked" in last_log(org, found).message


def test_period_locked_in_the_ledger_is_explained(org, world):
    conn = enabled(org, world)
    ledger(conn).set_lock_date(today(org))
    invoice = issue(org, world)
    assert sync(org, "invoice", invoice.pk) == "error"
    assert link(org, "invoice", invoice.pk).error == "The accounting period is locked in Xero."


def test_transient_failures_raise_for_retry_and_revoked_access_needs_reconnecting(org, world):
    from tutortrack.integrations.providers import ProviderError, fake

    conn = enabled(org, world)
    invoice = issue(org, world)
    fake.fail("xero", 1)
    with tenant_context(org), pytest.raises(ProviderError):
        services.sync("invoice", str(invoice.pk), inline=True)
    assert last_log(org, link(org, "contact", world["client"].pk)).outcome == "retrying"
    fake.revoke(conn.connection.external_account_id)
    assert sync(org, "invoice", invoice.pk) == "error"
    assert link(org, "contact", world["client"].pk).error_code == "reconnect"
    with tenant_context(org):
        assert IntegrationConnection.objects.get(pk=conn.connection_id).status == "needs_reconnect"


def test_our_rate_limit_budget():
    for _ in range(3):
        ratelimit.acquire("acct-1", 3)
    with pytest.raises(RateLimited) as exc:
        ratelimit.acquire("acct-1", 3)
    assert 0 < exc.value.retry_after <= 61


def test_error_explanations():
    assert errors.explain("xero", AuthError("revoked")).code == "reconnect"
    assert errors.explain("quickbooks", RateLimited("slow")).retryable is True
    from tutortrack.integrations.providers import Rejected

    explained = errors.explain("xero", Rejected("The TaxType code 'OUTPUT9' does not exist."))
    assert explained.code == "tax_code"
    assert "OUTPUT9" in explained.message
    assert errors.explain("quickbooks", Rejected("Duplicate Document Number Error")).code == (
        "duplicate"
    )


# --- tutor bills and payouts (T04) ----------------------------------------------------------------


def _pay_run(org, w, *, employment="self_employed", vat=False):
    from tutortrack.payroll import services as payroll
    from tutortrack.people.tests.factories import TutorProfileFactory

    with tenant_context(org):
        tutor = TutorProfileFactory(
            organisation=org, status="active", first_name="Nia", employment_type=employment
        )
        if vat:
            payroll.update_profile(tutor, vat_registered=True, vat_number="GB123456789")
            payroll.agree_self_billing(tutor)
        payroll.create_manual_item(
            tutor=tutor,
            kind="bonus",
            description="Exam season",
            amount=gbp("120.00"),
            day=now().date(),
        )
        run, _ = payroll.create_pay_run(
            period_start=now().date() - timedelta(days=30),
            period_end=now().date(),
            start_workflow=False,
        )
        payroll.assemble(run.pk)
        run = payroll.approve(run, user=w["finance"])
        payroll.issue_statements(run.pk)
        payout = run.payouts.get()
    return run, payout, tutor


def test_tutor_bills_and_bill_payments(org, world):
    conn = enabled(org, world)
    run, payout, tutor = _pay_run(org, world, vat=True)
    assert sync(org, "pay_run", run.pk) == "synced"
    bill_link = link(org, "bill", payout.pk)
    assert link(org, "supplier", tutor.pk).status == "synced"
    bill = ledger(conn).get("bills", bill_link.external_id)
    assert bill["number"].startswith("SB-")  # the self-billing invoice number
    assert Decimal(bill["total"]) == Decimal("144.00")  # 120 + 20% VAT
    with tenant_context(org):
        from tutortrack.payroll import services as payroll

        payroll.mark_paid(run, reference="BACS 31 Oct")
    assert sync(org, "bill_payment", payout.pk) == "synced"
    assert ledger(conn).amount_due("bills", bill_link.external_id) == Decimal("24.00")


def test_employees_are_not_billed(org, world):
    enabled(org, world)
    _run, payout, _tutor = _pay_run(org, world, employment="employee")
    assert sync(org, "bill", payout.pk) == "skipped"
    assert "payroll" in link(org, "bill", payout.pk).error


# --- summary journals and backfill helpers (T06) -------------------------------------------------


def test_summary_mode_posts_a_balanced_daily_journal(org, world):
    conn = enabled(org, world, mode="summary")
    invoice = issue(org, world, "100.00")
    with tenant_context(org):
        payments.record_provider_payment(
            account=world["account"],
            client=world["client"],
            amount=gbp("50.00"),
            provider_ref="pi_sum",
            invoice=invoice,
            fee=gbp("1.00"),
        )
    assert sync(org, "invoice", invoice.pk) == "skipped"  # not individually
    with tenant_context(org):
        result = services.daily(str(conn.pk), billing.org_today())
    assert result["journal"] == "synced"
    (journal,) = ledger(conn).records("journals")
    debit = sum(Decimal(str(x["debit"])) for x in journal["lines"])
    credit = sum(Decimal(str(x["credit"])) for x in journal["lines"])
    assert debit == credit == Decimal("171.00")  # 120 invoice + 50 payment + 1 fee
    by_account = {x["account"]: x for x in journal["lines"] if x["credit"]}
    assert Decimal(str(by_account["acc-200"]["credit"])) == Decimal("100.00")
    assert Decimal(str(by_account["acc-820"]["credit"])) == Decimal("20.00")


def test_backfill_batches_are_resumable(org, world):
    conn = enabled(org, world, start_date=str(today(org) + timedelta(days=1)))
    invoices = issue(org, world, n=3)
    since = now().date() - timedelta(days=1)
    with tenant_context(org):
        first = services.backfill_batch(str(conn.pk), since, {}, 2)
        assert (first["done"], first["synced"]) == (False, 2)
        rest = services.backfill_batch(str(conn.pk), since, first["checkpoint"], 10)
        assert rest["done"] is True
        assert (
            ExternalRecordLink.objects.filter(object_type="invoice", status="synced").count() == 3
        )
        again = services.backfill_batch(str(conn.pk), since, {}, 10)
    assert again["synced"] == 3  # already in the ledger: no-ops
    assert len(ledger(conn).records("invoices")) == len(invoices)


def test_reconciliation_flags_payments_recorded_in_the_ledger_and_digests_errors(
    org, world, django_capture_on_commit_callbacks
):
    from tutortrack.comms.models import InAppNotification

    conn = enabled(org, world)
    invoice = issue(org, world)
    sync(org, "invoice", invoice.pk)
    external = link(org, "invoice", invoice.pk).external_id
    from tutortrack.accounting.providers import fake as fake_ledger

    state = fake_ledger._load(conn.connection.external_account_id)
    state["records"]["invoices"][external]["amount_due"] = "0"
    fake_ledger._save(conn.connection.external_account_id, state)
    other = issue(org, world)
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        services.record_error("invoice", str(other.pk), "Account code 200 is archived in Xero.")
        result = services.daily(str(conn.pk))
    assert result["drift"] == 1
    assert result["digest"] is True
    with tenant_context(org):
        assert link(org, "invoice", invoice.pk).log.filter(outcome="error").exists()
        assert SyncLogEntry.objects.count() >= 2
        note = InAppNotification.objects.get(user=world["finance"])
        assert "didn't sync to Xero" in note.title


# --- GL exports (T08) -----------------------------------------------------------------------------


def _export(world, fmt: str):
    today = now().date()
    response = world["api"].get(
        "/api/v1/accounting/export",
        {
            "file_format": fmt,
            "start": str(today - timedelta(days=1)),
            "end": str(today + timedelta(days=1)),
            "mapping_set": "export",
        },
    )
    return response


@pytest.fixture
def export_codes(org, world):
    body = {
        "accounts": [
            {"kind": kind, "key": "default", "external_id": code}
            for kind, code in (
                ("revenue", "4000"),
                ("clearing", "1210"),
                ("bank", "1200"),
                ("fees", "7900"),
                ("tutor_cost", "5000"),
                ("bad_debt", "8100"),
                ("rounding", "9999"),
                ("receivable", "1100"),
                ("payable", "2100"),
                ("sales_tax", "2200"),
            )
        ],
        "taxes": [
            {"tax_rate": None, "external_id": "T9"},
            {"tax_rate": str(world["vat"].pk), "external_id": "T1"},
        ],
        "tracking": [],
    }
    assert (
        world["api"].put("/api/v1/accounting/mappings/export", body, format="json").status_code
        == 200
    )


def test_generic_gl_export_balances(org, world, export_codes):
    invoice = issue(org, world, "100.00")
    with tenant_context(org):
        payments.record_manual_payment(
            client=world["client"],
            amount=gbp("120.00"),
            method="bank_transfer",
            allocations=[(invoice, gbp("120.00"))],
        )
    response = _export(world, "generic")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.content.decode())))
    assert sum(Decimal(r["debit"]) for r in rows) == sum(Decimal(r["credit"]) for r in rows)
    assert {"4000", "2200", "1100", "1210"} <= {r["account"] for r in rows}
    assert any(r["tax_code"] == "T1" for r in rows)
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="gl_export").exists()


@pytest.mark.parametrize(
    ("fmt", "marker"),
    [
        ("sage50", "Nominal A/C Ref"),
        ("myob", "Journal Number"),
        ("iif", "!TRNS"),
    ],
)
def test_package_exports(org, world, export_codes, fmt, marker):
    issue(org, world)
    response = _export(world, fmt)
    assert response.status_code == 200
    body = response.content.decode()
    assert marker in body
    if fmt == "iif":
        assert "GENERAL JOURNAL" in body
        assert "ENDTRNS" in body


def test_exports_need_the_permission_and_mappings(org, world):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    today = str(now().date())
    assert (
        client_for(org, coordinator)
        .get("/api/v1/accounting/export", {"start": today, "end": today})
        .status_code
        == 403
    )
    issue(org, world)
    assert _export(world, "generic").status_code == 422  # no export mappings yet


# --- dashboard API and isolation ------------------------------------------------------------------


def test_records_filter_by_object_for_sync_badges(org, world):
    enabled(org, world)
    first, second = issue(org, world, n=2)
    sync(org, "invoice", first.pk)
    response = world["api"].get(
        "/api/v1/accounting/records",
        {"object_type": "invoice", "object_id": f"{first.pk},{second.pk}"},
    )
    rows = response.json()["results"]
    assert [(r["object_id"], r["status"]) for r in rows] == [(str(first.pk), "synced")]
    detail = world["api"].get(f"/api/v1/accounting/records/{rows[0]['id']}").json()
    assert detail["log"][0]["outcome"] == "created"


def test_retry_failed_retries_every_error(org, world):
    enabled(org, world)
    invoices = issue(org, world, n=2)
    with tenant_context(org):
        for invoice in invoices:
            services.record_error("invoice", str(invoice.pk), "Boom")
    assert world["api"].post("/api/v1/accounting/records/retry-failed").json() == {"retried": 2}
    with tenant_context(org):
        assert not ExternalRecordLink.objects.filter(status="error").exists()


class TestConnectionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/accounting/connections"

    def make_object(self, organisation):
        with tenant_context(organisation):
            connection = IntegrationConnection.objects.create(
                provider="xero", level="organisation", external_account_id=f"xero:{organisation.pk}"
            )
            return AccountingConnection.objects.create(connection=connection, provider="xero")


class TestRecordIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/accounting/records"

    def make_object(self, organisation):
        conn = TestConnectionIsolation().make_object(organisation)
        with tenant_context(organisation):
            return ExternalRecordLink.objects.create(
                connection=conn, provider="xero", object_type="invoice", object_id="x"
            )
