"""Gap G5 (FR-26-2, FR-26-4): referral, affiliate and review reports; room utilisation;
custom-field filters for students and tutors; tutor utilisation net of time off; scheduled
custom reports."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.db import transaction
from django.utils import timezone
from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.reporting import services
from tutortrack.reporting.models import CustomReport, ReportRun, ScheduledReport
from tutortrack.reporting.periods import org_timezone, org_today
from tutortrack.reporting.reports.operations import net_availability

from .conftest import window

pytestmark = pytest.mark.django_db


def run(api: Any, key: str, **params: Any) -> dict[str, Any]:
    response = api.get(f"/api/v1/reporting/reports/{key}", params)
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    return body


def set_fields(org: Any, obj: Any, **values: Any) -> None:
    with tenant_context(org):
        type(obj).objects.filter(pk=obj.pk).update(custom_fields=values)


@pytest.fixture
def coordinator(org: Any) -> Any:
    return client_for(org, MembershipFactory(organisation=org, role="coordinator").user)


# --- custom-field filters (students and tutors) -------------------------------------------------


def test_lesson_reports_filter_on_student_and_tutor_custom_fields(org, world, api):
    set_fields(org, world["students"][0], year_group="Y10")
    set_fields(org, world["students"][1], year_group="Y11")
    set_fields(org, world["nia"], contract="full_time")
    set_fields(org, world["sam"], contract="part_time", dbs=True)

    y10 = run(
        api, "lessons", group_by="status", custom_field="student.year_group=Y10", **window(org)
    )
    assert {r["group"]: r["lessons"] for r in y10["rows"]} == {
        "Cancelled": 1,
        "Completed": 1,
        "Planned": 1,
    }
    part_time = run(
        api, "lessons", group_by="tutor", custom_field="tutor.contract=part_time", **window(org)
    )
    assert [r["group"] for r in part_time["rows"]] == ["Sam Lee"]
    y11 = "student.year_group=Y11"
    students = run(api, "active_students", group_by="service", custom_field=y11, **window(org))
    assert students["rows"][0]["students"] == 1
    util = run(api, "tutor_utilisation", custom_field="tutor.contract=full_time", **window(org))
    assert [r["group"] for r in util["rows"]] == ["Nia Okafor"]
    revenue = run(
        api, "revenue", group_by="tutor", custom_field="student.year_group=Y10", **window(org)
    )
    assert [r["group"] for r in revenue["rows"]] == ["Nia Okafor"]
    # Yes/no values match "yes"; the compliance list follows tutors' fields.
    compliance = run(api, "tutor_compliance", custom_field="tutor.dbs=yes")
    assert [r["group"] for r in compliance["rows"]] == ["Sam Lee"]


def test_custom_field_filters_are_validated(org, world, api):
    def status(key: str, value: str) -> int:
        response = api.get(f"/api/v1/reporting/reports/{key}", {"custom_field": value})
        return int(response.status_code)

    assert status("aged_debtors", "student.year_group=Y10") == 422  # clients only
    assert status("lessons", "year_group=Y10") == 422  # bare keys mean clients
    assert status("lessons", "student.a__b=1") == 422  # not a lookup path
    assert status("lessons", "student.year_group") == 422
    assert status("aged_debtors", "school=state") == 200  # the E26 form still works
    library = {r["key"]: r for r in api.get("/api/v1/reporting/reports").json()}
    assert library["lessons"]["custom_field_entities"] == ["student", "tutor"]
    assert library["revenue"]["custom_field_entities"] == ["client", "student", "tutor"]
    assert library["aged_debtors"]["custom_field_entities"] == ["client"]
    assert library["pay_runs"]["custom_field_entities"] == []


# --- tutor utilisation net of time off ----------------------------------------------------------


def _next(day: Any, weekday: int) -> Any:
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def test_tutor_utilisation_is_net_of_time_off_and_adds_extra_availability(org, world, api):
    from tutortrack.scheduling.models import AvailabilityException

    with tenant_context(org):
        zone = ZoneInfo(org_timezone())
        start = org_today() - timedelta(days=10)
        monday, saturday = _next(start, 0), _next(start, 5)
        at = lambda day, hour: datetime.combine(day, time(hour), tzinfo=zone)  # noqa: E731
        nia = world["nia"]
        # A day off covering the whole Monday window (15:00-20:00) and more.
        AvailabilityException.objects.create(
            tutor=nia, type="off", start=at(monday, 9), end=at(monday, 21)
        )
        # Extra Saturday hours; a requested (not approved) day off is ignored.
        AvailabilityException.objects.create(
            tutor=nia, type="extra", start=at(saturday, 10), end=at(saturday, 12)
        )
        AvailabilityException.objects.create(
            tutor=nia,
            type="off",
            status="requested",
            start=at(monday + timedelta(days=1), 9),
            end=at(monday + timedelta(days=1), 21),
        )
    body = run(api, "tutor_utilisation", **window(org))
    row = next(r for r in body["rows"] if r["group"] == "Nia Okafor")
    assert (row["time_off"], row["extra"]) == ("5.0", "2.0")
    assert Decimal(row["available"]) == Decimal(row["weekly"]) - 5 + 2
    assert Decimal(row["weekly"]) % 5 == 0  # whole weekday windows only
    assert {c["key"] for c in body["columns"]} >= {"weekly", "time_off", "extra", "available"}
    assert body["totals"][0]["time_off"] == "5.0"


BASE = datetime(2026, 1, 5, tzinfo=ZoneInfo("UTC"))
spans = st.lists(st.tuples(st.integers(0, 600), st.integers(1, 180)), max_size=6).map(
    lambda xs: [(BASE + timedelta(minutes=a), BASE + timedelta(minutes=a + n)) for a, n in xs]
)


def _minute(moment: datetime) -> int:
    return int((moment - BASE).total_seconds() // 60)


def _minutes(items: list[tuple[datetime, datetime]]) -> set[int]:
    out: set[int] = set()
    for start, end in items:
        out |= set(range(_minute(start), _minute(end)))
    return out


@settings(max_examples=200, deadline=None)
@given(windows=spans, off=spans, extra=spans)
def test_net_availability_matches_minute_sets(windows, off, extra):
    figures = net_availability(windows, off, extra)
    w, o, e = _minutes(windows), _minutes(off), _minutes(extra)
    assert figures["weekly"] == len(w)
    assert figures["off"] == len(w & o)
    assert figures["extra"] == len(e - w - o)
    assert figures["available"] == len((w | e) - o)
    assert figures["available"] >= 0


# --- room utilisation ---------------------------------------------------------------------------


def test_room_utilisation_per_room_against_opening_hours(org, world, api):
    from tutortrack.catalogue.tests.factories import LocationFactory, RoomFactory
    from tutortrack.scheduling.models import Lesson

    weekdays = {
        d: [{"start": "09:00", "end": "17:00"}] for d in ("mon", "tue", "wed", "thu", "fri")
    }
    centre = LocationFactory(organisation=org, name="High Street", opening_hours=weekdays)
    studio = RoomFactory(organisation=org, location=centre, name="Studio", capacity=4)
    RoomFactory(organisation=org, location=centre, name="Library", capacity=2)
    RoomFactory(organisation=org, location=centre, name="Old store", active=False)
    with tenant_context(org):
        Lesson.objects.filter(pk__in=[world["done_nia"].pk, world["cancelled"].pk]).update(
            room=studio
        )
    params = window(org)
    body = run(api, "room_utilisation", **params)
    rows = {r["group"]: r for r in body["rows"]}
    assert set(rows) == {"Studio", "Library"}  # inactive rooms without lessons are left out
    first = datetime.fromisoformat(params["from"]).date()
    days = [first + timedelta(days=n) for n in range(21)]
    open_hours = Decimal(8 * sum(1 for d in days if d.weekday() < 5))
    studio_row = rows["Studio"]
    assert (studio_row["lessons"], studio_row["hours"]) == (1, "1.0")  # not the cancelled one
    assert Decimal(studio_row["open_hours"]) == open_hours
    assert studio_row["fill"] == "25.0"  # one attendee in a room for four
    assert studio_row["location"] == "High Street"
    assert rows["Library"]["lessons"] == 0
    assert body["totals"][0]["lessons"] == 1
    tutor = client_for(org, world["nia_user"])
    own = tutor.get("/api/v1/reporting/reports/room_utilisation", window(org))
    assert own.status_code == 200
    assert [r["group"] for r in own.json()["rows"]] == ["Studio"]  # rooms they taught in


# --- referral, affiliate and review reports ------------------------------------------------------


def test_referral_performance(org, coordinator):
    from tutortrack.growth.tests.factories import ReferralFactory, ReferralProgramFactory

    program = ReferralProgramFactory(organisation=org, name="Refer a friend")
    ReferralFactory(
        organisation=org,
        program=program,
        status="rewarded",
        converted_at=timezone.now(),
        rewarded_at=timezone.now(),
        currency="GBP",
        referrer_credit_amount=Decimal("20.00"),
    )
    ReferralFactory(organisation=org, program=program)
    ReferralFactory(organisation=org, program=program, status="blocked")
    body = run(coordinator, "referral_performance", group_by="program")
    [row] = body["rows"]
    assert row["group"] == "Refer a friend"
    assert (row["referrals"], row["converted"], row["rewarded"], row["held"]) == (3, 1, 1, 1)
    assert (row["conversion_rate"], row["rewards"], row["currency"]) == ("33.3", "20.00", "GBP")
    by_status = run(coordinator, "referral_performance", group_by="status")
    assert {r["group"]: r["referrals"] for r in by_status["rows"]} == {
        "Waiting for the milestone": 1,
        "Rewarded": 1,
        "Held by fraud checks": 1,
    }


def test_affiliate_performance(org, coordinator):
    from tutortrack.growth.models import CommissionItem
    from tutortrack.growth.tests.factories import (
        AffiliateFactory,
        AffiliateLinkFactory,
        AffiliateReferralFactory,
    )

    partner = AffiliateFactory(organisation=org, name="Tutor Times")
    AffiliateLinkFactory(organisation=org, affiliate=partner, clicks=40)
    converted = AffiliateReferralFactory(
        organisation=org, affiliate=partner, converted_at=timezone.now()
    )
    AffiliateReferralFactory(organisation=org, affiliate=partner)
    with tenant_context(org):
        for n, (kind, amount) in enumerate(
            (("commission", "20.00"), ("clawback", "-5.00"), ("adjustment", "1.00"))
        ):
            CommissionItem.objects.create(
                affiliate=partner,
                referral=converted,
                client=converted.client,
                kind=kind,
                source_key=f"test:{n}",
                currency="GBP",
                amount_amount=Decimal(amount),
                earned_at=timezone.now(),
            )
    body = run(coordinator, "affiliate_performance")
    [row] = body["rows"]
    assert (row["group"], row["clicks"], row["referred"], row["converted"]) == (
        "Tutor Times",
        40,
        2,
        1,
    )
    assert (row["earned"], row["clawed_back"], row["adjusted"], row["net"]) == (
        "20.00",
        "-5.00",
        "1.00",
        "16.00",
    )
    assert (row["paid"], row["unpaid"], row["conversion_rate"]) == ("0.00", "16.00", "50.0")
    assert body["totals"] == [
        {
            "currency": "GBP",
            "clicks": 40,
            "referred": 2,
            "converted": 1,
            "earned": "20.00",
            "clawed_back": "-5.00",
            "adjusted": "1.00",
            "net": "16.00",
            "paid": "0.00",
            "unpaid": "16.00",
        }
    ]


def test_review_scores(org, coordinator):
    from tutortrack.growth.tests.factories import ReviewFactory, ReviewRequestFactory
    from tutortrack.people.tests.factories import TutorProfileFactory

    nia = TutorProfileFactory(organisation=org, first_name="Nia", last_name="Okafor")
    ReviewFactory(organisation=org, tutor=nia, rating=5, status="approved", response="Thanks!")
    ReviewFactory(organisation=org, tutor=nia, rating=4, status="approved")
    ReviewFactory(organisation=org, tutor=nia, rating=1)
    ReviewFactory(organisation=org, rating=5)  # about the business
    for status in ("submitted", "submitted", "submitted", "pending"):
        ReviewRequestFactory(organisation=org, tutor=nia, status=status, sent_at=timezone.now())
    body = run(coordinator, "review_scores", group_by="tutor")
    rows = {r["group"]: r for r in body["rows"]}
    row = rows["Nia Okafor"]
    assert (row["reviews"], row["average"], row["five_star"], row["low"]) == (3, "3.33", "33.3", 1)
    assert (row["approved"], row["pending"], row["reply_rate"]) == (2, 1, "33.3")
    assert (row["requested"], row["request_answer_rate"]) == (4, "75.0")
    assert rows["The business"]["reviews"] == 1
    assert body["totals"][0]["average"] == "3.75"  # the overall average, not a sum
    by_source = run(coordinator, "review_scores", group_by="source")
    assert "requested" not in {c["key"] for c in by_source["columns"]}


def test_copilot_redacts_names_in_the_growth_reports():
    """The E31 copilot replaces people's names before a report reaches the model."""
    from tutortrack.ai.tools import NAME_GROUPS
    from tutortrack.reporting.reports.base import get

    people = {"referrer", "affiliate", "tutor"}
    for key in ("referral_performance", "affiliate_performance", "review_scores"):
        report = get(key)
        assert report is not None
        assert {g for g in report.group_by if g in people} <= set(NAME_GROUPS)


def test_growth_reports_need_the_growth_permission_too(org, world):
    finance = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    keys = {r["key"] for r in finance.get("/api/v1/reporting/reports").json()}
    # Finance holds the referral and affiliate rights, but not the reviews one.
    assert {"referral_performance", "affiliate_performance"} <= keys
    assert "review_scores" not in keys
    assert finance.get("/api/v1/reporting/reports/review_scores").status_code == 403
    tutor = client_for(org, world["nia_user"])
    assert tutor.get("/api/v1/reporting/reports/referral_performance").status_code == 403


# --- scheduled custom reports (FR-26-4) ---------------------------------------------------------

DEFINITION = {
    "dataset": "lessons",
    "group_by": ["status"],
    "measures": ["lessons"],
    "period": "all",
}


def _custom(org: Any, owner: Any, name: str = "Lessons by status") -> CustomReport:
    with tenant_context(org), transaction.atomic():
        return services.save_custom_report(owner, name=name, definition=DEFINITION)


def test_custom_reports_can_be_scheduled(org, world):
    owner = MembershipFactory(organisation=org, role="coordinator").user
    report = _custom(org, owner)
    api = client_for(org, owner)
    colleague = MembershipFactory(organisation=org, role="coordinator").user
    finance_user = MembershipFactory(organisation=org, role="finance").user
    payload = {
        "custom_report": str(report.pk),
        "frequency": "monthly",
        "day_of_month": 1,
        "time": "08:30",
        "format": "csv",
        "recipients": [str(colleague.pk), str(finance_user.pk)],
    }
    created = api.post("/api/v1/scheduled-reports", payload, format="json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["report_name"], body["report_key"]) == (
        "Lessons by status",
        f"custom:{report.pk}",
    )
    assert body["saved_report"] is None
    listed = api.get("/api/v1/scheduled-reports").json()["results"]
    assert [s["id"] for s in listed] == [body["id"]]  # the own scope covers custom reports
    with tenant_context(org):
        assert services.cron_for(ScheduledReport.objects.get(pk=body["id"])) == ["30 8 1 * *"]
    both = api.post(
        "/api/v1/scheduled-reports",
        {**payload, "saved_report": str(report.pk)},
        format="json",
    )
    assert both.status_code in (400, 422)
    neither = {k: v for k, v in payload.items() if k != "custom_report"}
    assert api.post("/api/v1/scheduled-reports", neither, format="json").status_code in (400, 422)


def test_scheduled_custom_report_runs_as_owner_and_is_emailed(org, world, s3):
    owner = MembershipFactory(organisation=org, role="coordinator").user
    report = _custom(org, owner)
    recipient = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org), transaction.atomic():
        scheduled = services.create_scheduled_report(
            owner, report, recipients=[recipient.pk], frequency="daily", time=time(7)
        )
    with tenant_context(org):
        run_id = services.generate_scheduled_run(scheduled.pk, "scheduled-report:custom-1")
        assert services.generate_scheduled_run(scheduled.pk, "scheduled-report:custom-1") == run_id
        assert services.deliver_run(run_id) == 1
        report_run = ReportRun.objects.get(pk=run_id)
        assert report_run.report_key == f"custom:{report.pk}"
        assert report_run.requested_by_id == owner.pk
        assert report_run.row_count == 3  # completed, cancelled, planned
        assert report_run.file is not None
    [message] = mail.outbox
    assert message.to == [recipient.email]
    assert message.attachments[0][0] == "lessons-by-status.csv"
    assert "/analytics/builder" in message.body
    runs = client_for(org, owner).get("/api/v1/report-runs").json()["results"]
    assert runs[0]["saved_report_name"] == "Lessons by status"


def test_coordinators_cannot_receive_finance_custom_reports(org, world):
    owner = MembershipFactory(organisation=org, role="finance").user
    with tenant_context(org), transaction.atomic():
        report = services.save_custom_report(
            owner,
            name="Charges",
            definition={"dataset": "charges", "group_by": ["kind"], "measures": ["count"]},
        )
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    response = client_for(org, owner).post(
        "/api/v1/scheduled-reports",
        {
            "custom_report": str(report.pk),
            "frequency": "daily",
            "time": "07:00",
            "recipients": [str(coordinator.pk)],
        },
        format="json",
    )
    assert response.status_code == 422


def test_deleting_a_custom_report_removes_its_schedules(org, world):
    owner = MembershipFactory(organisation=org, role="coordinator").user
    report = _custom(org, owner)
    with tenant_context(org), transaction.atomic():
        scheduled = services.create_scheduled_report(
            owner, report, recipients=[owner.pk], frequency="weekly", weekday=4, time=time(17)
        )
    assert client_for(org, owner).delete(f"/api/v1/custom-reports/{report.pk}").status_code == 204
    with tenant_context(org):
        assert not ScheduledReport.objects.filter(pk=scheduled.pk).exists()
        assert OutboxEvent.objects.filter(event_type="scheduled_report.deleted").exists()


class TestScheduledCustomReportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/scheduled-reports"

    def make_object(self, organisation):
        owner = UserFactory()
        with tenant_context(organisation):
            report = CustomReport.objects.create(
                name="x", dataset="lessons", definition=DEFINITION, owner=owner
            )
            return ScheduledReport.objects.create(
                custom_report=report, frequency="daily", time=time(7)
            )
