"""E12: pay profiles, pay items and holds, expenses, pay runs, statements, payouts, exports
and the tutor's earnings."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.models import AuditEntry
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.delivery import services as delivery
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import services as jobs
from tutortrack.payroll import services
from tutortrack.payroll.models import (
    ExpenseCategory,
    PayItem,
    Payout,
    PayRun,
    PayStatement,
)
from tutortrack.payroll.payouts.fake import FakePayouts
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


def snap(moment):
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


@pytest.fixture
def world(org) -> dict[str, Any]:
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor = TutorProfileFactory(organisation=org, status="active", first_name="Nia",
                                    membership=membership)  # fmt: skip
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        service = ServiceFactory(organisation=org)  # £40/h charge, £25/h pay
        job = jobs.create_job(client=client, service=service, students=[{"student": student}],
                              tutors=[{"tutor": tutor}], status="active")  # fmt: skip
        finance = MembershipFactory(organisation=org, role="finance")
    return {"tutor": tutor, "client": client, "student": student, "service": service,
            "job": job, "tutor_user": membership.user, "finance": finance.user}  # fmt: skip


def lesson(org, w, *, hours_ago=3, minutes=60) -> Lesson:
    start = snap(now() - timedelta(hours=hours_ago))
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start, end=start + timedelta(minutes=minutes), service=w["service"],
            job=w["job"], attendees=[{"student": w["student"]}], tutors=[{"tutor": w["tutor"]}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip


def completed(org, w, **kwargs) -> Lesson:
    item = lesson(org, w, **kwargs)
    with tenant_context(org):
        delivery.complete_lesson(item)
        services.sync_lesson_pay(item.pk)
    return item


def items(org, **filters) -> list[PayItem]:
    with tenant_context(org):
        return list(PayItem.objects.filter(**filters).order_by("created_at"))


# --- pay items (T02) ------------------------------------------------------------------------


def test_completed_lesson_creates_lesson_pay(org, world):
    done = completed(org, world)
    [item] = items(org, lesson=done)
    assert (item.kind, item.status, item.amount) == ("lesson", "ready", Money("25.00", "GBP"))
    assert item.quantity == Decimal("1.00")
    with tenant_context(org):
        services.sync_lesson_pay(done.pk)  # idempotent
    assert len(items(org, lesson=done)) == 1


def test_changing_a_lesson_replaces_open_pay_and_adjusts_paid_pay(org, world):
    done = completed(org, world)
    with tenant_context(org):
        Lesson.objects.filter(pk=done.pk).update(end=done.start + timedelta(minutes=90))
        from tutortrack.scheduling.pricing import price_lesson

        price_lesson(Lesson.objects.get(pk=done.pk))
        services.sync_lesson_pay(done.pk)
    live = [i for i in items(org, lesson=done) if i.status != "void"]
    assert [i.amount for i in live] == [Money("37.50", "GBP")]
    with tenant_context(org):
        PayItem.objects.filter(pk=live[0].pk).update(status="paid")
        Lesson.objects.filter(pk=done.pk).update(end=done.start + timedelta(minutes=60))
        price_lesson(Lesson.objects.get(pk=done.pk))
        services.sync_lesson_pay(done.pk)
    adjustment = items(org, lesson=done, kind="adjustment")[0]
    assert adjustment.amount == Money("-12.50", "GBP")


def test_cancellation_pay_follows_the_pay_share(org, world):
    planned = lesson(org, world, hours_ago=-48)
    with tenant_context(org):
        scheduling.cancel_lesson(planned, reason="Client cancelled", charge_percent=Decimal(100),
                                 pay_percent=Decimal(50))  # fmt: skip
        services.sync_lesson_pay(planned.pk)
    [item] = items(org, lesson=planned)
    assert (item.kind, item.amount) == ("cancellation", Money("12.50", "GBP"))
    with tenant_context(org):
        settings_service.update_settings("payroll", {"payroll.include_cancellations": False})
        services.sync_lesson_pay(planned.pk)
    assert [i.status for i in items(org, lesson=planned)] == ["void"]


def test_charge_shares_and_manual_items(org, world):
    from tutortrack.billing import services as billing

    with tenant_context(org):
        charge = billing.create_ad_hoc_charge(
            client=world["client"], description="Exam entry", unit_price=Money("60.00", "GBP"),
            tutor=world["tutor"], tutor_share=Money("15.00", "GBP"),
        )  # fmt: skip
        share = services.sync_charge_share(charge.pk)
        assert share is not None
        assert share.amount == Money("15.00", "GBP")
        billing.void_charge(charge, reason="mistake")
        services.sync_charge_share(charge.pk)
        share.refresh_from_db()
        assert share.status == "void"
        deduction = services.create_manual_item(
            tutor=world["tutor"], kind="deduction", description="Equipment",
            amount=Money("10.00", "GBP"), day=now().date(),
        )  # fmt: skip
    assert deduction.amount == Money("-10.00", "GBP")


def test_paid_events_use_the_hourly_rate(org, world):
    from tutortrack.scheduling.models import CalendarEvent, CalendarEventParticipant

    with tenant_context(org):
        services.update_profile(world["tutor"], hourly_rate=Decimal("18.00"))
        start = snap(now() - timedelta(days=1))
        event = CalendarEvent.objects.create(
            title="Training", start=start, end=start + timedelta(minutes=90),
            timezone="Europe/London", paid=True, type="training",
        )  # fmt: skip
        CalendarEventParticipant.objects.create(event=event, tutor=world["tutor"])
        assert services.sync_event_pay(now().date()) == 1
        assert services.sync_event_pay(now().date()) == 0
    [item] = items(org, kind="event")
    assert item.amount == Money("27.00", "GBP")


# --- holds (T03) ----------------------------------------------------------------------------


def test_overdue_report_holds_pay_until_written(org, world):
    from tutortrack.delivery.models import LessonReport

    done = completed(org, world)
    with tenant_context(org):
        report = LessonReport.objects.filter(lesson=done).first()
        if report is None:
            report = LessonReport.objects.create(
                lesson=done, tutor=world["tutor"], due_at=now() - timedelta(hours=1)
            )
        LessonReport.objects.filter(pk=report.pk).update(overdue_at=now())
        services.reevaluate_lessons([done.pk])
    [item] = items(org, lesson=done)
    assert (item.status, item.hold_reasons) == ("held", ["report_overdue"])
    with tenant_context(org):
        LessonReport.objects.filter(pk=report.pk).update(status="submitted")
        services.reevaluate_lessons([done.pk])
    assert items(org, lesson=done)[0].status == "ready"


def test_pay_when_client_paid(org, world):
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import Charge

    with tenant_context(org):
        settings_service.update_settings("payroll", {"payroll.pay_when_client_paid": True})
    done = completed(org, world)
    with tenant_context(org):
        billing.sync_lesson_charges(done.pk)
        services.reevaluate_lessons([done.pk])
    assert items(org, lesson=done)[0].hold_reasons == ["client_unpaid"]
    with tenant_context(org):
        draft = billing.create_draft(world["client"])
        invoice = billing.issue_invoice(draft)
        billing.allocate_payment(invoice, invoice.total)
        assert Charge.objects.filter(lesson=done, invoice__status="paid").exists()
        services.reevaluate_lessons([done.pk])
    assert items(org, lesson=done)[0].status == "ready"


def test_manual_hold_and_release(org, world):
    done = completed(org, world)
    [item] = items(org, lesson=done)
    with tenant_context(org):
        services.hold(item, note="Query from the family")
        item.refresh_from_db()
        assert (item.status, item.hold_reasons) == ("held", ["manual"])
        services.release(item)
        item.refresh_from_db()
    assert item.status == "ready"


# --- expenses (T04, T05) --------------------------------------------------------------------


@pytest.fixture
def categories(org) -> dict[str, ExpenseCategory]:
    with tenant_context(org):
        return {
            "books": ExpenseCategory.objects.create(name="Books", limit_amount=Decimal("50")),
            "mileage": ExpenseCategory.objects.create(
                name="Mileage", kind="mileage", mileage_rate=Decimal("0.45"), distance_unit="mi"
            ),
        }


def test_rebillable_expense_pays_the_tutor_and_charges_the_client(org, world, categories):
    """AC FR-12-4."""
    done = completed(org, world)
    with tenant_context(org):
        expense = services.submit_expense(
            tutor=world["tutor"], category=categories["books"], day=now().date(),
            description="Workbook", amount=Money("12.00", "GBP"), lesson=done, rebillable=True,
        )  # fmt: skip
        assert expense.client_id == world["client"].pk
        services.approve_expense(expense, user=world["finance"])
        from tutortrack.billing.models import Charge

        expense.refresh_from_db()
        charge = Charge.objects.get(pk=expense.charge_id)
    [reimbursement] = items(org, kind="expense")
    assert reimbursement.amount == Money("12.00", "GBP")
    assert (charge.client_id, charge.gross) == (world["client"].pk, Money("12.00", "GBP"))


def test_expense_rules(org, world, categories):
    with tenant_context(org):
        with pytest.raises(BusinessRuleViolation):
            services.submit_expense(tutor=world["tutor"], category=categories["books"],
                                    day=now().date(), description="Too much",
                                    amount=Money("80.00", "GBP"))  # fmt: skip
        mileage = services.submit_expense(
            tutor=world["tutor"], category=categories["mileage"], day=now().date(),
            description="To the Patels", distance=Decimal("12.5"),
        )  # fmt: skip
        assert mileage.amount == Money("5.63", "GBP")
        with pytest.raises(PermissionDenied):
            services.approve_expense(mileage, user=world["tutor_user"])
        with pytest.raises(BusinessRuleViolation):
            services.reject_expense(mileage, user=world["finance"], comment="")
        services.reject_expense(mileage, user=world["finance"], comment="Not a lesson day")
        mileage.refresh_from_db()
    assert mileage.status == "rejected"
    assert items(org, kind="mileage") == []


def test_mileage_suggestions_between_lessons():
    from tutortrack.payroll import travel

    leeds = travel.Place("Leeds", Decimal("53.800755"), Decimal("-1.549077"))
    york = travel.Place("York", Decimal("53.959965"), Decimal("-1.087298"))
    km = travel.road_km(leeds, york)
    assert Decimal("40") < km < Decimal("45")  # 34 km straight line x 1.25
    assert travel.in_unit(km, "mi") < km


# --- pay runs (T06-T10) ---------------------------------------------------------------------


def make_run(org, **kwargs) -> PayRun:
    today = now().date()
    with tenant_context(org):
        run, _ = services.create_pay_run(
            period_start=today - timedelta(days=30), period_end=today, start_workflow=False,
            **kwargs,
        )  # fmt: skip
        services.assemble(run.pk)
        run.refresh_from_db()
    return run


def test_pay_run_collects_items_and_flags_problems(org, world):
    completed(org, world)
    completed(org, world, hours_ago=6)
    with tenant_context(org):
        other = TutorProfileFactory(organisation=org, status="active")
        services.create_manual_item(tutor=other, kind="deduction", description="Penalty",
                                    amount=Money("5.00", "GBP"), day=now().date())  # fmt: skip
        services.update_profile(world["tutor"], method="bank_file")
    run = make_run(org)
    assert (run.status, run.totals) == ("review", {"GBP": "50.00"})
    codes = {w["code"] for w in run.warnings}
    assert {"negative", "no_bank_details"} <= codes
    with tenant_context(org):
        payout = Payout.objects.get(pay_run=run)
        assert payout.amount == Money("50.00", "GBP")
        assert PayItem.objects.get(tutor=other).status == "ready"  # carried forward


def test_dual_approval_above_the_threshold(org, world):
    completed(org, world)
    with tenant_context(org):
        settings_service.update_settings("payroll", {"payroll.dual_approval_threshold": "10"})
        second = MembershipFactory(organisation=org, role="finance").user
    run = make_run(org)
    assert run.approvals_required == 2
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        with pytest.raises(BusinessRuleViolation):
            services.approve(run, user=world["finance"])
        run = services.approve(run, user=second)
    assert run.status == "approved"
    assert items(org)[0].status == "approved"


def test_statements_payouts_and_bank_file(org, world):
    completed(org, world)
    with tenant_context(org):
        bank = {"country": "GB", "account_name": "N Okafor", "sort_code": "309634",
                "account_number": "12345678"}  # fmt: skip
        services.update_profile(world["tutor"], method="bank_file", vat_registered=True,
                                vat_number="GB123456789", bank=bank)  # fmt: skip
        services.agree_self_billing(world["tutor"])
        services.save_originator(name="Bright Minds Ltd",
                                 bank={"country": "GB", "sort_code": "200000",
                                       "account_number": "55779911"}, extra={})  # fmt: skip
        settings_service.update_settings("payroll", {"payroll.bank_file_format": "bacs18"})
    run = make_run(org)
    with tenant_context(org):
        services.approve(run, user=world["finance"])
        assert services.issue_statements(run.pk) == 1
        statement = PayStatement.objects.get()
        assert statement.kind == "self_billing"
        assert statement.number.startswith("SB-")
        assert statement.number.endswith("-0001")
        assert (statement.net, statement.vat) == (Money("25.00", "GBP"), Money("5.00", "GBP"))
        assert b"%PDF" in services.statement_pdf(statement)[:10]
        assert services.send_payouts(run.pk) == 1  # waiting for the bank file
        export = services.generate_bank_file(run, user=world["finance"])
        assert export.content.startswith("30963412345678099200000")
        services.mark_paid(run, reference="BACS 30 Oct")
        assert services.finalise(run.pk) == "paid"
    assert items(org)[0].status == "paid"


def test_stripe_payouts_and_failures(org, world):
    completed(org, world)
    with tenant_context(org):
        services.update_profile(world["tutor"], method="stripe_connect")
        services.stripe_onboarding_link(world["tutor"], return_url="https://x.test/back")
        profile = services.refresh_stripe(world["tutor"])
        assert profile.stripe_payouts_enabled
    FakePayouts.fail_for.add(profile.stripe_account_id)
    try:
        run = make_run(org)
        with tenant_context(org):
            services.approve(run, user=world["finance"])
            assert services.send_payouts(run.pk) == 0
            assert services.finalise(run.pk) == "partially_failed"
            payout = Payout.objects.get(pay_run=run)
            assert payout.status == "failed"
    finally:
        FakePayouts.fail_for.clear()
    [item] = items(org)
    assert (item.status, item.pay_run_id) == ("ready", None)  # back for the next run
    second = make_run(org)
    with tenant_context(org):
        services.approve(second, user=world["finance"])
        assert services.send_payouts(second.pk) == 0
        assert services.finalise(second.pk) == "paid"


def test_cancelling_a_run_returns_its_items(org, world):
    completed(org, world)
    run = make_run(org)
    with tenant_context(org):
        services.cancel_pay_run(run)
    assert items(org)[0].status == "ready"


def test_payroll_export_for_employees(org, world):
    completed(org, world)
    with tenant_context(org):
        services.update_profile(world["tutor"], method="external_payroll")
    run = make_run(org)
    with tenant_context(org):
        filename, content = services.payroll_export(run, "xero")
    assert filename.endswith("-xero.csv")
    assert content.splitlines()[1].startswith(
        f"{world['tutor'].full_name},Ordinary Hours,1.00,25.00"
    )


# --- API ------------------------------------------------------------------------------------


def test_pay_profile_api_masks_bank_details_and_audits_full_view(org, world):
    finance = client_for(org, world["finance"])
    path = f"/api/v1/tutors/{world['tutor'].pk}/pay-profile"
    saved = finance.put(path, {"country": "GB", "account_name": "N Okafor",
                               "sort_code": "30-96-34", "account_number": "12345678"})  # fmt: skip
    assert saved.status_code == 200, saved.content
    assert saved.json()["bank"]["account_number"] == "••••5678"
    full = finance.get(path, {"full": "true"}).json()
    assert full["bank"]["account_number"] == "12345678"
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="read", changes__reason="bank_details").exists()
    bad = finance.put(path, {"country": "GB", "account_name": "N", "sort_code": "1",
                             "account_number": "1"})  # fmt: skip
    assert bad.status_code == 422


def test_tutors_claim_expenses_and_see_their_own_earnings(org, world, categories):
    completed(org, world)
    tutor = client_for(org, world["tutor_user"])
    claim = tutor.post("/api/v1/expenses", {"category": str(categories["books"].pk),
                                             "date": now().date().isoformat(),
                                             "description": "Workbook",
                                             "amount": {"amount": "8.00", "currency": "GBP"}},
                       format="json")  # fmt: skip
    assert claim.status_code == 201, claim.content
    assert tutor.post(f"/api/v1/expenses/{claim.json()['id']}/approve").status_code == 403
    earnings = tutor.get("/api/v1/me/earnings").json()
    assert earnings["upcoming_total"] == {"GBP": "25.00"}
    with tenant_context(org):
        other = TutorProfileFactory(organisation=org, status="active")
        services.create_manual_item(tutor=other, kind="bonus", description="Thanks",
                                    amount=Money("5.00", "GBP"), day=now().date())  # fmt: skip
    mine = tutor.get("/api/v1/pay-items").json()["results"]
    assert {i["tutor"] for i in mine} == {str(world["tutor"].pk)}
    finance = client_for(org, world["finance"])
    approved = finance.post(f"/api/v1/expenses/{claim.json()['id']}/approve", {})
    assert approved.json()["status"] == "approved"


def test_pay_run_api(org, world):
    completed(org, world)
    finance = client_for(org, world["finance"])
    today = now().date()
    period = {"period_start": (today - timedelta(days=30)).isoformat(),
              "period_end": today.isoformat()}  # fmt: skip
    created = finance.post("/api/v1/pay-runs", period)
    assert created.status_code == 201
    run_id = created.json()["id"]
    with tenant_context(org):
        services.assemble(run_id)
    detail = finance.get(f"/api/v1/pay-runs/{run_id}").json()
    assert detail["payouts"][0]["amount"] == {"amount": "25.00", "currency": "GBP"}
    assert finance.post(f"/api/v1/pay-runs/{run_id}/approve").json()["status"] == "approved"
    paid = finance.post(f"/api/v1/pay-runs/{run_id}/mark-paid", {"reference": "Paid by hand"},
                        format="json")  # fmt: skip
    assert paid.json()["payouts"][0]["status"] == "paid"


class TestPayItemIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/pay-items"

    def make_object(self, organisation: Any) -> PayItem:
        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            return services.create_manual_item(
                tutor=tutor, kind="bonus", description="Bonus", amount=Money("5.00", "GBP"),
                day=now().date(),
            )  # fmt: skip

    def detail_url(self, obj: Any) -> str:
        return f"/api/v1/pay-items?tutor={obj.tutor_id}"

    def test_detail_of_other_organisation_is_404(self, org, other_org) -> None:
        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).get(self.detail_url(theirs))
        assert response.json()["results"] == []
