"""E26-T01..T07: facts, FX, dashboards and widgets, standard reports, scoping, saved and
scheduled reports and exports."""

from __future__ import annotations

import io
import zipfile
from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.reporting import facts, fx, handlers, services
from tutortrack.reporting.models import (
    DailyAggregate,
    FactCharge,
    FactLesson,
    FactPayItem,
    FactPayment,
    FxRate,
    ReportRun,
    SavedReport,
    ScheduledReport,
)
from tutortrack.reporting.periods import Period, comparison, resolve
from tutortrack.reporting.reports.base import all_reports
from tutortrack.tenancy import settings_service

from .conftest import window

pytestmark = pytest.mark.django_db


def envelope(subject_id: Any, **data: Any) -> Any:
    return SimpleNamespace(subject={"id": str(subject_id)}, data=data)


def run(api: Any, key: str, **params: Any) -> dict[str, Any]:
    response = api.get(f"/api/v1/reporting/reports/{key}", params)
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    return body


# --- T01: facts, daily aggregates, FX -----------------------------------------------------------


def test_facts_mirror_lessons_charges_payments_and_pay(org, world):
    with tenant_context(org):
        done = FactLesson.objects.get(lesson_id=world["done_nia"].pk)
        assert (done.status, done.primary, done.minutes, done.delivered_minutes) == (
            "completed",
            True,
            60,
            60,
        )
        assert done.revenue_amount == Decimal("40.00")
        assert done.pay_amount == Decimal("25.00")
        assert FactLesson.objects.get(lesson_id=world["cancelled"].pk).status == "cancelled"
        assert FactLesson.objects.get(lesson_id=world["planned"].pk).status == "planned"
        assert FactCharge.objects.exclude(status="void").count() == 2
        assert FactPayment.objects.get().amount_amount == Decimal("30.00")
        assert FactPayItem.objects.filter(kind="lesson").count() == 2


def test_handlers_refresh_facts_incrementally(org, world):
    from tutortrack.delivery import services as delivery

    with tenant_context(org):
        lesson = world["planned"]
        with transaction.atomic():
            delivery.cancel_lesson(lesson, cancelled_by="admin", notify=False)
        assert FactLesson.objects.get(lesson_id=lesson.pk).status == "planned"  # not yet
        handlers.lesson_changed(envelope(lesson.pk))
        assert FactLesson.objects.get(lesson_id=lesson.pk).status == "cancelled"
        # A fact whose source is gone is removed.
        missing = FactCharge.objects.first()
        assert facts.refresh_charge(missing.charge_id) is True
        assert facts.refresh_charge("00000000-0000-0000-0000-000000000000") is False


def test_daily_aggregates_follow_the_facts(org, world):
    with tenant_context(org):
        day = FactLesson.objects.get(lesson_id=world["done_nia"].pk).date
        counts = DailyAggregate.objects.filter(currency="")
        assert sum(r.lessons_completed for r in counts) == 2
        money = DailyAggregate.objects.get(currency="GBP", date=day)
        assert money.revenue >= Decimal("40.00")
        assert sum(r.collected for r in DailyAggregate.objects.filter(currency="GBP")) == Decimal(
            "30.00"
        )


def test_fx_rates_are_stored_and_convert_with_half_up_rounding():
    assert fx.fetch_latest(fx.FakeProvider(day=date(2026, 1, 5))) > 5
    converter = fx.Converter()
    # 1 EUR = 0.85 GBP = 1.10 USD -> 10 GBP = 12.94 USD (12.941...)
    assert converter.convert(Decimal("10.00"), "GBP", "USD", date(2026, 1, 6)) == Decimal("12.94")
    assert converter.convert(Decimal("10.00"), "GBP", "GBP", date(2020, 1, 1)) == Decimal("10.00")
    assert fx.Converter().convert(Decimal(1), "GBP", "USD", date(2025, 1, 1)) is None  # no rate
    table = fx.EcbProvider.parse(
        b'<gesmes:Envelope xmlns:gesmes="x" xmlns="y"><Cube><Cube time="2026-10-09">'
        b'<Cube currency="USD" rate="1.0950"/><Cube currency="GBP" rate="0.8601"/></Cube>'
        b"</Cube></gesmes:Envelope>"
    )
    assert table.day == date(2026, 10, 9)
    assert table.rates["GBP"] == Decimal("0.8601")
    fx.store(table, "ecb")
    assert FxRate.objects.filter(date=date(2026, 10, 9)).count() == 2


def test_reports_convert_into_a_reporting_currency(org, world, api):
    fx.fetch_latest(fx.FakeProvider(day=date(2020, 1, 1)))
    body = run(api, "revenue", currency="USD", group_by="tutor", **window(org))
    assert {r["currency"] for r in body["rows"]} == {"USD"}
    assert {r["original_currency"] for r in body["rows"]} == {"GBP"}
    nia = next(r for r in body["rows"] if r["group"] == "Nia Okafor")
    assert Decimal(nia["net"]) == (Decimal("40") / Decimal("0.85") * Decimal("1.10")).quantize(
        Decimal("0.01")
    )
    assert body["totals"][0]["currency"] == "USD"


# --- periods ------------------------------------------------------------------------------------


def test_periods_and_comparisons():
    today = date(2026, 3, 15)
    month = resolve("this_month", today=today)
    assert (month.start, month.end) == (date(2026, 3, 1), date(2026, 3, 31))
    assert comparison(month) == Period(date(2026, 2, 1), date(2026, 2, 28))
    assert comparison(month, "previous_year") == Period(date(2025, 3, 1), date(2025, 3, 31))
    week = resolve("last_week", today=today)
    assert (week.start, week.end) == (date(2026, 3, 2), date(2026, 3, 8))
    q = resolve("last_quarter", today=today)
    assert (q.start, q.end) == (date(2025, 10, 1), date(2025, 12, 31))
    assert comparison(Period(date(2026, 3, 10), date(2026, 3, 19))) == Period(
        date(2026, 2, 28), date(2026, 3, 9)
    )
    with pytest.raises(ValueError, match="to must not"):
        resolve("custom", start=date(2026, 1, 2), end=date(2026, 1, 1))


# --- T02/T03: dashboards and widgets ------------------------------------------------------------


def test_sole_trader_gets_the_simple_dashboard(org, api):
    response = api.get("/api/v1/reporting/dashboard")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["preset"] == "simple"
    assert not body["customised"]
    assert [w["widget"] for w in body["widgets"]] == [
        "revenue",
        "outstanding",
        "lessons",
        "upcoming_today",
    ]


def test_roles_get_their_default_layouts(org, world):
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    widgets = [
        w["widget"] for w in coordinator.get("/api/v1/reporting/dashboard").json()["widgets"]
    ]
    assert "lessons" in widgets
    assert "revenue" not in widgets
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    widgets = [w["widget"] for w in finance.get("/api/v1/reporting/dashboard").json()["widgets"]]
    assert widgets[0] == "revenue"
    assert "next_pay_run" in widgets
    with tenant_context(org):
        settings_service.update_settings("reporting", {"reporting.dashboard_preset": "role"})
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    assert admin.get("/api/v1/reporting/dashboard").json()["preset"] == "owner"


def test_users_customise_and_reset_their_dashboard(org, api):
    layout = {"widgets": [{"widget": "lessons", "size": "l"}, {"widget": "revenue", "size": "s"}]}
    response = api.put("/api/v1/reporting/dashboard", layout, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["customised"] is True
    assert api.get("/api/v1/reporting/dashboard").json()["widgets"] == layout["widgets"]
    bad = api.put("/api/v1/reporting/dashboard", {"widgets": [{"widget": "nope"}]}, format="json")
    assert bad.status_code == 422
    assert api.delete("/api/v1/reporting/dashboard").status_code == 204
    assert api.get("/api/v1/reporting/dashboard").json()["customised"] is False
    assert api.get("/api/v1/reporting/widgets").status_code == 200


def test_widgets_compare_with_the_previous_period(org, world, api):
    params = {**window(org), "compare": "previous_period"}
    body = api.get("/api/v1/reporting/widgets/revenue", params).json()
    assert body["unit"] == "money"
    [value] = body["values"]
    assert (value["currency"], value["value"], value["previous"]) == ("GBP", "100.00", "0.00")
    assert body["widget"]["report"] == "revenue"
    assert body["report_params"]["period"] == "custom"
    lessons = api.get("/api/v1/reporting/widgets/lessons", params).json()
    assert [v["value"] for v in lessons["values"]] == ["2", "2.5"]
    outstanding = api.get("/api/v1/reporting/widgets/outstanding", params).json()
    assert outstanding["unit"] == "money"


def test_every_widget_computes(org, world, api):
    for info in api.get("/api/v1/reporting/widgets").json():
        response = api.get(f"/api/v1/reporting/widgets/{info['key']}", window(org))
        assert response.status_code == 200, (info["key"], response.content)
    assert api.get("/api/v1/reporting/widgets/nope").status_code == 404


def test_tutor_dashboard_shows_only_their_own_figures(org, world):
    tutor = client_for(org, world["nia_user"])
    widgets = [w["widget"] for w in tutor.get("/api/v1/reporting/dashboard").json()["widgets"]]
    assert widgets == ["upcoming_today", "lessons", "earnings", "overdue_reports"]
    lessons = tutor.get("/api/v1/reporting/widgets/lessons", window(org)).json()
    assert lessons["values"][0]["value"] == "1"  # Nia's lesson only
    earnings = tutor.get("/api/v1/reporting/widgets/earnings", window(org)).json()
    assert earnings["values"][0]["value"] == "25.00"
    assert tutor.get("/api/v1/reporting/widgets/revenue", window(org)).status_code == 404


# --- T04-T06: standard reports ------------------------------------------------------------------


def test_report_library_is_filtered_by_permission(org, world, api):
    keys = {r["key"] for r in api.get("/api/v1/reporting/reports").json()}
    assert {r.key for r in all_reports()} == keys
    tutor = client_for(org, world["nia_user"])
    mine = {r["key"] for r in tutor.get("/api/v1/reporting/reports").json()}
    assert "tutor_earnings" in mine
    assert "revenue" not in mine
    assert tutor.get("/api/v1/reporting/reports/revenue").status_code == 403
    assert api.get("/api/v1/reporting/reports/nope").status_code == 404


@pytest.mark.parametrize("key", sorted(r.key for r in all_reports()))
def test_every_report_runs_with_each_grouping(org, world, api, key):
    from tutortrack.reporting.reports.base import get

    report = get(key)
    for group in report.group_by or ("",):
        params = {**window(org), **({"group_by": group} if group else {})}
        body = run(api, key, **params)
        assert body["columns"], key
        assert body["report"]["key"] == key


def test_revenue_by_tutor_and_service(org, world, api):
    body = run(api, "revenue", group_by="tutor", ordering="-net", **window(org))
    assert [(r["group"], r["net"]) for r in body["rows"]] == [
        ("Sam Lee", "60.00"),
        ("Nia Okafor", "40.00"),
    ]
    assert body["totals"] == [
        {"currency": "GBP", "lines": 2, "net": "100.00", "tax": "0.00", "gross": "100.00"}
    ]
    assert body["chart"]["kind"] == "bar"
    filtered = run(api, "revenue", group_by="service", tutor=str(world["nia"].pk), **window(org))
    assert [(r["group"], r["net"]) for r in filtered["rows"]] == [("Maths 1:1", "40.00")]


def test_margin_is_revenue_less_tutor_pay(org, world, api):
    body = run(api, "margin", group_by="tutor", **window(org))
    nia = next(r for r in body["rows"] if r["group"] == "Nia Okafor")
    assert (nia["revenue"], nia["cost"], nia["margin"], nia["margin_percent"]) == (
        "40.00",
        "25.00",
        "15.00",
        "37.5",
    )
    assert body["totals"][0]["margin"] == "37.50"


def test_cash_forecast_prices_planned_lessons(org, world, api):
    body = run(api, "cash_forecast")
    first = body["rows"][0]
    assert (first["lessons"], first["revenue"], first["pay"]) == (1, "40.00", "25.00")


def test_aged_debtors_and_client_balances(org, world, api):
    from tutortrack.billing import services as billing

    with tenant_context(org), transaction.atomic():
        invoice = billing.create_draft(world["client"])
        billing.issue_invoice(invoice, send=False)
    body = run(api, "aged_debtors")
    [row] = body["rows"]
    assert row["client"] == "The Patels"
    balances = run(api, "client_balances")
    assert balances["rows"][0]["client"] == "The Patels"
    register = run(api, "invoices_register", **window(org))
    assert len(register["rows"]) == 1


def test_operations_reports(org, world, api):
    lessons = run(api, "lessons", group_by="status", **window(org))
    by = {r["group"]: r["lessons"] for r in lessons["rows"]}
    assert by == {"Cancelled": 1, "Completed": 2, "Planned": 1}
    util = run(api, "tutor_utilisation", **window(org))
    nia = next(r for r in util["rows"] if r["group"] == "Nia Okafor")
    assert Decimal(nia["available"]) > 0
    assert nia["lessons"] == 1
    cancellations = run(api, "cancellations", group_by="who", **window(org))
    assert cancellations["rows"][0]["cancellations"] == 1


def test_people_and_sales_reports(org, world, api):
    students = run(api, "active_students", group_by="service", **window(org))
    assert students["rows"][0]["students"] == 2
    ltv = run(api, "lifetime_value")
    assert ltv["rows"][0]["revenue"] == "100.00"
    compliance = run(api, "tutor_compliance")
    assert {r["group"] for r in compliance["rows"]} == {"Nia Okafor", "Sam Lee"}


def test_tutors_see_only_their_own_earnings_and_lessons(org, world):
    tutor = client_for(org, world["nia_user"])
    earnings = run(tutor, "tutor_earnings", group_by="tutor", **window(org))
    assert [r["group"] for r in earnings["rows"]] == ["Nia Okafor"]
    lessons = run(tutor, "lessons", group_by="tutor", **window(org))
    assert [r["group"] for r in lessons["rows"]] == ["Nia Okafor"]


def test_branch_scope_limits_figures(org, world):
    from tutortrack.identity.models import MembershipBranch
    from tutortrack.tenancy.tests.factories import BranchFactory

    other = BranchFactory(organisation=org, name="North")
    member = MembershipFactory(organisation=org, role="branch_manager", branch_scope="selected")
    with tenant_context(org):
        MembershipBranch.objects.create(membership=member, branch=other)
    manager = client_for(org, member.user)
    body = run(manager, "revenue", **window(org))
    assert body["rows"] == []


def test_invalid_parameters_are_rejected(org, api):
    bad = api.get("/api/v1/reporting/reports/revenue", {"group_by": "planet"})
    assert bad.status_code == 422
    assert api.get("/api/v1/reporting/reports/revenue", {"from": "nope"}).status_code == 422
    assert api.get("/api/v1/reporting/reports/revenue", {"tutor": "x"}).status_code == 422
    too_long = {"period": "custom", "from": "2020-01-01", "to": "2026-01-01"}
    assert api.get("/api/v1/reporting/reports/revenue", too_long).status_code == 422


# --- T07: exports, saved and scheduled reports --------------------------------------------------


def test_exports_csv_xlsx_and_pdf_are_audited(org, world, api):
    base = {**window(org), "group_by": "tutor"}
    csv = api.get("/api/v1/reporting/reports/revenue/export", {**base, "file_format": "csv"})
    assert csv.status_code == 200, csv.content
    assert csv["Content-Type"] == "text/csv"
    text = csv.content.decode("utf-8-sig")
    assert "Nia Okafor" in text
    assert "Total" in text
    xlsx = api.get("/api/v1/reporting/reports/revenue/export", {**base, "file_format": "xlsx"})
    sheet = zipfile.ZipFile(io.BytesIO(xlsx.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "Sam Lee" in sheet
    assert "<v>60.00</v>" in sheet
    pdf = api.get("/api/v1/reporting/reports/revenue/export", {**base, "file_format": "pdf"})
    assert pdf.content.startswith(b"%PDF")
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="export").count() == 3
        assert ReportRun.objects.filter(status="completed").count() == 3
        assert OutboxEvent.objects.filter(event_type="report.exported").count() == 3
    tutor = client_for(org, world["nia_user"])
    assert tutor.get("/api/v1/reporting/reports/lessons/export").status_code == 403


def test_csv_neutralises_formulas():
    from tutortrack.reporting.exports import to_csv
    from tutortrack.reporting.reports.base import Column, Result

    result = Result(
        columns=[Column("name", "Name"), Column("n", "N", "money")],
        rows=[{"name": "=HYPERLINK()", "n": "-5.00"}],
        totals=[],
    )
    text = to_csv(result).decode("utf-8-sig")
    assert "'=HYPERLINK()" in text
    assert ",-5.00" in text


def test_saved_reports_are_private_unless_shared(org, world, api):
    response = api.post(
        "/api/v1/saved-reports",
        {
            "name": "Monthly revenue",
            "report_key": "revenue",
            "params": {"period": "last_month", "group_by": "tutor"},
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    saved_id = response.json()["id"]
    assert response.json()["params"] == {"period": "last_month", "group_by": "tutor"}
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert finance.get(f"/api/v1/saved-reports/{saved_id}").status_code == 404
    assert (
        api.patch(f"/api/v1/saved-reports/{saved_id}", {"shared": True}, format="json").status_code
        == 200
    )
    assert finance.get(f"/api/v1/saved-reports/{saved_id}").status_code == 200
    assert (
        finance.patch(
            f"/api/v1/saved-reports/{saved_id}", {"name": "Mine"}, format="json"
        ).status_code
        == 403
    )
    bad = api.post(
        "/api/v1/saved-reports",
        {"name": "x", "report_key": "revenue", "params": {"group_by": "planet"}},
        format="json",
    )
    assert bad.status_code == 422
    assert api.delete(f"/api/v1/saved-reports/{saved_id}").status_code == 204


def _saved(org: Any, user: Any) -> SavedReport:
    with tenant_context(org), transaction.atomic():
        return services.create_saved_report(
            user, name="Revenue", report_key="revenue", params={"period": "this_month"}
        )


def test_scheduled_reports_only_go_to_allowed_staff(org, world, api, user):
    saved = _saved(org, user)
    finance_user = MembershipFactory(organisation=org, role="finance").user
    payload = {
        "saved_report": str(saved.pk),
        "frequency": "weekly",
        "weekday": 0,
        "time": "07:30",
        "format": "xlsx",
        "recipients": [str(finance_user.pk)],
    }
    response = api.post("/api/v1/scheduled-reports", payload, format="json")
    assert response.status_code == 201, response.content
    assert response.json()["recipient_details"][0]["email"] == finance_user.email
    with tenant_context(org):
        scheduled = ScheduledReport.objects.get()
        assert services.cron_for(scheduled) == ["30 7 * * 1"]
        assert OutboxEvent.objects.filter(event_type="scheduled_report.saved").exists()
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    bad = api.post(
        "/api/v1/scheduled-reports", {**payload, "recipients": [str(coordinator.pk)]}, format="json"
    )
    assert bad.status_code == 422  # coordinators can't see finance reports
    tutor = api.post(
        "/api/v1/scheduled-reports",
        {**payload, "recipients": [str(world["nia_user"].pk)]},
        format="json",
    )
    assert tutor.status_code == 422
    patched = api.patch(
        f"/api/v1/scheduled-reports/{scheduled.pk}",
        {"frequency": "monthly", "day_of_month": 3},
        format="json",
    )
    assert patched.status_code == 200
    with tenant_context(org):
        scheduled.refresh_from_db()
        assert services.cron_for(scheduled) == ["30 7 3 * *"]
    assert api.get("/api/v1/scheduled-reports/recipients").status_code == 200
    assert api.delete(f"/api/v1/scheduled-reports/{scheduled.pk}").status_code == 204


def test_scheduled_run_stores_the_file_and_emails_it(org, world, user, member, s3):
    saved = _saved(org, user)
    finance_user = MembershipFactory(organisation=org, role="finance").user
    with tenant_context(org), transaction.atomic():
        scheduled = services.create_scheduled_report(
            user,
            saved,
            recipients=[finance_user.pk],
            frequency="daily",
            time=time(7),
            format="csv",
        )
    with tenant_context(org):
        run_id = services.generate_scheduled_run(scheduled.pk, "scheduled-report:test-1")
        assert services.generate_scheduled_run(scheduled.pk, "scheduled-report:test-1") == run_id
        assert services.deliver_run(run_id) == 1
        assert services.deliver_run(run_id) == 1  # idempotent
        report_run = ReportRun.objects.get(pk=run_id)
        assert report_run.status == "delivered"
        assert report_run.file is not None
        assert report_run.recipients == [finance_user.email]
    [message] = mail.outbox
    assert message.to == [finance_user.email]
    assert message.attachments[0][0].endswith(".csv")
    downloads = client_for(org, finance_user).get(f"/api/v1/report-runs/{run_id}/download")
    assert downloads.status_code == 200, downloads.content


def test_paused_schedules_skip(org, user, member):
    saved = _saved(org, user)
    with tenant_context(org), transaction.atomic():
        scheduled = services.create_scheduled_report(
            user, saved, recipients=[user.pk], frequency="daily", time=time(7), enabled=False
        )
    with tenant_context(org):
        assert services.generate_scheduled_run(scheduled.pk, "k") == ""
        run_id = services.fail_run(scheduled.pk, "k2", "boom")
        assert ReportRun.objects.get(pk=run_id).status == "failed"


def test_rebuild_requires_reporting_manage(org, world, api):
    assert api.post("/api/v1/reporting/rebuild").json()["lessons"] == 4
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.post("/api/v1/reporting/rebuild").status_code == 403


# --- tenant isolation ---------------------------------------------------------------------------


class TestSavedReportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/saved-reports"

    def make_object(self, organisation):
        owner = UserFactory()
        MembershipFactory(organisation=organisation, user=owner)
        with tenant_context(organisation):
            return SavedReport.objects.create(
                name="x", report_key="revenue", owner=owner, shared=True
            )


class TestScheduledReportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/scheduled-reports"

    def make_object(self, organisation):
        owner = UserFactory()
        with tenant_context(organisation):
            saved = SavedReport.objects.create(name="x", report_key="revenue", owner=owner)
            return ScheduledReport.objects.create(
                saved_report=saved, frequency="daily", time=time(7)
            )


class TestReportRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/report-runs"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return ReportRun.objects.create(report_key="revenue", format="csv")


def test_organisation_reporting_currency_is_the_default(org, world, api):
    fx.fetch_latest(fx.FakeProvider(day=date(2020, 1, 1)))
    with tenant_context(org):
        settings_service.update_settings("reporting", {"reporting.currency": "USD"})
    body = run(api, "revenue", **window(org))
    assert {r["currency"] for r in body["rows"]} == {"USD"}
