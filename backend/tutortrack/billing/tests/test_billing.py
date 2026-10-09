"""E10-T01..T10: ledger, charges, invoices, runs, credit notes, payment requests, invoicing
in advance, statements and the negative-balance guard."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.billing import ledger, services
from tutortrack.billing.models import (
    Charge,
    ClientLedgerEntry,
    CreditNote,
    ImmutableRecord,
    Invoice,
    InvoiceRun,
    PaymentRequest,
)
from tutortrack.catalogue.tests.factories import ServiceFactory, TaxRateFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def gbp(amount: str) -> Money:
    return Money(Decimal(amount), "GBP")


def snap(moment):
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


@pytest.fixture
def family(org):
    client = ClientFactory(organisation=org, display_name="The Patels", payment_terms_days=14)
    contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
    with tenant_context(org):
        client.billing_contact = contact
        client.save()
    students = [
        StudentFactory(organisation=org, client=client, first_name=name, last_name="Patel")
        for name in ("Arjun", "Maya", "Dev")
    ]
    tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia")
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {"client": client, "students": students, "tutor": tutor, "service": service}


@pytest.fixture
def finance(org):
    return client_for(org, MembershipFactory(organisation=org, role="finance").user)


def set_settings(org, area, values):
    with tenant_context(org):
        settings_service.update_settings(area, values)


def lesson(org, family, *, student=0, hours_ago=3, minutes=60, job=None, **kwargs):
    start = snap(now() - timedelta(hours=hours_ago))
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=kwargs.pop("service", family["service"]),
            job=job,
            attendees=[{"student": family["students"][student]}],
            tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London",
            override_conflicts=True,
            **kwargs,
        ).lesson


def complete(org, the_lesson, **kwargs):
    with tenant_context(org):
        delivery.complete_lesson(the_lesson, **kwargs)
        return services.sync_lesson_charges(the_lesson.pk)


def events_of(org, kind):
    with tenant_context(org):
        return [
            e.payload["data"] for e in OutboxEvent.objects.filter(event_type=kind).order_by("id")
        ]


def make_job(org, family, method, students=(0,)):
    with tenant_context(org):
        return jobs.create_job(
            client=family["client"],
            service=family["service"],
            students=[{"student": family["students"][i]} for i in students],
            tutors=[{"tutor": family["tutor"]}],
            status="active",
            billing_method=method,
        )


# --- ledger (T01) -------------------------------------------------------------------------------


def test_ledger_posts_running_balance_and_is_immutable(org, family):
    client = family["client"]
    with tenant_context(org):
        from django.db import transaction

        with transaction.atomic():
            first = ledger.post(client, ClientLedgerEntry.Type.INVOICE, gbp("100.00"))
            second = ledger.post(client, ClientLedgerEntry.Type.PAYMENT, gbp("-30.00"))
        assert (first.balance_after, second.balance_after) == (gbp("100.00"), gbp("70.00"))
        with pytest.raises(ledger.LedgerError), transaction.atomic():
            ledger.post(client, ClientLedgerEntry.Type.PAYMENT, gbp("10.00"))
        with pytest.raises(ledger.LedgerError), transaction.atomic():
            ledger.post(client, ClientLedgerEntry.Type.INVOICE, gbp("1.005"))
        with pytest.raises(ImmutableRecord):
            second.save()
        with pytest.raises(ImmutableRecord):
            second.delete()
        assert ledger.ledger_balance(client, "GBP") == gbp("70.00")


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    amounts=st.lists(
        st.decimals(min_value=-500, max_value=500, places=2).filter(lambda d: d != 0),
        min_size=1,
        max_size=12,
    )
)
def test_ledger_balance_is_the_sum_of_entries(org, amounts):
    from django.db import transaction

    with tenant_context(org):
        client = ClientFactory(organisation=org)
        with transaction.atomic():
            for amount in amounts:
                kind = (
                    ClientLedgerEntry.Type.INVOICE if amount > 0 else ClientLedgerEntry.Type.PAYMENT
                )
                entry = ledger.post(client, kind, Money(amount, "GBP"))
        total = sum(amounts, Decimal(0))
        assert ledger.ledger_balance(client, "GBP") == Money(total, "GBP")
        assert entry.balance_after == Money(total, "GBP")


# --- charges (T02) ------------------------------------------------------------------------------


def test_completion_creates_one_charge_with_tax(org, family):
    vat = TaxRateFactory(organisation=org, percent=Decimal("20"))
    service = ServiceFactory(organisation=org, name="GCSE", tax_rate=vat)
    the_lesson = lesson(org, family, service=service, minutes=90)
    complete(org, the_lesson)
    with tenant_context(org):
        services.sync_lesson_charges(the_lesson.pk)  # redelivered event: still one charge
        [charge] = Charge.objects.all()
    assert (charge.kind, charge.status) == ("lesson", "uninvoiced")
    assert (charge.net, charge.tax, charge.gross) == (gbp("60.00"), gbp("12.00"), gbp("72.00"))
    set_settings(org, "billing", {"billing.prices_include_tax": True})
    with tenant_context(org):
        inclusive = services.amounts_for(gbp("60.00"), Decimal(20), inclusive=True, exempt=False)
    assert (inclusive.net, inclusive.tax, inclusive.gross) == (
        gbp("50.00"),
        gbp("10.00"),
        gbp("60.00"),
    )
    assert events_of(org, "charge.created")[0]["gross"] == {"amount": "72.00", "currency": "GBP"}


def test_late_cancellation_fee_line(org, family):
    """E09 AC: a client cancelling 10h before under a 24h policy is charged a "Late
    cancellation fee" line referencing the lesson."""
    start = snap(now() + timedelta(hours=10))
    with tenant_context(org):
        the_lesson = scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=family["service"],
            attendees=[{"student": family["students"][0]}], tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London",
        ).lesson  # fmt: skip
        delivery.cancel_lesson(the_lesson, cancelled_by="client")
        services.sync_lesson_charges(the_lesson.pk)
        [charge] = Charge.objects.all()
    assert charge.kind == "late_cancellation"
    assert charge.description.startswith("Late cancellation fee \N{EN DASH} ")
    assert (charge.lesson_id, charge.gross) == (the_lesson.pk, gbp("40.00"))


def test_attendance_changes_update_uninvoiced_charges(org, family):
    the_lesson = lesson(org, family)
    complete(org, the_lesson)
    with tenant_context(org):
        attendee = the_lesson.attendees.get()
        delivery.record_attendance(
            the_lesson, [delivery.AttendanceRow(attendee.pk, "absent_notified")]
        )
        services.sync_lesson_charges(the_lesson.pk)
        assert not Charge.objects.exclude(status="void").exists()
        delivery.record_attendance(the_lesson, [delivery.AttendanceRow(attendee.pk, "present")])
        services.sync_lesson_charges(the_lesson.pk)
        assert Charge.objects.filter(status="uninvoiced").count() == 1


def test_makeup_lessons_are_not_charged(org, family):
    source = lesson(org, family, hours_ago=-48)
    makeup = lesson(org, family, hours_ago=3)
    with tenant_context(org):
        credit = delivery.issue_makeup_credit(source, source.attendees.get(), days=30)
        delivery.consume_makeup_credit(credit, makeup)
    assert complete(org, makeup) == []


def test_editing_an_invoiced_lesson_adds_an_adjustment(org, family):
    the_lesson = lesson(org, family)
    complete(org, the_lesson)
    with tenant_context(org):
        invoice = services.create_draft(family["client"])
        services.issue_invoice(invoice, send=False)
        the_lesson.refresh_from_db()
        assert the_lesson.lock_state == "invoiced"
        scheduling.update_lesson(
            the_lesson,
            end=the_lesson.start + timedelta(minutes=30),
            can_edit_locked=True,
        )
        services.sync_lesson_charges(the_lesson.pk)
        adjustment = Charge.objects.get(kind="reconciliation")
    assert adjustment.gross == gbp("-20.00")
    assert adjustment.status == "uninvoiced"


def test_ad_hoc_charges_and_discounts(org, finance, family):
    response = finance.post(
        "/api/v1/charges",
        {
            "client": str(family["client"].pk),
            "student": str(family["students"][0].pk),
            "description": "Workbook",
            "quantity": "2",
            "unit_price": {"amount": "7.50", "currency": "GBP"},
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["gross"] == {"amount": "15.00", "currency": "GBP"}
    discount = finance.post(
        "/api/v1/charges",
        {
            "client": str(family["client"].pk),
            "description": "Sibling discount",
            "unit_price": {"amount": "-5.00", "currency": "GBP"},
        },
        format="json",
    ).json()
    assert discount["gross"]["amount"] == "-5.00"
    voided = finance.post(f"/api/v1/charges/{discount['id']}/void").json()
    assert voided["status"] == "void"
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/charges").status_code == 403


# --- invoices (T03) -----------------------------------------------------------------------------


def test_monthly_arrears_run_for_a_family(org, finance, family):
    """AC: 3 siblings, family grouping → 1 invoice, lines grouped by student, gap-free
    numbers, and credit from an earlier overpayment applied automatically."""
    from django.db import transaction

    for i in (2, 0, 1):
        complete(org, lesson(org, family, student=i, hours_ago=3 + i * 3))
    with tenant_context(org), transaction.atomic():
        ledger.post(family["client"], ClientLedgerEntry.Type.PAYMENT, gbp("-25.00"))
    other = ClientFactory(organisation=org)
    other_student = StudentFactory(organisation=org, client=other)
    with tenant_context(org):
        start = snap(now() - timedelta(hours=8))
        other_lesson = scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=family["service"],
            attendees=[{"student": other_student}], tutors=[{"tutor": family["tutor"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip
    complete(org, other_lesson)
    today = now().date()
    created = finance.post(
        "/api/v1/invoice-runs",
        {"period_start": str(today - timedelta(days=30)), "period_end": str(today)},
        format="json",
    )
    assert created.status_code == 201, created.json()
    run_id = created.json()["id"]
    again = finance.post(
        "/api/v1/invoice-runs",
        {"period_start": str(today - timedelta(days=30)), "period_end": str(today)},
        format="json",
    )
    assert (again.status_code, again.json()["id"]) == (200, run_id)
    with tenant_context(org):
        assert services.collect_run(run_id)["drafts"] == 2
        services.collect_run(run_id)  # re-running a step never duplicates
        services.issue_run(run_id)
        invoices = list(Invoice.objects.order_by("number"))
        family_invoice = next(i for i in invoices if i.client_id == family["client"].pk)
        lines = list(family_invoice.lines.order_by("position"))
    assert [i.number for i in invoices] == ["INV-000001", "INV-000002"]
    assert [line.student_name for line in lines] == ["Arjun Patel", "Dev Patel", "Maya Patel"]
    assert family_invoice.total == gbp("120.00")
    assert family_invoice.amount_credited == gbp("25.00")
    assert (family_invoice.balance_due, family_invoice.status) == (gbp("95.00"), "partially_paid")
    run = finance.get(f"/api/v1/invoice-runs/{run_id}").json()
    assert (run["status"], run["stats"]["issued"]) == ("completed", 2)
    with tenant_context(org):
        assert not Charge.objects.filter(status="uninvoiced").exists()
        assert Lesson.objects.filter(lock_state="invoiced").count() == 4


def test_issue_numbers_locks_posts_and_renders_pdf(org, finance, family):
    the_lesson = lesson(org, family)
    complete(org, the_lesson)
    draft = finance.post(
        "/api/v1/invoices", {"client": str(family["client"].pk)}, format="json"
    ).json()
    assert (draft["status"], draft["number"]) == ("draft", "")
    finance.patch(f"/api/v1/invoices/{draft['id']}", {"po_number": "PO-7"}, format="json")
    issued = finance.post(f"/api/v1/invoices/{draft['id']}/issue").json()
    assert issued["number"] == "INV-000001"
    assert issued["due_date"] == str(now().date() + timedelta(days=14))
    assert issued["billing_snapshot"]["email"] == "priya@example.com"
    assert issued["po_number"] == "PO-7"
    with tenant_context(org):
        [entry] = ClientLedgerEntry.objects.all()
    assert (entry.type, entry.amount, entry.ref_id) == ("invoice", gbp("40.00"), draft["id"])
    pdf = finance.get(f"/api/v1/invoices/{draft['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert (
        finance.patch(f"/api/v1/invoices/{draft['id']}", {"notes": "x"}, format="json").status_code
        == 422
    )  # immutable once issued
    sent = finance.post(f"/api/v1/invoices/{draft['id']}/send")
    assert sent.status_code == 200
    assert mail.outbox[-1].to == ["priya@example.com"]
    assert mail.outbox[-1].attachments[0][0] == "INV-000001.pdf"
    assert events_of(org, "invoice.sent")[0]["to"] == ["priya@example.com"]


def test_draft_editing_minimum_and_currency_splits(org, finance, family):
    complete(org, lesson(org, family))
    draft = finance.post(
        "/api/v1/invoices", {"client": str(family["client"].pk)}, format="json"
    ).json()
    added = finance.post(
        f"/api/v1/invoices/{draft['id']}/add-line",
        {"description": "Registration", "unit_price": {"amount": "10", "currency": "GBP"}},
        format="json",
    ).json()
    assert added["total"]["amount"] == "50.00"
    removed = finance.post(
        f"/api/v1/invoices/{draft['id']}/remove-line",
        {"line": added["lines"][0]["id"]},
        format="json",
    ).json()
    assert removed["total"]["amount"] == "10.00"
    assert finance.delete(f"/api/v1/invoices/{draft['id']}").status_code == 204
    with tenant_context(org):
        assert Charge.objects.filter(invoice__isnull=True, status="uninvoiced").count() == 2
        services.create_ad_hoc_charge(
            client=family["client"], description="US fee", unit_price=Money("5", "USD")
        )
        settings_service.update_settings("billing", {"billing.minimum_invoice_amount": 100})
        assert services.build_drafts(Charge.objects.all()) == []  # below minimum: carried
        settings_service.update_settings("billing", {"billing.minimum_invoice_amount": 0})
        drafts = services.build_drafts(Charge.objects.all())
    assert sorted(d.currency for d in drafts) == ["GBP", "USD"]


def test_hold_invoices_for_missing_reports(org, family):
    set_settings(org, "delivery", {"delivery.hold_invoice_without_report": True})
    complete(org, lesson(org, family))
    today = now().date()
    with tenant_context(org):
        run, _created = services.create_run(
            period_start=today - timedelta(days=7), period_end=today, start_workflow=False
        )
        assert services.collect_run(run.pk)["drafts"] == 0


# --- actions (T05) ------------------------------------------------------------------------------


def issued_invoice(org, family, count=1):
    for i in range(count):
        complete(org, lesson(org, family, student=i, hours_ago=3 + i * 2))
    with tenant_context(org):
        return services.issue_invoice(services.create_draft(family["client"]), send=False)


def test_void_reverses_and_returns_charges(org, finance, family):
    invoice = issued_invoice(org, family)
    response = finance.post(f"/api/v1/invoices/{invoice.pk}/void", {"reason": "Wrong client"})
    assert response.json()["status"] == "void"
    with tenant_context(org):
        assert ledger.ledger_balance(family["client"], "GBP") == gbp("0.00")
        assert Charge.objects.get().status == "uninvoiced"
        assert Lesson.objects.get().lock_state == "unlocked"
        assert ClientLedgerEntry.objects.filter(type="invoice_void").count() == 1
    paid = issued_invoice(org, family)
    with tenant_context(org):
        services.allocate_payment(paid, gbp("10.00"))
    assert finance.post(f"/api/v1/invoices/{paid.pk}/void", {"reason": "x"}).status_code == 422


def test_partial_credit_note_and_credit_left_with_client(org, finance, family):
    invoice = issued_invoice(org, family, count=2)
    lines = finance.get(f"/api/v1/invoices/{invoice.pk}").json()["lines"]
    note = finance.post(
        f"/api/v1/invoices/{invoice.pk}/credit-note",
        {"reason": "Lesson cut short", "lines": [{"line": lines[0]["id"], "amount": "15.00"}]},
        format="json",
    )
    assert note.status_code == 201, note.json()
    assert (note.json()["number"], note.json()["total"]["amount"]) == ("CN-000001", "15.00")
    detail = finance.get(f"/api/v1/invoices/{invoice.pk}").json()
    assert detail["balance_due"]["amount"] == "65.00"
    assert detail["lines"][0]["credited"]["amount"] == "15.00"
    too_much = finance.post(
        f"/api/v1/invoices/{invoice.pk}/credit-note",
        {"reason": "x", "lines": [{"line": lines[0]["id"], "amount": "30.00"}]},
        format="json",
    )
    assert too_much.status_code == 422
    finance.post(
        f"/api/v1/invoices/{invoice.pk}/credit-note",
        {"reason": "Goodwill", "application": "credit",
         "lines": [{"line": lines[1]["id"], "amount": "10.00"}]},
        format="json",
    )  # fmt: skip
    balance = finance.get(f"/api/v1/clients/{family['client'].pk}/balance").json()
    assert balance["invoice_balance"]["amount"] == "65.00"
    assert balance["available_credit"]["amount"] == "10.00"
    applied = finance.post(f"/api/v1/invoices/{invoice.pk}/apply-credit", {}, format="json")
    assert applied.json()["applied"]["amount"] == "10.00"
    assert applied.json()["invoice"]["balance_due"]["amount"] == "55.00"


def test_write_off(org, finance, family):
    invoice = issued_invoice(org, family)
    done = finance.post(f"/api/v1/invoices/{invoice.pk}/write-off", {"reason": "Moved away"})
    assert done.json()["status"] == "written_off"
    with tenant_context(org):
        assert ledger.ledger_balance(family["client"], "GBP") == gbp("0.00")
    assert events_of(org, "invoice.written_off")[0]["amount"]["amount"] == "40.00"


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    credits=st.lists(st.integers(min_value=1, max_value=6000), min_size=1, max_size=5),
)
def test_credit_never_over_allocates(org, family, credits):
    """Property: applying credit never takes an invoice below zero or uses more credit
    than the client has."""
    from django.db import transaction

    with tenant_context(org):
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        services.create_ad_hoc_charge(
            client=client, student=student, description="Fee", unit_price=gbp("40.00")
        )
        invoice = services.issue_invoice(services.create_draft(client), send=False)
        given_credit = Decimal(0)
        for pence in credits:
            amount = Money.from_minor(pence, "GBP")
            given_credit += amount.amount
            with transaction.atomic():
                ledger.post(client, ClientLedgerEntry.Type.PAYMENT, -amount)
            services.apply_credit(invoice, quiet=True)
            invoice.refresh_from_db()
            assert invoice.balance_due.amount >= 0
            assert invoice.amount_credited.amount <= min(given_credit, Decimal(40))


# --- payment requests and prepaid credit (T06) --------------------------------------------------


def test_payment_request_credit_is_drawn_down_by_lessons(org, finance, family):
    """AC: a £400 request paid by card adds £400 of credit; completed lessons reduce it."""
    job = make_job(org, family, "prepaid_credit")
    created = finance.post(
        "/api/v1/payment-requests",
        {"client": str(family["client"].pk), "amount": {"amount": "400", "currency": "GBP"}},
        format="json",
    ).json()
    assert created["number"] == "PR-000001"
    with tenant_context(org):
        services.pay_payment_request(PaymentRequest.objects.get(), gbp("400.00"))
    balance = finance.get(f"/api/v1/clients/{family['client'].pk}/balance").json()
    assert balance["available_credit"]["amount"] == "400.00"
    for hours in (3, 6):
        complete(org, lesson(org, family, job=job, hours_ago=hours))
    balance = finance.get(f"/api/v1/clients/{family['client'].pk}/balance").json()
    assert balance["available_credit"]["amount"] == "320.00"
    with tenant_context(org):
        receipts = list(Invoice.objects.all())
    assert len(receipts) == 2
    assert {r.status for r in receipts} == {"paid"}
    ledger_rows = finance.get(f"/api/v1/clients/{family['client'].pk}/ledger").json()
    assert [r["type"] for r in ledger_rows][-1] == "payment_request_payment"
    assert ledger_rows[0]["balance_after"]["amount"] == "-320.00"


def test_negative_balance_guard_blocks_prepaid_completion(org, family):
    job = make_job(org, family, "prepaid_credit")
    the_lesson = lesson(org, family, job=job)
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation) as blocked:
            delivery.complete_lesson(the_lesson)
        assert blocked.value.extra["code"] == "insufficient_balance"
        family["client"].credit_limit_amount = Decimal("50")
        family["client"].save()
        delivery.complete_lesson(the_lesson)  # within the credit limit
    payg = lesson(org, family, hours_ago=6)
    complete(org, payg)  # pay-as-you-go clients are never blocked


def test_bulk_and_automatic_top_up_requests(org, finance, family):
    make_job(org, family, "prepaid_credit")
    bulk = finance.post(
        "/api/v1/payment-requests/bulk",
        {
            "below": {"amount": "50", "currency": "GBP"},
            "top_up_to": {"amount": "200", "currency": "GBP"},
        },
        format="json",
    )
    assert bulk.status_code == 201, bulk.json()
    [request] = bulk.json()["created"]
    assert request["amount"]["amount"] == "200.00"
    assert (
        finance.post(f"/api/v1/payment-requests/{request['id']}/cancel").json()["status"]
        == "cancelled"
    )
    set_settings(org, "billing", {"billing.topup_threshold": 30, "billing.topup_amount": 150})
    with tenant_context(org):
        auto = services.check_topup(family["client"])
        assert auto is not None
        assert auto.source == "threshold"
        assert services.check_topup(family["client"]) is None  # one open at a time
    assert events_of(org, "client.balance_low")


# --- invoicing in advance (T07) -----------------------------------------------------------------


def test_advance_invoicing_and_reconciliation(org, family):
    job = make_job(org, family, "invoice_in_advance")
    upcoming = [lesson(org, family, job=job, hours_ago=-24 * d) for d in (3, 10)]
    today = now().date()
    with tenant_context(org):
        run, _ = services.create_run(
            period_start=today,
            period_end=today + timedelta(days=30),
            mode=InvoiceRun.Mode.ADVANCE,
            start_workflow=False,
        )
        assert services.collect_run(run.pk)["drafts"] == 1
        services.issue_run(run.pk)
        invoice = Invoice.objects.get()
        assert invoice.total == gbp("80.00")
        # A free cancellation (well ahead) credits the next invoice.
        delivery.cancel_lesson(upcoming[1], cancelled_by="client")
        services.sync_lesson_charges(upcoming[1].pk)
        credit = Charge.objects.get(kind="reconciliation")
        assert credit.gross == gbp("-40.00")
        # Completing an advance-billed lesson doesn't charge it again.
    with tenant_context(org):
        Lesson.objects.filter(pk=upcoming[0].pk).update(
            start=now() - timedelta(hours=2), end=now() - timedelta(hours=1)
        )
        upcoming[0].refresh_from_db()
    assert complete(org, upcoming[0]) == []


# --- statements and ageing (T08) ----------------------------------------------------------------


def test_statement_and_ageing(org, finance, family):
    invoice = issued_invoice(org, family)
    with tenant_context(org):
        Invoice.objects.filter(pk=invoice.pk).update(due_date=now().date() - timedelta(days=40))
    statement = finance.get(
        f"/api/v1/clients/{family['client'].pk}/statement",
        {"from": str(now().date() - timedelta(days=5)), "to": str(now().date())},
    ).json()
    assert statement["opening"]["amount"] == "0.00"
    assert statement["closing"]["amount"] == "40.00"
    assert statement["ageing"]["thirty_one_to_60"]["amount"] == "40.00"
    pdf = finance.get(f"/api/v1/clients/{family['client'].pk}/statement", {"pdf": "true"})
    assert pdf.content.startswith(b"%PDF")
    rows = finance.get("/api/v1/billing/ageing").json()
    assert rows[0]["client_name"] == "The Patels"
    assert rows[0]["total"]["amount"] == "40.00"
    overdue = finance.get("/api/v1/invoices?overdue=true").json()["results"]
    assert [i["id"] for i in overdue] == [str(invoice.pk)]
    assert overdue[0]["is_overdue"] is True


def test_reminders_publish_once_per_offset(org, family):
    invoice = issued_invoice(org, family)
    with tenant_context(org):
        assert services.send_reminder(invoice.pk, 7, dedupe_key="k:7") is True
        assert services.send_reminder(invoice.pk, 7, dedupe_key="k:7") is True
    assert len(events_of(org, "invoice.reminder")) == 1  # the same step never repeats
    assert len(events_of(org, "invoice.overdue")) == 1
    with tenant_context(org):
        services.allocate_payment(invoice, gbp("40.00"))
        assert services.send_reminder(invoice.pk, 14) is False  # paid: no reminder


def test_scheduled_period():
    assert services.scheduled_period("monthly", date(2026, 3, 1)) == (
        date(2026, 2, 1),
        date(2026, 2, 28),
    )
    assert services.scheduled_period("weekly", date(2026, 10, 7)) == (
        date(2026, 9, 28),
        date(2026, 10, 4),
    )


# --- tenant isolation ---------------------------------------------------------------------------


def _client_with_invoice(organisation):
    with tenant_context(organisation):
        client = ClientFactory(organisation=organisation)
        services.create_ad_hoc_charge(client=client, description="Fee", unit_price=gbp("10"))
        return services.issue_invoice(services.create_draft(client), send=False)


class TestInvoiceIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/invoices"

    def make_object(self, organisation):
        return _client_with_invoice(organisation)


class TestChargeIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/charges"

    def make_object(self, organisation):
        invoice = _client_with_invoice(organisation)
        with tenant_context(organisation):
            return invoice.charges.get()


class TestCreditNoteIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/credit-notes"

    def make_object(self, organisation):
        invoice = _client_with_invoice(organisation)
        with tenant_context(organisation):
            return services.create_credit_note(invoice, reason="x")


class TestPaymentRequestIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/payment-requests"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.create_payment_request(
                client=ClientFactory(organisation=organisation), amount=gbp("50")
            )


class TestRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/invoice-runs"

    def make_object(self, organisation):
        with tenant_context(organisation):
            today = now().date()
            return services.create_run(period_start=today, period_end=today, start_workflow=False)[
                0
            ]


def test_credit_notes_are_numbered_without_gaps(org, family):
    invoice = issued_invoice(org, family, count=2)
    with tenant_context(org):
        lines = list(invoice.lines.all())
        first = services.create_credit_note(
            invoice, reason="a", lines=[{"line": lines[0], "amount": gbp("1")}]
        )
        with pytest.raises(BusinessRuleViolation):
            services.create_credit_note(invoice, reason="", lines=None)
        second = services.create_credit_note(invoice, reason="b")
    assert (first.number, second.number) == ("CN-000001", "CN-000002")
    assert second.application == CreditNote.Application.INVOICE
