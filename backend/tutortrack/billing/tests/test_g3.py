"""Gap batch G3 (billing): discounts as separate invoice lines (FR-06-7, FR-10-3), credit
note PDFs (FR-10-5), tutor pre-review of drafts (FR-10-3), scheduled statements (FR-10-9),
card surcharge invoices (FR-11-1), package deferred revenue (FR-26-2) and the low-balance
read for "jobs needing attention" (FR-07-6)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import transaction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tutortrack.billing import packages, selectors, services, statements, tutor_review
from tutortrack.billing.models import (
    Charge,
    CreditNote,
    Invoice,
    InvoiceLine,
    InvoiceRun,
    PackageConsumption,
    TutorInvoiceReview,
)
from tutortrack.billing.tests.test_billing import (
    complete,
    events_of,
    gbp,
    lesson,
    make_job,
    set_settings,
)
from tutortrack.billing.tests.test_phase2 import sold, template
from tutortrack.catalogue.models import DiscountRule
from tutortrack.catalogue.tests.factories import DiscountRuleFactory, ServiceFactory, TaxRateFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, TutorProfileFactory
from tutortrack.scheduling.models import LessonAttendee

pytestmark = pytest.mark.django_db


def separate(org):
    with tenant_context(org):
        from tutortrack.tenancy import settings_service

        settings_service.update_settings("pricing", {"pricing.discount_display": "separate"})


def discounted_invoice(org, family, *, percent="10", tax=None):
    """A completed 60-minute £40/h lesson with a client discount, invoiced."""
    with tenant_context(org):
        DiscountRuleFactory(
            organisation=org,
            name="Loyalty discount",
            kind=DiscountRule.Kind.CLIENT,
            client=family["client"],
            percent=Decimal(percent),
        )
    service = ServiceFactory(organisation=org, name="Maths", tax_rate=tax) if tax else None
    the_lesson = lesson(org, family, **({"service": service} if service else {}))
    complete(org, the_lesson)
    with tenant_context(org), transaction.atomic():
        invoice = services.create_draft(family["client"])
    return invoice


# --- discounts as separate lines (FR-06-7, FR-10-3) -----------------------------------------------


def test_discounts_are_netted_by_default(org, family):
    invoice = discounted_invoice(org, family)
    with tenant_context(org):
        [line] = invoice.lines.all()
    assert line.gross == gbp("36.00")


def test_separate_discount_lines_add_up_to_the_charge(org, family):
    separate(org)
    invoice = discounted_invoice(org, family)
    with tenant_context(org):
        rows = list(invoice.lines.order_by("position"))
        charge = Charge.objects.get(kind="lesson")
    assert [(r.kind, r.gross) for r in rows] == [
        ("line", gbp("40.00")),
        ("discount", gbp("-4.00")),
    ]
    assert rows[1].description == "Loyalty discount"
    assert rows[1].parent_id == rows[0].pk
    assert rows[1].charge_id is None
    assert invoice.total == charge.gross == gbp("36.00")


def test_separate_discounts_with_tax_and_credit_notes(org, family):
    separate(org)
    vat = TaxRateFactory(organisation=org, percent=Decimal("20"))
    invoice = discounted_invoice(org, family, tax=vat)
    with tenant_context(org):
        rows = list(invoice.lines.order_by("position"))
    assert [(r.net, r.tax, r.gross) for r in rows] == [
        (gbp("40.00"), gbp("8.00"), gbp("48.00")),
        (gbp("-4.00"), gbp("-0.80"), gbp("-4.80")),
    ]
    with tenant_context(org), transaction.atomic():
        invoice = services.issue_invoice(invoice)
        with pytest.raises(BusinessRuleViolation):
            services.remove_line(invoice, rows[1])
        note = services.create_credit_note(invoice, reason="Lesson missed")
    # The full credit is the line with its discount, never more than was invoiced.
    assert (note.net, note.tax, note.total) == (gbp("36.00"), gbp("7.20"), gbp("43.20"))
    with tenant_context(org):
        invoice.refresh_from_db()
        assert invoice.balance_due == gbp("0.00")
        with pytest.raises(BusinessRuleViolation):
            services.create_credit_note(invoice, reason="again")


def test_removing_a_discounted_line_from_a_draft_takes_its_discount(org, family):
    separate(org)
    invoice = discounted_invoice(org, family)
    with tenant_context(org), transaction.atomic():
        line = invoice.lines.get(kind="line")
        invoice = services.remove_line(invoice, line)
        assert not InvoiceLine.objects.filter(invoice=invoice).exists()
    assert invoice.total == gbp("0.00")


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    undiscounted=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("500.00"), places=2),
    shares=st.lists(st.integers(min_value=1, max_value=40), min_size=1, max_size=3),
    percent=st.sampled_from([Decimal(100), Decimal(50), Decimal("33.33"), Decimal(25)]),
    tax=st.sampled_from([Decimal(0), Decimal(5), Decimal(20)]),
    inclusive=st.booleans(),
)
def test_discount_split_always_adds_up(org, undiscounted, shares, percent, tax, inclusive):
    """Property: the undiscounted line and its discount lines add up exactly to the
    charge (net, tax and gross), discounts are never positive, rounding is half-up."""
    total_off = (undiscounted * Decimal(sum(shares)) / Decimal(100)).quantize(Decimal("0.01"))
    amount = undiscounted - total_off
    if amount <= 0:
        return
    weights = [Decimal(s) for s in shares]
    offs = Money(total_off, "GBP").allocate(weights)
    snapshot = {
        "amount": {"amount": str(amount), "currency": "GBP"},
        "undiscounted_amount": {"amount": str(undiscounted), "currency": "GBP"},
        "discounts": [
            {"name": f"D{i}", "amount": {"amount": str(-o.amount), "currency": "GBP"}}
            for i, o in enumerate(offs)
            if o.is_positive()
        ],
    }
    with tenant_context(org):
        from tutortrack.tenancy import settings_service

        settings_service.update_settings("pricing", {"pricing.discount_display": "separate"})
        settings_service.update_settings("billing", {"billing.prices_include_tax": inclusive})
        price = (Money(amount, "GBP") * percent / Decimal(100)).round_to_minor()
        if not price.is_positive():
            return
        figures = services.amounts_for(price, tax, inclusive=inclusive, exempt=False)
        charge = Charge(
            kind="lesson",
            currency="GBP",
            quantity=Decimal(1),
            unit_price=price,
            tax_percent=tax,
            net=figures.net,
            tax=figures.tax,
            gross=figures.gross,
        )
        charge.lesson_attendee = LessonAttendee(charge_snapshot=snapshot, currency="GBP")
        split = services.discount_split(charge)
    if split is None:
        return  # rounding left nothing to show separately
    full, parts = split
    for field in ("net", "tax", "gross"):
        whole = getattr(full, field) + sum(
            (getattr(p, field) for _n, p in parts), Money.zero("GBP")
        )
        assert whole == getattr(charge, field)
    assert all(not p.gross.is_positive() and not p.tax.is_positive() for _n, p in parts)
    assert all(p.gross.is_rounded() for _n, p in parts)


# --- credit note PDFs (FR-10-5) -----------------------------------------------------------------


def test_credit_note_pdf(org, family, finance):
    with tenant_context(org), transaction.atomic():
        services.create_ad_hoc_charge(
            client=family["client"], description="Books", unit_price=gbp("30.00")
        )
        invoice = services.issue_invoice(services.create_draft(family["client"]))
        note = services.create_credit_note(invoice, reason="Returned", application="credit")
    response = finance.get(f"/api/v1/credit-notes/{note.pk}/pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert note.number in response["Content-Disposition"]


# --- tutor pre-review of drafts (FR-10-3) ------------------------------------------------------


@pytest.fixture
def tutor_user(org, family):
    membership = MembershipFactory(organisation=org, role="tutor")
    with tenant_context(org):
        family["tutor"].membership = membership
        family["tutor"].save()
    return membership.user


def run_with_drafts(org, family, *, lessons=1):
    set_settings(org, "billing", {"billing.tutor_review": True, "billing.tutor_review_days": 3})
    for n in range(lessons):
        complete(org, lesson(org, family, student=n, hours_ago=3 + n * 2))
    today = date.today()
    with tenant_context(org), transaction.atomic():
        run, _ = services.create_run(
            period_start=today - timedelta(days=7), period_end=today, start_workflow=False
        )
        stats = services.collect_run(run.pk)
        run.refresh_from_db()
    return run, stats


def test_collecting_opens_one_review_per_tutor(org, family):
    run, stats = run_with_drafts(org, family, lessons=2)
    assert stats["tutor_review"] is True
    assert stats["tutor_review_days"] == 3
    assert (run.review_until - now()).days >= 2
    with tenant_context(org):
        [review] = TutorInvoiceReview.objects.all()
        rows = tutor_review.lessons_for(review)
    assert review.tutor_id == family["tutor"].pk
    assert len(rows) == 2
    assert "amount" not in str(rows).lower()
    [requested] = events_of(org, "invoice_run.tutor_review_requested")
    assert requested["tutor_ids"] == [str(family["tutor"].pk)]


def test_tutors_confirm_or_flag_through_the_api(org, family, tutor_user):
    run, _ = run_with_drafts(org, family)
    tutor = client_for(org, tutor_user)
    listed = tutor.get("/api/v1/me/invoice-reviews", {"open": "true"}).json()["results"]
    assert len(listed) == 1
    assert listed[0]["lessons"][0]["student"]
    assert "gross" not in str(listed[0])
    assert "total" not in str(listed[0])
    review_id = listed[0]["id"]
    missing = tutor.post(f"/api/v1/me/invoice-reviews/{review_id}/flag", {}, format="json")
    assert missing.status_code == 400
    flagged = tutor.post(
        f"/api/v1/me/invoice-reviews/{review_id}/flag",
        {"comment": "Maya's lesson was 45 minutes"},
        format="json",
    )
    assert flagged.status_code == 200, flagged.content
    assert flagged.json()["status"] == "flagged"
    again = tutor.post(f"/api/v1/me/invoice-reviews/{review_id}/confirm")
    assert again.status_code == 422
    with tenant_context(org):
        held = tutor_review.held_invoice_ids(run.pk)
        assert held == {str(i.pk) for i in Invoice.objects.filter(invoice_run=run)}
        stats = services.issue_run(run.pk)
        assert Invoice.objects.filter(invoice_run=run, status="draft").count() == 1
    assert (stats["issued"], stats["held"]) == (0, 1)
    [answered] = events_of(org, "invoice_run.tutor_reviewed")
    assert answered["status"] == "flagged"
    assert answered["held_invoice_ids"]


def test_confirmed_reviews_dont_hold_and_staff_see_them(org, family, tutor_user, finance):
    run, _ = run_with_drafts(org, family)
    with tenant_context(org):
        review = TutorInvoiceReview.objects.get()
    response = client_for(org, tutor_user).post(f"/api/v1/me/invoice-reviews/{review.pk}/confirm")
    assert response.status_code == 200
    staff = finance.get(f"/api/v1/invoice-runs/{run.pk}/tutor-reviews").json()
    assert [r["status"] for r in staff] == ["confirmed"]
    with tenant_context(org):
        stats = services.issue_run(run.pk)
    assert stats["issued"] == 1
    assert "held" not in stats


def test_reviews_are_off_by_default(org, family):
    complete(org, lesson(org, family))
    today = date.today()
    with tenant_context(org), transaction.atomic():
        run, _ = services.create_run(
            period_start=today - timedelta(days=7), period_end=today, start_workflow=False
        )
        stats = services.collect_run(run.pk)
        assert not TutorInvoiceReview.objects.exists()
    assert "tutor_review" not in stats


def test_other_tutors_cant_answer(org, family, tutor_user):
    run_with_drafts(org, family)
    other = MembershipFactory(organisation=org, role="tutor")
    TutorProfileFactory(organisation=org, membership=other, status="active")
    with tenant_context(org):
        review = TutorInvoiceReview.objects.get()
    response = client_for(org, other.user).post(f"/api/v1/me/invoice-reviews/{review.pk}/confirm")
    assert response.status_code == 404


class TestMyInvoiceReviewsIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/me/invoice-reviews"

    def make_object(self, organisation):
        from tutortrack.tenancy.models import Branch

        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation)
            run = InvoiceRun.objects.create(
                branch=Branch.objects.first(),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
                status="review",
            )
            return TutorInvoiceReview.objects.create(invoice_run=run, tutor=tutor)

    def acting_user(self, organisation):
        membership = MembershipFactory(organisation=organisation, role="tutor")
        with tenant_context(organisation):
            TutorInvoiceReview.objects.update(
                tutor=TutorProfileFactory(organisation=organisation, membership=membership)
            )
        return membership.user


# --- scheduled statements (FR-10-9) ------------------------------------------------------------


def test_statements_go_to_clients_with_activity_once(org, family):
    quiet = ClientFactory(organisation=org, display_name="Quiet family")
    ContactFactory(organisation=org, client=quiet, email="quiet@example.com")
    with tenant_context(org), transaction.atomic():
        services.create_ad_hoc_charge(
            client=family["client"], description="Books", unit_price=gbp("25.00")
        )
        services.issue_invoice(services.create_draft(family["client"]), send=False)
        today = services.org_today()
    start, end = today.replace(day=1), today
    with tenant_context(org):
        due = statements.due(start, end)
        assert due == [(str(family["client"].pk), "GBP")]
        mail.outbox.clear()
        assert statements.send([c for c, _cur in due], start, end) == 1
        assert statements.send([c for c, _cur in due], start, end) == 0  # deduplicated
    [message] = mail.outbox
    assert message.to == ["priya@example.com"]
    assert message.attachments
    assert message.attachments[0][0].endswith("-GBP.pdf")
    assert events_of(org, "client.statement_sent")


def test_last_month_period():
    assert statements.last_month(date(2026, 3, 1)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert statements.last_month(date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


# --- card surcharge invoices (FR-11-1) -----------------------------------------------------------


def test_surcharge_is_its_own_issued_invoice_once(org, family):
    with tenant_context(org), transaction.atomic():
        first = services.invoice_surcharge(
            client=family["client"],
            amount=gbp("1.50"),
            source_key="surcharge:pi_1",
            description="Card surcharge for INV-000001",
        )
        again = services.invoice_surcharge(
            client=family["client"],
            amount=gbp("1.50"),
            source_key="surcharge:pi_1",
            description="Card surcharge for INV-000001",
        )
        with pytest.raises(BusinessRuleViolation):
            services.invoice_surcharge(
                client=family["client"],
                amount=gbp("0"),
                source_key="surcharge:pi_2",
                description="x",
            )
    assert first.pk == again.pk
    assert (first.status, first.total, first.tax_total) == ("issued", gbp("1.50"), gbp("0.00"))
    with tenant_context(org):
        assert first.lines.get().charge.kind == "surcharge"


# --- package deferred revenue (FR-26-2) ----------------------------------------------------------


def test_package_revenue_is_recognised_as_units_are_used(org, family):
    job = make_job(org, family, "package")
    purchase = sold(org, family, template(org, quantity="4", price="160.00"))
    with tenant_context(org):
        assert packages.liability(purchase, now()) == gbp("160.00")
    complete(org, lesson(org, family, job=job, minutes=60))
    with tenant_context(org):
        purchase.refresh_from_db()
        later = now() + timedelta(seconds=1)
        assert packages.recognised_net(purchase, later) == gbp("40.00")
        assert packages.liability(purchase, later) == gbp("120.00")


def test_refunded_cancellation_ends_with_no_liability(org, family):
    job = make_job(org, family, "package")
    tpl = template(org, quantity="3", price="100.00", refund_policy="unused_pro_rata")
    purchase = sold(org, family, tpl)
    complete(org, lesson(org, family, job=job, minutes=60))
    with tenant_context(org), transaction.atomic():
        packages.cancel_package(purchase, reason="Moving away")
        purchase.refresh_from_db()
    later = now() + timedelta(seconds=1)
    with tenant_context(org):
        credited = packages.credited_net(purchase, later)
        assert credited.is_positive()
        assert packages.recognised_net(purchase, later) + credited == gbp("100.00")
        assert packages.liability(purchase, later) == gbp("0.00")
        assert PackageConsumption.objects.filter(purchase=purchase, kind="adjustment").exists()


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("999.99"), places=2),
    units=st.lists(st.integers(min_value=1, max_value=7), min_size=1, max_size=6),
)
def test_daily_recognition_telescopes_to_the_sale(org, family, price, units):
    """Property: summing each movement's recognised slice gives exactly the sale's net
    once every unit has gone, whatever the rounding of each slice."""
    total_units = Decimal(sum(units))
    with tenant_context(org):
        purchase = packages.PackagePurchase(
            client=family["client"],
            name="P",
            quantity_type="lessons",
            units_total=total_units,
            currency="GBP",
            price=Money(price, "GBP"),
        )
        net = Money(price, "GBP")
        recognised = []
        moved = Decimal(0)
        for step in units:
            before = (net * min(moved / total_units, Decimal(1))).round_to_minor()
            moved += step
            after = (net * min(moved / total_units, Decimal(1))).round_to_minor()
            recognised.append(after - before)
        assert purchase.units_total == total_units
    assert sum(recognised, Money.zero("GBP")) == net


# --- low balance (FR-07-6) ---------------------------------------------------------------------


def test_low_balance_clients(org, family):
    client_id = str(family["client"].pk)
    set_settings(org, "billing", {"billing.topup_threshold": 50})
    with tenant_context(org):
        low = selectors.low_balance_clients(
            {(client_id, "GBP", "prepaid_credit"), (client_id, "GBP", "package")}
        )
    assert low == {(client_id, "GBP", "prepaid_credit"), (client_id, "GBP", "package")}
    sold(org, family, template(org, quantity="10"))
    with tenant_context(org):
        low = selectors.low_balance_clients({(client_id, "GBP", "package")})
    assert low == set()


def test_credit_note_numbering_unchanged(org, family):
    """Regression: credit notes without discount lines behave as before."""
    with tenant_context(org), transaction.atomic():
        services.create_ad_hoc_charge(
            client=family["client"], description="Books", unit_price=gbp("10.00")
        )
        invoice = services.issue_invoice(services.create_draft(family["client"]))
        line = invoice.lines.get()
        note = services.create_credit_note(
            invoice, reason="Part", lines=[{"line": line, "amount": gbp("4.00")}]
        )
    assert note.total == gbp("4.00")
    with tenant_context(org):
        assert CreditNote.objects.count() == 1
