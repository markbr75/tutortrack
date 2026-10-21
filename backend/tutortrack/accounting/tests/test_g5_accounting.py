"""Gap batch G5 (E23): payment reallocations and lost disputes after a payment is in the
ledger (FR-23-2/3), bad debt VAT relief on write-offs, summary journals in other
currencies and self-billing VAT in GL exports (FR-23-2/5), and per-branch ledgers
(FR-23-1). Ledgers are the sandbox-shaped fakes; the real clients' requests are checked
against recorded shapes."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.accounting import journals, routing, services
from tutortrack.accounting.documents import ReallocationDoc
from tutortrack.accounting.journals import Posting
from tutortrack.accounting.mappings import AccountRef
from tutortrack.accounting.models import AccountingConnection, ExternalRecordLink
from tutortrack.accounting.providers import freeagent, quickbooks, sage, xero
from tutortrack.accounting.providers.fake import FakeLedger
from tutortrack.billing import services as billing
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import Credentials, http
from tutortrack.payments import services as payments
from tutortrack.people.tests.factories import ClientFactory, StudentFactory
from tutortrack.tenancy.tests.factories import BranchFactory

from .conftest import ACCOUNTS, enabled, gbp, issue

pytestmark = pytest.mark.django_db
LEDGERS = ["xero", "quickbooks", "sage", "freeagent"]


def ledger(conn: AccountingConnection) -> FakeLedger:
    with tenant_context(conn.organisation_id):
        account = IntegrationConnection.objects.get(pk=conn.connection_id).external_account_id
    return FakeLedger(account)


def link(org, object_type: str, object_id: Any, conn=None) -> ExternalRecordLink:
    with tenant_context(org):
        qs = ExternalRecordLink.objects.filter(object_type=object_type, object_id=str(object_id))
        if conn is not None:
            qs = qs.filter(connection=conn)
        return qs.get()


def sync(org, object_type: str, object_id: Any) -> str:
    with tenant_context(org):
        return services.sync(object_type, str(object_id), inline=True)


def due(org, conn, invoice) -> tuple[Decimal, Decimal]:
    """(ledger's amount due, TutorTrack's balance due) for an invoice."""
    with tenant_context(org):
        invoice.refresh_from_db()
    external = link(org, "invoice", invoice.pk, conn).external_id
    return ledger(conn).amount_due("invoices", external), invoice.balance_due.amount


def in_step(org, conn, *invoices) -> None:
    for invoice in invoices:
        theirs, ours = due(org, conn, invoice)
        assert theirs == ours, (invoice.number, theirs, ours)


def set_setting(org, area: str, key: str, value: Any) -> None:
    from tutortrack.tenancy import settings_service

    with tenant_context(org):
        settings_service.update_settings(area, {key: value})


# --- reallocations after sync (FR-23-2/3) ---------------------------------------------------------


@pytest.mark.parametrize("provider", LEDGERS)
def test_reallocating_a_synced_payment_moves_it_in_the_ledger(org, world, provider):
    conn = enabled(org, world, provider)
    first, second = issue(org, world, "50.00", vat=False, n=2)
    assert sync(org, "invoice", first.pk) == "synced"
    assert sync(org, "invoice", second.pk) == "synced"
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("50.00"),
            method="bank_transfer",
            allocations=[(first, gbp("50.00"))],
        )
    assert sync(org, "payment", payment.pk) == "synced"
    with tenant_context(org):
        payments.reallocate(payment, [(second, gbp("50.00"))])
        assert OutboxEvent.objects.filter(event_type="payment.reallocated").count() == 1
    assert sync(org, "reallocation", payment.pk) == "synced"
    in_step(org, conn, first, second)
    second_ext = link(org, "invoice", second.pk).external_id
    assert link(org, "payment", payment.pk).meta["ledger"] == {second_ext: "50.00"}
    calls = ledger(conn).calls
    assert sync(org, "reallocation", payment.pk) == "synced"  # nothing more to move
    assert ledger(conn).calls == calls
    # A refund afterwards takes money back off the invoice the payment moved to.
    with tenant_context(org):
        refund = payments.refund_payment(payment, amount=gbp("20.00"), reason="Missed lesson")
    assert sync(org, "refund", refund.pk) == "synced"
    in_step(org, conn, first, second)


def test_reallocating_onto_more_invoices_uses_the_clients_credit(org, world):
    conn = enabled(org, world)
    first, second = issue(org, world, "50.00", vat=False, n=2)
    sync(org, "invoice", first.pk)
    sync(org, "invoice", second.pk)
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("80.00"),
            method="bank_transfer",
            allocations=[(first, gbp("50.00"))],
        )
    assert sync(org, "payment", payment.pk) == "synced"
    contact = link(org, "contact", world["client"].pk).external_id
    assert Decimal(ledger(conn).get("contacts", contact)["credit"]) == Decimal("30.00")
    with tenant_context(org):
        payments.reallocate(payment, [(first, gbp("30.00")), (second, gbp("50.00"))])
    assert sync(org, "reallocation", payment.pk) == "synced"
    in_step(org, conn, first, second)
    assert Decimal(ledger(conn).get("contacts", contact)["credit"]) == Decimal("0")


def test_a_reallocation_before_the_payment_syncs_goes_with_the_payment(org, world):
    conn = enabled(org, world)
    first, second = issue(org, world, "40.00", vat=False, n=2)
    sync(org, "invoice", first.pk)
    sync(org, "invoice", second.pk)
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("40.00"),
            method="bank_transfer",
            allocations=[(first, gbp("40.00"))],
        )
        payments.reallocate(payment, [(second, gbp("40.00"))])
    assert sync(org, "reallocation", payment.pk) == "skipped"
    assert sync(org, "payment", payment.pk) == "synced"
    in_step(org, conn, first, second)


def test_a_refund_waits_for_a_reallocation_not_yet_in_the_ledger(org, world):
    """The reallocation is marked pending when the event arrives, so a refund recorded
    after it is planned behind it (and never takes money off the old invoice)."""
    conn = enabled(org, world)
    first, second = issue(org, world, "50.00", vat=False, n=2)
    sync(org, "invoice", first.pk)
    sync(org, "invoice", second.pk)
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("50.00"),
            method="bank_transfer",
            allocations=[(first, gbp("50.00"))],
        )
    sync(org, "payment", payment.pk)
    with tenant_context(org):
        payments.reallocate(payment, [(second, gbp("50.00"))])
        services.note_reallocated(str(payment.pk))
        assert link(org, "reallocation", payment.pk).status == "pending"
        refund = payments.refund_payment(payment, amount=gbp("10.00"), reason="Overcharged")
        planned = services.plan("refund", str(refund.pk))
    assert ["reallocation", str(payment.pk)] in planned["prerequisites"]
    assert planned["connection_id"] == str(conn.pk)
    # Inline (as a backfill or the workflow's children would): reallocation, then refund.
    assert sync(org, "refund", refund.pk) == "synced"
    assert link(org, "reallocation", payment.pk).status == "synced"
    in_step(org, conn, first, second)


def test_reallocation_before_a_refund_is_synced_counts_the_refund_once(org, world):
    """A refund recorded (not yet synced) before the payment is moved: the reallocation
    keeps the refunded amount where the refund will take it from."""
    conn = enabled(org, world)
    first, second = issue(org, world, "50.00", vat=False, n=2)
    sync(org, "invoice", first.pk)
    sync(org, "invoice", second.pk)
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("50.00"),
            method="bank_transfer",
            allocations=[(first, gbp("50.00"))],
        )
    sync(org, "payment", payment.pk)
    with tenant_context(org):
        refund = payments.refund_payment(payment, amount=gbp("20.00"), reason="Overcharged")
        payments.reallocate(payment, [(second, gbp("30.00"))])
    assert sync(org, "reallocation", payment.pk) == "synced"
    assert sync(org, "refund", refund.pk) == "synced"
    in_step(org, conn, first, second)


# --- lost disputes after sync ---------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["xero", "quickbooks"])
def test_a_lost_dispute_takes_the_money_back_in_the_ledger(org, world, provider):
    conn = enabled(org, world, provider)
    invoice = issue(org, world, "100.00")
    sync(org, "invoice", invoice.pk)
    with tenant_context(org):
        payment = payments.record_provider_payment(
            account=world["account"],
            client=world["client"],
            amount=gbp("120.00"),
            provider_ref="pi_g5_dispute",
            invoice=invoice,
            fee=gbp("2.00"),
        )
    assert sync(org, "payment", payment.pk) == "synced"
    in_step(org, conn, invoice)
    with tenant_context(org):
        dispute = payments.open_dispute(
            payment, ref="dp_g5", amount=gbp("120.00"), reason="fraudulent", due=None
        )
    assert sync(org, "chargeback", dispute.pk) == "skipped"  # not lost (yet)
    with tenant_context(org):
        payments.close_dispute(dispute, won=False)
        assert OutboxEvent.objects.filter(
            event_type="payment.dispute_closed", payload__data__outcome="lost"
        ).exists()
    assert sync(org, "chargeback", dispute.pk) == "synced"
    in_step(org, conn, invoice)
    with tenant_context(org):
        invoice.refresh_from_db()
        assert invoice.balance_due == gbp("120.00")
    assert len(ledger(conn).records("refunds")) == 1
    assert link(org, "payment", payment.pk).meta["ledger"] == {}


def test_lost_disputes_are_in_summary_journals_and_gl_exports(org, world):
    conn = enabled(org, world, mode="summary")
    invoice = issue(org, world, "50.00", vat=False)
    with tenant_context(org):
        payment = payments.record_provider_payment(
            account=world["account"],
            client=world["client"],
            amount=gbp("50.00"),
            provider_ref="pi_g5_sum",
            invoice=invoice,
        )
        dispute = payments.open_dispute(
            payment, ref="dp_g5_sum", amount=gbp("50.00"), reason="", due=None
        )
        payments.close_dispute(dispute, won=False)
        postings = journals.sales_postings(
            services.builders.Context(conn).maps,
            billing.org_today(),
            billing.org_today(),
            "Europe/London",
        )
    chargeback = [p for p in postings if p.source == f"chargeback:{dispute.pk}"]
    assert sorted((p.account.id, p.debit, p.credit) for p in chargeback) == [
        ("acc-091", Decimal(0), Decimal("50.00")),
        ("acc-610", Decimal("50.00"), Decimal(0)),
    ]


# --- bad debt VAT relief --------------------------------------------------------------------------


def test_write_off_without_relief_is_unchanged(org, world):
    conn = enabled(org, world)
    invoice = issue(org, world, "100.00")
    sync(org, "invoice", invoice.pk)
    with tenant_context(org):
        billing.write_off(invoice, reason="Moved away")
    assert sync(org, "write_off", invoice.pk) == "synced"
    (note,) = ledger(conn).records("credit_notes")
    assert Decimal(note["total"]) == Decimal("120.00")
    in_step(org, conn, invoice)


def test_write_off_with_relief_reclaims_the_vat_in_what_is_written_off(org, world):
    conn = enabled(org, world)
    set_setting(org, "accounting", "accounting.bad_debt_vat_relief", True)
    invoice = issue(org, world, "100.00")  # 100 + 20 VAT
    sync(org, "invoice", invoice.pk)
    with tenant_context(org):
        payments.record_manual_payment(
            client=world["client"],
            amount=gbp("60.00"),
            method="bank_transfer",
            allocations=[(invoice, gbp("60.00"))],
        )
        invoice.refresh_from_db()
        billing.write_off(invoice, reason="Moved away")
        built = services.builders.build(
            services.builders.Context(conn), "write_off", str(invoice.pk)
        )
    (line,) = built.doc.lines  # type: ignore[attr-defined]
    assert (line.net, line.tax, line.tax_code) == (Decimal("50.00"), Decimal("10.00"), "OUTPUT2")
    assert built.doc.total == Decimal("60.00")  # type: ignore[attr-defined]
    assert sync(org, "write_off", invoice.pk) == "synced"


def test_write_off_relief_in_gl_exports(org, world):
    set_setting(org, "accounting", "accounting.bad_debt_vat_relief", True)
    _export_codes(world)
    invoice = issue(org, world, "100.00")
    with tenant_context(org):
        billing.write_off(invoice, reason="Gone")
    rows = _export_rows(world)
    write_off = [r for r in rows if r["journal"] == f"write_off:{invoice.pk}"]
    assert {(r["account"], r["debit"], r["credit"]) for r in write_off} == {
        ("8100", "100.00", "0.00"),
        ("2200", "20.00", "0.00"),
        ("1100", "0.00", "120.00"),
    }
    assert sum(Decimal(r["debit"]) for r in rows) == sum(Decimal(r["credit"]) for r in rows)


money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100000"), places=2)
rates = st.sampled_from([Decimal(0), Decimal(5), Decimal("12.5"), Decimal(20), Decimal("17.5")])


@settings(max_examples=150, deadline=None)
@given(
    groups=st.lists(st.tuples(money, rates), min_size=1, max_size=4),
    share=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(1), places=4),
)
def test_bad_debt_vat_parts_add_up_and_use_each_rates_vat_fraction(groups, share):
    """Hypothesis: the parts add up exactly to the amount written off; each part's VAT is
    its group's VAT fraction of it, rounded half-up; writing off everything reclaims
    exactly the invoice's VAT."""
    tax_groups = [
        (
            net + (net * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP),
            (net * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP),
        )
        for net, rate in groups
    ]
    total = sum((g for g, _t in tax_groups), Decimal(0))
    amount = Money(total * share, "GBP").round_to_minor()
    if not amount.is_positive():
        return
    parts = journals.bad_debt_vat(amount, tax_groups)
    assert sum((n + t for n, t in parts), Decimal(0)) == amount.amount
    shares = amount.allocate([g for g, _t in tax_groups])
    for (gross, tax), part, (net, vat) in zip(tax_groups, shares, parts, strict=True):
        expected = (part.amount * tax / gross).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert vat == min(expected, part.amount)
        assert net == part.amount - vat
        assert Decimal(0) <= vat <= tax
    whole = journals.bad_debt_vat(Money(total, "GBP"), tax_groups)
    assert [t for _n, t in whole] == [t for _g, t in tax_groups]


# --- summary journals in other currencies ---------------------------------------------------------


def _fx(day: date, gbp_per_eur: str) -> None:
    from tutortrack.reporting.models import FxRate

    FxRate.objects.update_or_create(
        date=day, base="EUR", quote="GBP", defaults={"rate": Decimal(gbp_per_eur)}
    )


def _euro_invoice(org, w, amount: str) -> Any:
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=w["client"],
            student=w["student"],
            description="Tuition (EUR)",
            unit_price=Money(Decimal(amount), "EUR"),
            tax_rate=w["vat"],
        )
        return billing.issue_invoice(billing.create_draft(w["client"]), send=False)


def test_summary_journal_for_another_currency_is_converted_to_the_base(org, world):
    conn = enabled(org, world, mode="summary")
    with tenant_context(org):
        day = billing.org_today()
    _fx(day, "0.8537")
    issue(org, world, "10.00", vat=False)  # a GBP one too: its own journal
    invoice = _euro_invoice(org, world, "33.33")  # 33.33 + 6.67 VAT = 40.00 EUR
    assert invoice.currency == "EUR"
    with tenant_context(org):
        result = services.daily(str(conn.pk), day)
    assert result["journal"] == "synced"
    assert result["journal_EUR"] == "synced"
    euro = link(org, "journal", f"{day.isoformat()}:EUR")
    assert euro.meta["currency"] == "EUR"
    journal = next(j for j in ledger(conn).records("journals") if "EUR" in j["narration"])
    debit = sum(Decimal(str(x["debit"])) for x in journal["lines"])
    credit = sum(Decimal(str(x["credit"])) for x in journal["lines"])
    assert debit == credit
    receivable = next(x for x in journal["lines"] if x["account"] == "acc-610")
    assert Decimal(str(receivable["debit"])) == Decimal("34.15")  # 40.00 x 0.8537
    assert any(x["description"] == "Currency conversion difference" for x in journal["lines"])
    assert "0.8537" in journal["narration"]


def test_no_exchange_rate_is_a_readable_error(org, world):
    conn = enabled(org, world, mode="summary")
    with tenant_context(org):
        day = billing.org_today()
    from tutortrack.reporting.models import FxRate

    FxRate.objects.all().delete()
    _euro_invoice(org, world, "10.00")
    with tenant_context(org):
        result = services.daily(str(conn.pk), day)
    assert result["journal_EUR"] == "error"
    failed = link(org, "journal", f"{day.isoformat()}:EUR")
    assert failed.error_code == "fx_rate_missing"
    assert "exchange rate" in failed.error


def test_backfill_includes_journals_in_other_currencies(org, world):
    conn = enabled(org, world, mode="summary")
    with tenant_context(org):
        day = billing.org_today() - timedelta(days=1)
        ids = services._candidates(conn, "journal", day, "")
    assert ids[0] == day.isoformat()
    _euro_invoice(org, world, "10.00")
    with tenant_context(org):
        today = billing.org_today()
        later = services._candidates(conn, "journal", today - timedelta(days=1), today.isoformat())
    assert later == []  # only days before today
    with tenant_context(org):
        found = journals.activity_currencies(today, today, "Europe/London")
    assert "EUR" in found


class _Rates:
    def __init__(self, rate: Decimal):
        self.value = rate

    def rate(self, source: str, target: str, day: date) -> Decimal:
        return self.value


@settings(max_examples=150, deadline=None)
@given(
    amounts=st.lists(money, min_size=1, max_size=6),
    rate=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("200"), places=6),
)
def test_converted_journals_always_balance(amounts, rate):
    """Hypothesis: each posting is converted half-up at line level, and the summary is
    balanced with one conversion-difference line no bigger than half a penny a posting."""
    from tutortrack.accounting.documents import JournalLine

    receivable, revenue = AccountRef("r", "610"), AccountRef("s", "200")
    day = date(2026, 10, 1)
    postings = []
    for amount in amounts:
        postings.append(Posting(day, "EUR", receivable, debit=amount))
        postings.append(Posting(day, "EUR", revenue, credit=amount))
    converted, used = journals.convert(postings, "GBP", _Rates(rate))
    for before, after in zip(postings, converted, strict=True):
        assert after.currency == "GBP"
        assert after.debit == (before.debit * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert after.credit == (before.credit * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert used == {"EUR 2026-10-01": str(rate)}

    class Maps:
        def find(self, kind: str) -> AccountRef | None:
            return AccountRef("fx", "7999") if kind == "fx" else None

        def account(self, kind: str) -> AccountRef:
            return AccountRef("round", "9999")

    lines = journals.balance(Maps(), journals.summarise(converted), kind="fx")  # type: ignore[arg-type]
    assert sum((x.debit for x in lines), Decimal(0)) == sum((x.credit for x in lines), Decimal(0))
    extra = [x for x in lines if x.account == "fx"]
    assert len(extra) <= 1
    assert all(isinstance(x, JournalLine) for x in lines)
    if extra:
        assert extra[0].debit + extra[0].credit <= Decimal("0.005") * len(postings) + Decimal(
            "0.01"
        )


# --- self-billing VAT in GL exports ---------------------------------------------------------------


def _export_codes(world, extra: tuple[tuple[str, str], ...] = ()) -> None:
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
                *extra,
            )
        ],
        "taxes": [
            {"tax_rate": None, "external_id": "T9"},
            {"tax_rate": str(world["vat"].pk), "external_id": "T1"},
        ],
        "tracking": [],
    }
    response = world["api"].put("/api/v1/accounting/mappings/export", body, format="json")
    assert response.status_code == 200, response.json()


def _export_rows(world, **params: str) -> list[dict[str, str]]:
    today = now().date()
    response = world["api"].get(
        "/api/v1/accounting/export",
        {
            "file_format": "generic",
            "start": str(today - timedelta(days=1)),
            "end": str(today + timedelta(days=1)),
            "mapping_set": "export",
            **params,
        },
    )
    assert response.status_code == 200, response.content
    return list(csv.DictReader(io.StringIO(response.content.decode())))


def test_self_billing_vat_is_in_gl_exports(org, world):
    from .test_accounting import _pay_run

    _export_codes(world, (("input_tax", "2201"), ("purchase_tax", "T1-IN")))
    _run, payout, _tutor = _pay_run(org, world, vat=True)
    rows = [r for r in _export_rows(world) if r["journal"] == f"bill:{payout.pk}"]
    assert {(r["account"], r["debit"], r["credit"], r["tax_code"]) for r in rows} == {
        ("5000", "120.00", "0.00", ""),
        ("2201", "24.00", "0.00", "T1-IN"),
        ("2100", "0.00", "144.00", ""),
    }


def test_self_billing_vat_falls_back_to_the_vat_account(org, world):
    from .test_accounting import _pay_run

    _export_codes(world)
    _run, payout, _tutor = _pay_run(org, world, vat=True)
    rows = [r for r in _export_rows(world) if r["journal"] == f"bill:{payout.pk}"]
    assert ("2200", "24.00") in {(r["account"], r["debit"]) for r in rows}


# --- per-branch ledgers (FR-23-1) -----------------------------------------------------------------


def connect_branch(org, w, branch, provider: str = "xero") -> AccountingConnection:
    api = w["api"]
    started = api.post(
        "/api/v1/integrations/oauth/start",
        {
            "provider": provider,
            "level": "branch",
            "branch": str(branch.pk),
            "next": "/settings/accounting",
        },
        format="json",
    )
    assert started.status_code == 200, started.json()
    query = urllib.parse.parse_qs(urllib.parse.urlparse(started.json()["authorize_url"]).query)
    done = api.post(
        "/api/v1/integrations/oauth/complete",
        {"code": query["code"][0], "state": query["state"][0]},
        format="json",
    )
    assert done.status_code == 201, done.json()
    assert (done.json()["level"], done.json()["branch"]) == ("branch", str(branch.pk))
    adopted = api.post(
        "/api/v1/accounting/connections", {"connection": done.json()["id"]}, format="json"
    )
    assert adopted.status_code == 201, adopted.json()
    body = adopted.json()
    assert (body["branch"], body["mapping_set"]) == (
        str(branch.pk),
        f"{provider}@{branch.pk}",
    )
    with tenant_context(org):
        return AccountingConnection.objects.select_related("connection").get(pk=body["id"])


def map_set(w, name: str) -> dict[str, Any]:
    response = w["api"].put(
        f"/api/v1/accounting/mappings/{name}",
        {
            "accounts": [
                {"kind": kind, "key": key, "external_id": external}
                for kind, key, external in ACCOUNTS
            ],
            "taxes": [
                {"tax_rate": None, "external_id": "NONE"},
                {"tax_rate": str(w["vat"].pk), "external_id": "OUTPUT2"},
            ],
            "tracking": [],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    return response.json()


@pytest.fixture
def north(org, world):
    with tenant_context(org):
        branch = BranchFactory(organisation=org, name="North")
        family = ClientFactory(organisation=org, display_name="The Okafors", branch=branch)
        student = StudentFactory(organisation=org, client=family)
    return {"branch": branch, "client": family, "student": student}


def _north_invoice(org, world, north, amount: str = "80.00") -> Any:
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=north["client"],
            student=north["student"],
            description="Tuition",
            unit_price=gbp(amount),
            tax_rate=None,
        )
        return billing.issue_invoice(billing.create_draft(north["client"]), send=False)


def test_a_branch_with_its_own_ledger_gets_its_records(org, world, north):
    main = enabled(org, world, "xero")
    branch_conn = connect_branch(org, world, north["branch"])
    data = map_set(world, branch_conn.mapping_set)
    assert data["problems"] == []
    enable = world["api"].post(f"/api/v1/accounting/connections/{branch_conn.pk}/enable", {})
    assert enable.status_code == 200, enable.json()
    theirs = _north_invoice(org, world, north)
    ours = issue(org, world, "50.00", vat=False)
    with tenant_context(org):
        assert routing.route("invoice", str(theirs.pk)).pk == branch_conn.pk  # type: ignore[union-attr]
        assert routing.route("invoice", str(ours.pk)).pk == main.pk  # type: ignore[union-attr]
        planned = services.plan("invoice", str(theirs.pk))
    assert planned["connection_id"] == str(branch_conn.pk)
    assert sync(org, "invoice", theirs.pk) == "synced"
    assert sync(org, "invoice", ours.pk) == "synced"
    assert link(org, "invoice", theirs.pk).connection_id == branch_conn.pk
    assert link(org, "contact", north["client"].pk).connection_id == branch_conn.pk
    assert link(org, "invoice", ours.pk).connection_id == main.pk
    assert [r["number"] for r in ledger(branch_conn).records("invoices")] == [theirs.number]
    assert [r["number"] for r in ledger(main).records("invoices")] == [ours.number]
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=north["client"],
            amount=gbp("80.00"),
            method="bank_transfer",
            allocations=[(theirs, gbp("80.00"))],
        )
    assert sync(org, "payment", payment.pk) == "synced"
    in_step(org, branch_conn, theirs)
    # The connections list shows both ledgers.
    rows = world["api"].get("/api/v1/accounting/connections").json()["results"]
    assert {(r["branch_name"], r["mapping_set"]) for r in rows} == {
        (None, "xero"),
        ("North", f"xero@{north['branch'].pk}"),
    }


def test_the_organisations_ledger_leaves_out_branches_with_their_own(org, world, north):
    main = enabled(org, world, "xero", mode="summary")
    branch_conn = connect_branch(org, world, north["branch"], "quickbooks")
    map_set(world, branch_conn.mapping_set)
    world["api"].patch(
        f"/api/v1/accounting/connections/{branch_conn.pk}", {"mode": "summary"}, format="json"
    )
    assert (
        world["api"].post(f"/api/v1/accounting/connections/{branch_conn.pk}/enable", {}).status_code
        == 200
    )
    theirs = _north_invoice(org, world, north)
    ours = issue(org, world, "50.00", vat=False)
    with tenant_context(org):
        day = billing.org_today()
        main.refresh_from_db()
        branch_conn.refresh_from_db()
        assert services.daily(str(main.pk), day)["journal"] == "synced"
        assert services.daily(str(branch_conn.pk), day)["journal"] == "synced"
    (main_journal,) = ledger(main).records("journals")
    (branch_journal,) = ledger(branch_conn).records("journals")

    def receivable(journal: dict[str, Any]) -> Decimal:
        return sum(
            (Decimal(str(x["debit"])) for x in journal["lines"] if x["account"] == "acc-610"),
            Decimal(0),
        )

    assert receivable(main_journal) == ours.total.amount
    assert receivable(branch_journal) == theirs.total.amount


def test_one_switched_on_ledger_per_branch(org, world, north):
    enabled(org, world, "xero")
    first = connect_branch(org, world, north["branch"], "xero")
    map_set(world, first.mapping_set)
    assert (
        world["api"].post(f"/api/v1/accounting/connections/{first.pk}/enable", {}).status_code
        == 200
    )
    second = connect_branch(org, world, north["branch"], "quickbooks")
    map_set(world, second.mapping_set)
    refused = world["api"].post(f"/api/v1/accounting/connections/{second.pk}/enable", {})
    assert refused.status_code == 422
    assert "branch" in json.dumps(refused.json())


def test_branch_level_connections_need_a_branch(org, world):
    response = world["api"].post(
        "/api/v1/integrations/oauth/start",
        {"provider": "xero", "level": "branch", "next": "/settings/accounting"},
        format="json",
    )
    assert response.status_code in (400, 422)
    assert "branch" in json.dumps(response.json())
    unknown = world["api"].get("/api/v1/accounting/mappings/xero@not-a-branch")
    assert unknown.status_code in (400, 422)


def test_gl_exports_by_ledger_and_branch(org, world, north):
    _export_codes(world)
    theirs = _north_invoice(org, world, north)
    ours = issue(org, world, "50.00", vat=False)
    everything = {r["journal"] for r in _export_rows(world)}
    assert {f"invoice:{theirs.pk}", f"invoice:{ours.pk}"} <= everything
    only_north = {r["journal"] for r in _export_rows(world, branch=str(north["branch"].pk))}
    assert f"invoice:{theirs.pk}" in only_north
    assert f"invoice:{ours.pk}" not in only_north


def test_a_client_update_reaches_every_ledger_the_client_is_in(org, world, north):
    main = enabled(org, world, "xero")
    branch_conn = connect_branch(org, world, north["branch"])
    map_set(world, branch_conn.mapping_set)
    world["api"].post(f"/api/v1/accounting/connections/{branch_conn.pk}/enable", {})
    # The northern family also has an invoice billed by the main branch's ledger.
    theirs = _north_invoice(org, world, north)
    sync(org, "invoice", theirs.pk)
    with tenant_context(org):
        services.sync("contact", str(north["client"].pk), conn=main)
        family = north["client"]
        family.display_name = "The Okafor Family"
        family.save()
        assert services.sync("contact", str(family.pk)) == "synced"
    for conn in (main, branch_conn):
        external = link(org, "contact", north["client"].pk, conn).external_id
        assert ledger(conn).get("contacts", external)["name"] == "The Okafor Family"


# --- the real clients' requests (no network) ------------------------------------------------------


class Recorder:
    def __init__(self, replies: dict[tuple[str, str], Any] | None = None):
        self.replies = replies or {}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> http.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        for (m, fragment), reply in self.replies.items():
            if m == method and fragment in url:
                return http.Response(200, None, json.dumps(reply).encode())  # type: ignore[arg-type]
        return http.Response(200, None, b"{}")  # type: ignore[arg-type]


CREDS = Credentials(access_token="t", account_id="acct-1")
MOVE = ReallocationDoc(
    kind="reallocation",
    ref="pay-1",
    date="2026-10-20",
    currency="GBP",
    contact="c-1",
    account="bank-1",
    payment="p-1",
    paid_on="2026-10-01",
    reference="BACS",
    total=Decimal("80.00"),
    allocations=(("inv-a", Decimal("20.00")), ("inv-b", Decimal("60.00"))),
    previous=(("inv-a", Decimal("50.00")),),
    parts=(("inv-a", "xp-1", "50.00"), ("overpayment", "op-1", "30.00")),
)


def test_xero_reallocation_requests(monkeypatch):
    recorder = Recorder(
        {
            ("PUT", "/Payments"): {"Payments": [{"PaymentID": "xp-new"}]},
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    pushed = xero.XeroClient().push(CREDS, MOVE, "", idempotency_key="tt-1")
    calls = [(c["method"], c["url"].split("2.0")[-1]) for c in recorder.calls]
    assert ("POST", "/Payments/xp-1") in calls  # the old payment on A is deleted
    made = [
        c["json_body"]["Payments"][0]
        for c in recorder.calls
        if c["method"] == "PUT" and c["url"].endswith("/Payments")
    ]
    assert sorted((p["Invoice"]["InvoiceID"], p["Amount"], p["Date"]) for p in made) == [
        ("inv-a", "20.00", "2026-10-01"),
        ("inv-b", "30.00", "2026-10-01"),  # the cash freed from A
    ]
    (allocation,) = [c for c in recorder.calls if "/Overpayments/op-1/Allocations" in c["url"]]
    assert allocation["json_body"]["Allocations"][0]["Amount"] == "30.00"  # from credit
    parts = {tuple(p) for p in pushed.meta["parts"]}
    assert ("overpayment", "op-1", "0.00") in parts
    assert {p[0] for p in parts} == {"inv-a", "inv-b", "overpayment"}


def test_quickbooks_reallocation_replaces_the_payment_lines(monkeypatch):
    recorder = Recorder({("GET", "/payment/p-1"): {"Payment": {"Id": "p-1", "SyncToken": "3"}}})
    monkeypatch.setattr(http, "request", recorder)
    quickbooks.QuickBooksClient().push(CREDS, MOVE, "", idempotency_key="tt-1")
    update = next(c for c in recorder.calls if c["method"] == "POST")
    body = update["json_body"]
    assert (body["Id"], body["SyncToken"], body["sparse"]) == ("p-1", "3", True)
    assert [(x["Amount"], x["LinkedTxn"][0]["TxnId"]) for x in body["Line"]] == [
        (20.0, "inv-a"),
        (60.0, "inv-b"),
    ]


def test_sage_reallocation_replaces_the_receipt_allocations(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(http, "request", recorder)
    sage.SageClient().push(CREDS, MOVE, "", idempotency_key="tt-1")
    (call,) = recorder.calls
    assert (call["method"], call["url"].split("v3.1")[-1]) == ("PUT", "/contact_payments/p-1")
    assert call["json_body"]["contact_payment"]["allocated_artefacts"] == [
        {"artefact_id": "inv-a", "amount": "20.00"},
        {"artefact_id": "inv-b", "amount": "60.00"},
    ]


def test_freeagent_reallocation_explains_the_payment_again(monkeypatch):
    move = ReallocationDoc(
        **{
            **MOVE.as_dict(),
            "parts": (("https://fa/explanations/1",),),
            "allocations": (("https://fa/invoices/b", Decimal("50.00")),),
            "previous": (("https://fa/invoices/a", Decimal("50.00")),),
            "total": Decimal("80.00"),
        }
    )
    recorder = Recorder(
        {
            ("POST", "/bank_transaction_explanations"): {
                "bank_transaction_explanation": {"url": "https://fa/explanations/9"}
            }
        }
    )
    monkeypatch.setattr(http, "request", recorder)
    pushed = freeagent.FreeAgentClient().push(CREDS, move, "", idempotency_key="tt-1")
    assert recorder.calls[0]["method"] == "DELETE"
    assert recorder.calls[0]["url"] == "https://fa/explanations/1"
    made = [c["json_body"]["bank_transaction_explanation"] for c in recorder.calls[1:]]
    assert [(m.get("paid_invoice"), m["gross_value"], m["dated_on"]) for m in made] == [
        ("https://fa/invoices/b", "50.00", "2026-10-01"),
        (None, "30.00", "2026-10-01"),  # the rest on account
    ]
    assert pushed.meta["parts"] == ["https://fa/explanations/9", "https://fa/explanations/9"]
