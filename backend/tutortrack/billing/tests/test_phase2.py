"""E10 Phase 2: packages (T12), recurring fixed fees with proration (T13), late fees and
collections (T14) and split billing (T15)."""

from __future__ import annotations

import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.billing import dunning, packages, plans, selectors, services, splits
from tutortrack.billing.models import (
    BillingPlan,
    Charge,
    CollectionsCase,
    CreditNote,
    Invoice,
    LateFeeRule,
    PackageConsumption,
    PackagePurchase,
)
from tutortrack.billing.tests.test_billing import (
    complete,
    events_of,
    gbp,
    lesson,
    make_job,
    set_settings,
)
from tutortrack.catalogue.models import PackageTemplate
from tutortrack.core.context import tenant_context
from tutortrack.core.events import subscribers_for
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.delivery import services as delivery
from tutortrack.people.tests.factories import ClientFactory, StudentFactory

pytestmark = pytest.mark.django_db


def template(org, *, quantity="10", kind="hours", price="350.00", **extra):
    with tenant_context(org):
        return PackageTemplate.objects.create(
            name=extra.pop("name", f"{quantity} {kind}"),
            quantity_type=kind,
            quantity=Decimal(quantity),
            currency="GBP",
            price_amount=Decimal(price),
            **extra,
        )


def sold(org, family, tpl, *, pay=True, **kwargs):
    """Sell and (by default) pay for a package; returns the active purchase."""
    with tenant_context(org), transaction.atomic():
        purchase = packages.sell_package(client=family["client"], template=tpl, **kwargs)
        invoice = Invoice.objects.get(charges__pk=purchase.charge_id)
        if pay and invoice.balance_due.is_positive():
            services.allocate_payment(invoice, invoice.balance_due)
        packages.activate_for_invoice(invoice.pk)  # the invoice.paid subscriber
        purchase.refresh_from_db()
    return purchase


def package_job(org, family):
    return make_job(org, family, "package")


def charges_of(org):
    with tenant_context(org):
        return list(Charge.objects.exclude(status="void").exclude(kind="package"))


# --- packages (T12) ---------------------------------------------------------------------------


def test_selling_invoices_then_activates_on_payment(org, family):
    tpl = template(org, validity_days=90)
    with tenant_context(org), transaction.atomic():
        purchase = packages.sell_package(client=family["client"], template=tpl)
        invoice = Invoice.objects.get(charges__pk=purchase.charge_id)
        assert invoice.lines.get().description == "Package: 10 hours"
    assert purchase.status == "pending"
    assert (invoice.status, invoice.total) == ("issued", gbp("350.00"))
    with tenant_context(org), transaction.atomic():
        assert packages.activate_for_invoice(invoice.pk) == []  # not paid yet
        services.allocate_payment(invoice, gbp("350.00"))
        [active] = packages.activate_for_invoice(invoice.pk)
    assert active.status == "active"
    assert active.expires_at is not None
    assert (active.expires_at - active.activated_at).days == 90
    assert events_of(org, "package.activated")
    names = {s.name for s in subscribers_for("invoice.paid")}
    assert any("activate_packages" in n for n in names)


def test_activation_on_issue_setting(org, family):
    set_settings(org, "billing", {"billing.package_activation": "issue"})
    purchase = sold(org, family, template(org), pay=False)
    assert purchase.status == "active"


def test_lessons_consume_hours_instead_of_charging(org, family):
    job = package_job(org, family)
    purchase = sold(org, family, template(org, quantity="10"))
    complete(org, lesson(org, family, job=job, minutes=60))
    complete(org, lesson(org, family, job=job, hours_ago=6, minutes=90))
    with tenant_context(org):
        purchase.refresh_from_db()
        rows = list(PackageConsumption.objects.filter(purchase=purchase))
    assert charges_of(org) == []
    assert purchase.units_used == Decimal("2.5")
    assert purchase.units_remaining == Decimal("7.5")
    assert [r.value for r in rows] == [gbp("35.00"), gbp("52.50")]


def test_overage_is_charged_for_the_part_not_covered(org, family):
    job = package_job(org, family)
    sold(org, family, template(org, quantity="1.5", price="60.00"))
    complete(org, lesson(org, family, job=job, minutes=120))  # £80 at £40/h; 75% covered
    [charge] = charges_of(org)
    assert charge.gross == gbp("20.00")


def test_changed_attendance_gives_units_back_and_takes_them_again(org, family):
    job = package_job(org, family)
    purchase = sold(org, family, template(org, quantity="5", kind="lessons", price="150.00"))
    the_lesson = lesson(org, family, job=job)
    complete(org, the_lesson)
    with tenant_context(org):
        attendee = the_lesson.attendees.get()
        delivery.record_attendance(
            the_lesson, [delivery.AttendanceRow(attendee.pk, "absent_notified")]
        )
        services.sync_lesson_charges(the_lesson.pk)
        purchase.refresh_from_db()
        assert purchase.units_used == 0
        delivery.record_attendance(the_lesson, [delivery.AttendanceRow(attendee.pk, "present")])
        services.sync_lesson_charges(the_lesson.pk)
        services.sync_lesson_charges(the_lesson.pk)  # idempotent
        purchase.refresh_from_db()
        kinds = list(
            PackageConsumption.objects.filter(purchase=purchase).values_list("kind", flat=True)
        )
    assert purchase.units_used == 1
    assert kinds == ["lesson", "reversal", "lesson"]
    assert charges_of(org) == []


def test_oldest_expiring_package_is_used_first_then_depletes_and_renews(org, family):
    job = package_job(org, family)
    later = sold(org, family, template(org, quantity="2", kind="lessons", validity_days=60))
    sooner = sold(
        org, family, template(org, quantity="1", kind="lessons", validity_days=10, auto_renew=True)
    )
    complete(org, lesson(org, family, job=job))
    with tenant_context(org):
        sooner.refresh_from_db()
        later.refresh_from_db()
    assert (sooner.status, sooner.units_used, later.units_used) == ("depleted", 1, 0)
    [depleted] = events_of(org, "package.depleted")
    assert depleted["auto_renew"] is True
    with tenant_context(org), transaction.atomic():
        renewal = packages.renew(sooner.pk)
        assert packages.renew(sooner.pk) is None  # once only
    assert (renewal.source, renewal.status) == ("renewal", "pending")


def test_low_balance_is_announced_once(org, family):
    job = package_job(org, family)
    sold(org, family, template(org, quantity="3", kind="lessons"))
    for hours in (3, 6):
        complete(org, lesson(org, family, job=job, hours_ago=hours))
    assert len(events_of(org, "package.low")) == 1


def test_credit_packages_cover_the_lesson_price(org, family):
    job = package_job(org, family)
    purchase = sold(org, family, template(org, quantity="50", kind="credit", price="50.00"))
    complete(org, lesson(org, family, job=job))  # £40
    complete(org, lesson(org, family, job=job, hours_ago=6))  # £10 left of £40
    with tenant_context(org):
        purchase.refresh_from_db()
    assert purchase.units_remaining == 0
    [charge] = charges_of(org)
    assert charge.gross == gbp("30.00")


def test_services_and_students_limit_which_package_is_used(org, family):
    from tutortrack.catalogue.tests.factories import ServiceFactory

    job = package_job(org, family)
    other = ServiceFactory(organisation=org, name="Science")
    tpl = template(org, kind="lessons")
    with tenant_context(org):
        tpl.services.set([other])
    sold(org, family, tpl)
    maya = family["students"][1]
    sold(org, family, template(org, kind="lessons", name="Maya only"), student=maya)
    complete(org, lesson(org, family, job=job))  # Arjun, Maths: neither package applies
    assert len(charges_of(org)) == 1


def test_expiry_writes_off_unused_units_as_revenue(org, family):
    purchase = sold(org, family, template(org, quantity="4", kind="lessons", price="100.00"))
    with tenant_context(org):
        PackagePurchase.objects.filter(pk=purchase.pk).update(expires_at=now() - timedelta(hours=1))
        assert packages.expire_package(purchase.pk) == "expired"
        assert packages.expire_package(purchase.pk) == "skipped"
        purchase.refresh_from_db()
        row = PackageConsumption.objects.get(purchase=purchase, kind="expiry")
    assert (purchase.status, purchase.units_expired, row.value) == ("expired", 4, gbp("100.00"))
    [event] = events_of(org, "package.expired")
    assert event["value"] == {"amount": "100.00", "currency": "GBP"}


def test_extend_moves_the_expiry(org, family):
    purchase = sold(org, family, template(org, validity_days=5))
    until = now() + timedelta(days=60)
    with tenant_context(org), transaction.atomic():
        packages.extend_package(purchase, until=until)
        assert packages.expire_package(purchase.pk).startswith("moved:")
        with pytest.raises(BusinessRuleViolation):
            packages.extend_package(purchase, until=now() - timedelta(days=1))


def test_cancel_credits_unused_value_by_credit_note(org, family):
    job = package_job(org, family)
    purchase = sold(
        org, family, template(org, quantity="4", kind="lessons", price="100.00",
                              refund_policy="unused_pro_rata"),
    )  # fmt: skip
    complete(org, lesson(org, family, job=job))
    with tenant_context(org), transaction.atomic():
        packages.cancel_package(purchase, reason="Moving away")
        note = CreditNote.objects.get()
        purchase.refresh_from_db()
    assert note.total == gbp("75.00")
    assert note.application == "credit"  # the invoice was already paid
    assert (purchase.status, purchase.units_remaining) == ("cancelled", 0)


def test_voiding_an_unpaid_sale_cancels_the_package(org, family):
    with tenant_context(org), transaction.atomic():
        purchase = packages.sell_package(client=family["client"], template=template(org))
        invoice = Invoice.objects.get(charges__pk=purchase.charge_id)
        services.void_invoice(invoice, reason="Sold by mistake")
        purchase.refresh_from_db()
        charge = Charge.objects.get(pk=purchase.charge_id)
    assert (purchase.status, charge.status) == ("cancelled", "void")


def test_package_api_sells_lists_and_extends(org, family, finance):
    tpl = template(org)
    response = finance.post(
        "/api/v1/packages",
        {"client": str(family["client"].pk), "template": str(tpl.pk)},
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["status"], body["invoice_number"]) == ("pending", "INV-000001")
    listed = finance.get("/api/v1/packages", {"client": str(family["client"].pk)}).json()
    assert [p["id"] for p in listed["results"]] == [body["id"]]
    cancelled = finance.post(
        f"/api/v1/packages/{body['id']}/cancel", {"reason": "Changed mind"}, format="json"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_imported_packages_are_active_with_what_is_left(org, family):
    with tenant_context(org), transaction.atomic():
        purchase = packages.import_package(
            client=family["client"],
            name="10 hours GCSE",
            quantity_type="hours",
            units_total=Decimal("10"),
            units_remaining=Decimal("4"),
            value_remaining=gbp("140.00"),
        )
        assert packages.discard_imported_package(purchase)
    assert purchase.units_total == 4
    assert packages.value_of(purchase, Decimal(1)) == gbp("35.00")


class TestPackageIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/packages"

    def make_object(self, organisation):
        client = ClientFactory(organisation=organisation)
        tpl = template(organisation)
        with tenant_context(organisation), transaction.atomic():
            return packages.sell_package(client=client, template=tpl)


# --- recurring fees with proration (T13) ------------------------------------------------------

INTERVALS = st.sampled_from(["weekly", "monthly", "termly"])
DAYS = st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31))


@settings(max_examples=150, deadline=None)
@given(interval=INTERVALS, anchor=DAYS, start=DAYS, length=st.integers(0, 800))
def test_segments_cover_the_plan_exactly_once(interval, anchor, start, length):
    end = start + timedelta(days=length)
    parts = list(plans.segments(interval, anchor, start, end))
    assert parts[0].start == start
    assert parts[-1].end == end
    for before, after in itertools.pairwise(parts):
        assert after.start == before.end + timedelta(days=1)
    for part in parts:
        assert part.period_start <= part.start <= part.end <= part.period_end
        assert Decimal(0) < part.fraction <= 1
    assert sum(p.days for p in parts) == length + 1


@settings(max_examples=150, deadline=None)
@given(
    interval=INTERVALS,
    anchor=DAYS,
    switch=DAYS,
    amount=st.decimals(min_value=Decimal("1"), max_value=Decimal("5000"), places=2),
)
def test_proration_of_a_split_period_adds_up_to_the_full_fee(interval, anchor, switch, amount):
    """A plan ending the day before another starts: the two parts of the shared period
    cost the full fee, give or take one minor unit of half-up rounding per part."""
    fee = Money(amount, "GBP")
    before = switch - timedelta(days=1)
    first = list(plans.segments(interval, anchor, switch - timedelta(days=400), before))[-1]
    second = next(plans.segments(interval, anchor, switch))
    full = plans.amount_for(fee, first, prorate=False)
    if first.period_start != second.period_start:  # switch fell on a boundary
        assert not second.partial
        assert plans.amount_for(fee, second, prorate=True) == full
        return
    parts = plans.amount_for(fee, first, prorate=True) + plans.amount_for(fee, second, prorate=True)
    assert abs((parts - full).amount) <= Decimal("0.01")
    assert plans.amount_for(fee, second, prorate=True) <= full


@settings(max_examples=100, deadline=None)
@given(day=st.integers(1, 31), months=st.integers(-30, 30))
def test_monthly_boundaries_keep_the_anchor_day_where_the_month_allows(day, months):
    import calendar

    anchor = date(2025, 1, day)
    moved = plans.boundary("monthly", anchor, months)
    last = calendar.monthrange(moved.year, moved.month)[1]
    assert moved.day == min(anchor.day, last)
    assert (moved.year * 12 + moved.month) - (2025 * 12 + 1) == months


def make_plan(org, family, **kwargs):
    values = {
        "client": family["client"],
        "description": "Monthly tuition",
        "amount": gbp("160.00"),
        "interval": "monthly",
        "start_date": date(2026, 9, 15),
        "anchor_date": date(2026, 9, 1),
        **kwargs,
    }
    with tenant_context(org), transaction.atomic():
        return plans.create_plan(**values)


def test_periods_are_charged_once_prorated_and_invoiced(org, family):
    plan = make_plan(org, family)
    with tenant_context(org), transaction.atomic():
        first = plans.next_period(plan.pk, "")
        assert first["start"] == "2026-09-15"
        assert plans.charge_period(plan.pk, "2026-09-15") == "charged"
        assert plans.charge_period(plan.pk, "2026-09-15") == "exists"
        assert plans.next_period(plan.pk, "")["start"] == "2026-10-01"
        assert plans.charge_period(plan.pk, "2026-10-01") == "charged"
        charges = list(Charge.objects.filter(kind="plan").order_by("date"))
        invoices = list(Invoice.objects.filter(charges__kind="plan").distinct())
    assert [c.gross for c in charges] == [gbp("85.33"), gbp("160.00")]  # 16 of 30 days
    assert "part period" in charges[0].description
    assert {i.status for i in invoices} == {"issued"}


def test_pausing_skips_periods_and_ending_stops_billing(org, family):
    plan = make_plan(org, family, start_date=date(2026, 9, 1), prorate=False)
    with tenant_context(org), transaction.atomic():
        plans.set_plan_status(plan, "paused")
        assert plans.next_period(plan.pk, "")["status"] == "paused"
        assert plans.charge_period(plan.pk, "2026-09-01") == "paused"
        plans.set_plan_status(plan, "active")
        plans.set_plan_status(plan, "ended")
        plan.refresh_from_db()
        with pytest.raises(BusinessRuleViolation):
            plans.update_plan(plan, amount=gbp("1.00"))
    assert plan.end_date is not None


def test_plans_that_follow_attendance_skip_periods_without_lessons(org, family):
    job = make_job(org, family, "recurring_fixed")
    plan = make_plan(
        org, family, job=job, start_date=date(2026, 9, 1), attendance_independent=False
    )
    with tenant_context(org), transaction.atomic():
        assert plans.charge_period(plan.pk, "2026-09-01") == "skipped"
    assert events_of(org, "billing_plan.period_skipped")


def test_lessons_on_recurring_fee_jobs_are_not_charged(org, family):
    job = make_job(org, family, "recurring_fixed")
    complete(org, lesson(org, family, job=job))
    assert charges_of(org) == []


def test_plan_api_creates_previews_and_pauses(org, family, finance):
    response = finance.post(
        "/api/v1/billing-plans",
        {
            "client": str(family["client"].pk),
            "description": "Weekly class",
            "amount": {"amount": "30.00", "currency": "GBP"},
            "interval": "weekly",
            "start_date": "2026-10-07",
            "anchor_date": "2026-10-05",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    plan_id = response.json()["id"]
    periods = finance.get(f"/api/v1/billing-plans/{plan_id}/periods").json()
    assert periods[0] == {
        "start": "2026-10-07",
        "end": "2026-10-11",
        "amount": {"amount": "21.43", "currency": "GBP"},
        "partial": True,
    }
    paused = finance.post(
        f"/api/v1/billing-plans/{plan_id}/status", {"status": "paused"}, format="json"
    )
    assert paused.json()["status"] == "paused"


class TestPlanIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/billing-plans"

    def make_object(self, organisation):
        client = ClientFactory(organisation=organisation)
        with tenant_context(organisation), transaction.atomic():
            return plans.create_plan(
                client=client,
                description="Fee",
                amount=gbp("10.00"),
                interval="monthly",
                start_date=date(2026, 9, 1),
            )


# --- late fees and collections (T14) ----------------------------------------------------------


def overdue_invoice(org, family, amount="100.00"):
    with tenant_context(org), transaction.atomic():
        services.create_ad_hoc_charge(
            client=family["client"], description="Tuition", unit_price=gbp(amount)
        )
        return services.issue_invoice(services.create_draft(family["client"]), send=False)


def rule(org, **values):
    with tenant_context(org), transaction.atomic():
        return dunning.save_rule(None, **values)


def test_fixed_late_fee_is_charged_once_per_application(org, family):
    invoice = overdue_invoice(org, family)
    fixed = rule(org, kind="fixed", amount=Decimal("15"), days_overdue=7)
    with tenant_context(org), transaction.atomic():
        assert dunning.fee_offsets(fixed) == [7]
        assert dunning.apply_late_fee(invoice.pk, 1) == "applied"
        assert dunning.apply_late_fee(invoice.pk, 1) == "exists"
        fee = Charge.objects.get(kind="late_fee")
    assert (fee.gross, fee.status, fee.invoice_id) == (gbp("15.00"), "uninvoiced", None)
    assert "INV-000001" in fee.description
    assert events_of(org, "late_fee.applied")[0]["number"] == 1


def test_percentage_fees_recur_monthly_up_to_the_cap(org, family):
    invoice = overdue_invoice(org, family, "200.00")
    monthly = rule(
        org, kind="percent", percent=Decimal("5"), recurrence="monthly", max_applications=3,
        cap=Decimal("25"), days_overdue=14,
    )  # fmt: skip
    with tenant_context(org), transaction.atomic():
        assert dunning.fee_offsets(monthly) == [14, 44, 74]
        outcomes = [dunning.apply_late_fee(invoice.pk, n) for n in (1, 2, 3)]
        fees = [c.gross for c in Charge.objects.filter(kind="late_fee").order_by("source_key")]
        assert dunning.apply_late_fee(invoice.pk, 4) == "capped"
    assert outcomes == ["applied", "applied", "applied"]
    assert fees == [gbp("10.00"), gbp("10.00"), gbp("5.00")]  # 5% of £200, capped at £25


def test_immediate_late_fees_get_their_own_invoice_without_fees_on_fees(org, family):
    invoice = overdue_invoice(org, family)
    rule(org, kind="fixed", amount=Decimal("10"), mode="immediate")
    with tenant_context(org), transaction.atomic():
        dunning.apply_late_fee(invoice.pk, 1)
        fee_invoice = Invoice.objects.exclude(pk=invoice.pk).get()
        assert dunning.apply_next_late_fee(fee_invoice.pk) == "only_fees"
    assert (fee_invoice.status, fee_invoice.total) == ("issued", gbp("10.00"))


def test_paid_invoices_get_no_fee_and_waiving_voids_or_credits(org, family):
    invoice = overdue_invoice(org, family)
    rule(org, kind="fixed", amount=Decimal("10"))
    with tenant_context(org), transaction.atomic():
        dunning.apply_late_fee(invoice.pk, 1)
        fee = Charge.objects.get(kind="late_fee")
        dunning.waive_late_fee(fee, reason="Goodwill")
        fee.refresh_from_db()
        assert fee.status == "void"
        services.allocate_payment(invoice, gbp("100.00"))
        assert dunning.apply_late_fee(invoice.pk, 2) == "closed"
    other = overdue_invoice(org, family)
    with tenant_context(org), transaction.atomic():
        dunning.apply_late_fee(other.pk, 1)
        fee = Charge.objects.exclude(status="void").get(kind="late_fee")
        fee_invoice = services.issue_invoice(services.create_draft(family["client"]), send=False)
        dunning.waive_late_fee(fee, reason="Bank delay")
        note = CreditNote.objects.get(invoice=fee_invoice)
    assert note.total == gbp("10.00")
    assert events_of(org, "late_fee.waived")


def test_a_new_rule_replaces_the_previous_one(org):
    first = rule(org, kind="fixed", amount=Decimal("5"))
    rule(org, kind="fixed", amount=Decimal("7"))
    with tenant_context(org):
        first.refresh_from_db()
        assert not first.active
        assert LateFeeRule.objects.filter(active=True).count() == 1
    with pytest.raises(BusinessRuleViolation):
        rule(org, kind="percent", percent=Decimal("0"))


def test_collections_open_a_task_and_block_until_paid(org, family):
    invoice = overdue_invoice(org, family)
    set_settings(org, "billing", {"billing.collections_block": "hard"})
    with tenant_context(org), transaction.atomic():
        assert dunning.open_collections(invoice.pk)
        assert not dunning.open_collections(invoice.pk)
        case = CollectionsCase.objects.get()
        assert Task.objects.get(pk=case.task_id).target_id == str(invoice.pk)
        assert selectors.booking_block(family["client"].pk) == "hard"
        services.allocate_payment(invoice, gbp("100.00"))
        dunning.close_collections(invoice.pk, reason="invoice.paid")  # the subscriber
        assert selectors.booking_block(family["client"].pk) == "none"
    assert events_of(org, "client.collections_opened")


def test_late_fee_rules_api(org, finance):
    created = finance.post(
        "/api/v1/billing/late-fee-rules",
        {"kind": "percent", "percent": "2.50", "days_overdue": 10, "recurrence": "monthly",
         "max_applications": 3},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.content
    listed = finance.get("/api/v1/billing/late-fee-rules").json()
    assert [r["percent"] for r in listed] == ["2.50"]


class TestCollectionsIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/billing/collections"

    def make_object(self, organisation):
        client = ClientFactory(organisation=organisation)
        with tenant_context(organisation), transaction.atomic():
            services.create_ad_hoc_charge(client=client, description="Fee", unit_price=gbp("10"))
            invoice = services.issue_invoice(services.create_draft(client), send=False)
            dunning.open_collections(invoice.pk)
            return CollectionsCase.objects.get(invoice=invoice)


# --- split billing (T15) ----------------------------------------------------------------------


def payers(org, n):
    return [ClientFactory(organisation=org, display_name=f"Payer {i}") for i in range(n)]


def test_splits_must_add_up_and_name_two_payers(org, family):
    job = make_job(org, family, "pay_as_you_go")
    a, b = payers(org, 2)
    with tenant_context(org), transaction.atomic():
        with pytest.raises(BusinessRuleViolation):
            splits.set_splits(job=job, shares=[(a, Decimal(60)), (b, Decimal(30))])
        with pytest.raises(BusinessRuleViolation):
            splits.set_splits(job=job, shares=[(a, Decimal(100))])
        rows = splits.set_splits(job=job, shares=[(a, Decimal(70)), (b, Decimal(30))])
    assert [r.percent for r in rows] == [70, 30]


def test_lesson_charges_are_split_between_payers(org, family):
    job = make_job(org, family, "pay_as_you_go")
    a, b, c = payers(org, 3)
    with tenant_context(org), transaction.atomic():
        splits.set_splits(
            job=job,
            shares=[(a, Decimal("33.33")), (b, Decimal("33.33")), (c, Decimal("33.34"))],
        )
    the_lesson = lesson(org, family, job=job)
    complete(org, the_lesson)
    with tenant_context(org):
        services.sync_lesson_charges(the_lesson.pk)  # idempotent with three charges
        rows = sorted(charges_of(org), key=lambda ch: ch.client.display_name)
    assert [(r.client_id, r.gross) for r in rows] == [
        (a.pk, gbp("13.33")),
        (b.pk, gbp("13.33")),
        (c.pk, gbp("13.34")),
    ]
    assert sum((r.gross for r in rows), gbp("0")) == gbp("40.00")


def test_student_split_applies_when_the_job_has_none(org, family):
    a, b = payers(org, 2)
    student = family["students"][0]
    with tenant_context(org), transaction.atomic():
        splits.set_splits(student=student, shares=[(a, Decimal(50)), (b, Decimal(50))])
    complete(org, lesson(org, family))
    assert {c.client_id for c in charges_of(org)} == {a.pk, b.pk}


def test_split_api(org, family, finance):
    job = make_job(org, family, "pay_as_you_go")
    a, b = payers(org, 2)
    response = finance.post(
        "/api/v1/billing/splits",
        {"job": str(job.pk), "shares": [{"client": str(a.pk), "percent": "50"},
                                         {"client": str(b.pk), "percent": "50"}]},
        format="json",
    )  # fmt: skip
    assert response.status_code == 200, response.content
    got = finance.get("/api/v1/billing/splits", {"job": str(job.pk)}).json()
    assert [s["client_name"] for s in got["shares"]] == ["Payer 0", "Payer 1"]


def test_student_split_rejects_another_currency(org, family):
    a = ClientFactory(organisation=org, currency="EUR")
    b = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=family["client"])
    with tenant_context(org), transaction.atomic(), pytest.raises(BusinessRuleViolation):
        splits.set_splits(student=student, shares=[(a, Decimal(50)), (b, Decimal(50))])


def test_new_events_are_registered():
    from tutortrack.core.events import EVENT_TYPES

    for key in (
        "package.purchased", "package.activated", "package.low", "package.depleted",
        "package.expiring", "package.expired", "late_fee.applied", "client.collections_opened",
        "billing_plan.created", "billing_split.changed",
    ):  # fmt: skip
        assert key in EVENT_TYPES
    assert BillingPlan.Interval.TERMLY == "termly"
