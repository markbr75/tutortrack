"""E08-T01..T11: lessons, series, events, availability, conflicts, calendar, jobs, iCal."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tutortrack.catalogue.tests.factories import LocationFactory, ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.jobs import lessons as job_lessons
from tutortrack.jobs import services as jobs
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import availability, services
from tutortrack.scheduling.models import CalendarEvent, Lesson, LessonSeries

pytestmark = pytest.mark.django_db

LONDON = ZoneInfo("Europe/London")


def at(day: str, hhmm: str, tz=LONDON) -> datetime:
    """A local wall-clock time as an aware datetime."""
    return datetime.combine(date.fromisoformat(day), time.fromisoformat(hhmm), tzinfo=tz)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def api_as(org, role):
    membership = MembershipFactory(organisation=org, role=role)
    return client_for(org, membership.user), membership


@pytest.fixture
def admin_api(org):
    return api_as(org, "admin")[0]


@pytest.fixture
def people(org):
    """A family with one student, an active tutor and a £40/h service paying £25/h."""
    client = ClientFactory(organisation=org)
    student = StudentFactory(organisation=org, client=client, first_name="Arjun", last_name="Patel")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", last_name="Adeyemi"
    )
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {"client": client, "student": student, "tutor": tutor, "service": service}


def make_lesson(org, people, start, minutes=60, **kwargs):
    with tenant_context(org):
        return services.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=kwargs.pop("service", people["service"]),
            attendees=kwargs.pop("attendees", [{"student": people["student"]}]),
            tutors=kwargs.pop("tutors", [{"tutor": people["tutor"]}]),
            timezone="Europe/London",
            **kwargs,
        ).lesson


def events_of(org, kind):
    with tenant_context(org):
        return [
            e.payload["data"]
            for e in OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at")
        ]


# --- lessons and pricing (T01) ------------------------------------------------------------------


def test_create_lesson_snapshots_prices(org, admin_api, people):
    response = admin_api.post(
        "/api/v1/lessons",
        {
            "service": str(people["service"].pk),
            "start": iso(at("2026-11-02", "16:00")),
            "end": iso(at("2026-11-02", "17:30")),
            "attendees": [{"student": str(people["student"].pk)}],
            "tutors": [{"tutor": str(people["tutor"].pk)}],
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    lesson = response.json()["lesson"]
    assert lesson["title"] == "Maths 1:1 \N{EN DASH} Arjun Patel"
    assert lesson["duration_minutes"] == 90
    assert lesson["timezone"] == "Europe/London"
    [attendee] = lesson["attendees"]
    assert attendee["charge_amount"] == {"amount": "60.00", "currency": "GBP"}
    assert attendee["charge_snapshot"]["trace"] == ["service rate £40.00/h", "90 minutes"]
    assert lesson["tutors"][0]["pay_amount"] == {"amount": "37.50", "currency": "GBP"}
    assert events_of(org, "lesson.scheduled")[0]["student_ids"] == [str(people["student"].pk)]


def test_lesson_from_job_uses_job_rates_and_people(org, tenant, people):
    job = jobs.create_job(
        client=people["client"],
        service=people["service"],
        students=[{"student": people["student"]}],
        tutors=[{"tutor": people["tutor"], "pay_rate_override": Money("30", "GBP")}],
        status="active",
        charge_rate=Money("45", "GBP"),
    )
    start = at("2026-11-03", "16:00")
    lesson = services.create_lesson(job=job, start=start, end=start + timedelta(hours=1)).lesson
    attendee, tutor = lesson.attendees.get(), lesson.tutors.get()
    assert (attendee.charge_amount, tutor.pay_amount) == (
        Money("45.00", "GBP"),
        Money("30.00", "GBP"),
    )
    assert attendee.charge_snapshot["trace"][0] == "job rate £45.00/h"
    assert lesson.title == job.name


@pytest.mark.parametrize(
    ("start", "minutes", "field"),
    [("16:03", 60, "start"), ("16:00", 2, "end"), ("09:00", 13 * 60, "end")],
)
def test_duration_and_increment_rules(org, tenant, people, start, minutes, field):
    with pytest.raises(BusinessRuleViolation) as exc:
        make_lesson(org, people, at("2026-11-02", start), minutes=minutes)
    assert field in exc.value.extra["errors"]


def test_group_lesson_capacity(org, tenant, people):
    sibling = StudentFactory(organisation=org, client=people["client"])
    with pytest.raises(BusinessRuleViolation, match="at most 1"):
        make_lesson(
            org,
            people,
            at("2026-11-02", "16:00"),
            attendees=[{"student": people["student"]}, {"student": sibling}],
        )


# --- conflicts (T06) ----------------------------------------------------------------------------


def test_tutor_double_booking_blocks_unless_overridden(org, admin_api, people):
    make_lesson(org, people, at("2026-11-02", "16:00"))
    other = StudentFactory(organisation=org)
    body = {
        "service": str(people["service"].pk),
        "start": iso(at("2026-11-02", "16:30")),
        "end": iso(at("2026-11-02", "17:30")),
        "attendees": [{"student": str(other.pk)}],
        "tutors": [{"tutor": str(people["tutor"].pk)}],
    }
    blocked = admin_api.post("/api/v1/lessons", body, format="json")
    assert blocked.status_code == 422
    assert blocked.json()["conflicts"][0]["kind"] == "tutor_double_booked"
    overridden = admin_api.post(
        "/api/v1/lessons", {**body, "override_conflicts": True}, format="json"
    )
    assert overridden.status_code == 201, overridden.json()
    assert overridden.json()["warnings"][0]["severity"] == "hard"


def test_student_clash_is_a_warning(org, tenant, people):
    make_lesson(org, people, at("2026-11-02", "16:00"))
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    start = at("2026-11-02", "16:30")
    result = services.create_lesson(
        start=start,
        end=start + timedelta(hours=1),
        service=people["service"],
        attendees=[{"student": people["student"]}],
        tutors=[{"tutor": other_tutor}],
    )
    assert [c.kind for c in result.warnings] == ["student_double_booked"]


def test_conflict_dry_run_reports_soft_and_hard(org, admin_api, people):
    tutor = people["tutor"]
    with tenant_context(org):
        services.set_availability(
            tutor,
            windows=[{"weekday": 0, "start_time": time(9), "end_time": time(12)}],
            effective_from=date(2026, 10, 1),
            timezone="Europe/London",
        )
        services.add_exception(
            tutor, type="off", start=at("2026-11-02", "00:00"), end=at("2026-11-03", "00:00")
        )
    response = admin_api.post(
        "/api/v1/conflicts/check",
        {
            "start": iso(at("2026-11-02", "16:00")),
            "end": iso(at("2026-11-02", "17:00")),
            "timezone": "Europe/London",
            "tutors": [str(tutor.pk)],
        },
        format="json",
    )
    kinds = {(c["kind"], c["severity"]) for c in response.json()}
    assert kinds == {("tutor_time_off", "hard"), ("outside_availability", "soft")}


# --- series (T02, T03) --------------------------------------------------------------------------


def weekly(
    org, people, *, start="2026-10-19", count=None, until=None, rrule="FREQ=WEEKLY;BYDAY=MO", **kw
):
    with tenant_context(org):
        return services.create_series(
            service=people["service"],
            rrule=rrule,
            start_date=date.fromisoformat(start),
            start_time=time(16),
            duration_minutes=60,
            timezone="Europe/London",
            attendees=kw.pop("attendees", [{"student": people["student"]}]),
            tutors=[{"tutor": people["tutor"]}],
            count=count,
            until=until,
            **kw,
        )


def test_weekly_series_keeps_local_time_across_dst(org, people):
    """AC FR-08-2: 16:00 Europe/London stays 16:00 across the October clock change, and a
    New York viewer sees it shift."""
    result = weekly(org, people, count=3)
    starts = [lesson.start for lesson in sorted(result.created, key=lambda x: x.start)]
    assert [s.astimezone(LONDON).strftime("%Y-%m-%d %H:%M") for s in starts] == [
        "2026-10-19 16:00",
        "2026-10-26 16:00",
        "2026-11-02 16:00",
    ]
    assert [s.astimezone(UTC).hour for s in starts] == [15, 16, 16]
    new_york = [s.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") for s in starts]
    assert new_york == ["11:00", "12:00", "11:00"]  # US clocks change a week later
    with tenant_context(org):
        assert all(
            lesson.attendees.get().charge_amount == Money("40.00", "GBP")
            for lesson in result.created
        )


def test_series_skips_holidays_and_reports_clashes(org, people):
    with tenant_context(org):
        services.save_event(
            None,
            type="holiday",
            title="Half term",
            org_wide=True,
            timezone="Europe/London",
            start=at("2026-10-26", "00:00"),
            end=at("2026-10-31", "00:00"),
        )
    clash_student = StudentFactory(organisation=org)
    make_lesson(org, people, at("2026-11-02", "16:30"), attendees=[{"student": clash_student}])
    result = weekly(org, people, count=4)
    dates = sorted(lesson.occurrence_date for lesson in result.created)
    assert dates == [date(2026, 10, 19), date(2026, 11, 9)]
    assert [day for day, _found in result.skipped] == [date(2026, 11, 2)]


def test_until_and_rolling_horizon(org, people, monkeypatch):
    assert len(weekly(org, people, until=date(2026, 11, 9)).created) == 4
    from tutortrack.tenancy.settings_service import update_settings

    monkeypatch.setattr("tutortrack.scheduling.services.now", lambda: at("2026-10-01", "12:00"))
    with tenant_context(org):
        update_settings("scheduling", {"scheduling.series_horizon_months": 1})
    other = StudentFactory(organisation=org)
    result = weekly(org, people, rrule="FREQ=WEEKLY;BYDAY=TU", attendees=[{"student": other}])
    assert [lesson.occurrence_date for lesson in result.created] == [
        date(2026, 10, 20),
        date(2026, 10, 27),
    ]
    with tenant_context(org):
        extended = services.extend_series(result.series, until=date(2026, 11, 17))
    assert [lesson.occurrence_date for lesson in extended.created] == [
        date(2026, 11, 3),
        date(2026, 11, 10),
        date(2026, 11, 17),
    ]


def test_edit_all_future_preserves_completed_locked_and_exceptions(org, people, monkeypatch):
    """AC FR-08-2: moving all future lessons from 16:00 to 17:00."""
    result = weekly(org, people, start="2026-10-05", count=5)
    with tenant_context(org):
        lessons = sorted(result.series.lessons.all(), key=lambda x: x.start)
        # First is in the past and completed; second is invoiced; fourth was moved by hand.
        monkeypatch.setattr("tutortrack.scheduling.services.now", lambda: at("2026-10-14", "12:00"))
        services.complete_lesson(lessons[0])
        services.set_lock([lessons[1]], Lesson.Lock.INVOICED)
        services.update_lesson(
            lessons[3], start=at("2026-10-28", "15:00"), end=at("2026-10-28", "16:00")
        )
        services.edit_series(result.series, scope="all", start_time=time(17))
        after = {lesson.pk: lesson for lesson in Lesson.objects.filter(series__isnull=False)}
    local = {pk: lesson.start.astimezone(LONDON) for pk, lesson in after.items()}
    assert local[lessons[0].pk].hour == 16  # completed
    assert local[lessons[1].pk].hour == 16  # invoiced
    assert local[lessons[3].pk].strftime("%a %H:%M") == "Wed 15:00"  # exception kept
    moved = [
        lesson
        for lesson in after.values()
        if lesson.pk not in {lessons[0].pk, lessons[1].pk, lessons[3].pk}
    ]
    assert sorted(lesson.start.astimezone(LONDON).strftime("%m-%d %H:%M") for lesson in moved) == [
        "10-19 17:00",
        "11-02 17:00",
    ]


def test_edit_all_can_overwrite_exceptions(org, people, monkeypatch):
    monkeypatch.setattr("tutortrack.scheduling.services.now", lambda: at("2026-10-01", "12:00"))
    result = weekly(org, people, count=2)
    with tenant_context(org):
        first = min(result.created, key=lambda x: x.start)
        services.update_lesson(
            first, start=at("2026-10-20", "10:00"), end=at("2026-10-20", "11:00")
        )
        services.edit_series(
            result.series, scope="all", start_time=time(18), overwrite_exceptions=True
        )
        assert sorted(
            lesson.start.astimezone(LONDON).strftime("%m-%d %H:%M")
            for lesson in result.series.lessons.all()
        ) == ["10-19 18:00", "10-26 18:00"]


def test_this_and_following_splits_the_series(org, people, monkeypatch):
    monkeypatch.setattr("tutortrack.scheduling.services.now", lambda: at("2026-10-01", "12:00"))
    result = weekly(org, people, count=4)
    with tenant_context(org):
        third = sorted(result.created, key=lambda x: x.start)[2]
        services.edit_series(
            result.series, scope="following", from_lesson=third, duration_minutes=90
        )
        old = LessonSeries.objects.get(pk=result.series.pk)
        new = LessonSeries.objects.get(split_from=old)
        assert old.until == date(2026, 11, 1)
        assert (new.start_date, new.count, new.duration_minutes) == (date(2026, 11, 2), 2, 90)
        durations = {
            lesson.occurrence_date: (lesson.series_id, lesson.duration_minutes)
            for lesson in Lesson.objects.filter(series__in=[old, new])
        }
    assert durations[date(2026, 10, 19)] == (old.pk, 60)
    assert durations[date(2026, 11, 2)] == (new.pk, 90)
    assert durations[date(2026, 11, 9)] == (new.pk, 90)


def test_changing_the_rule_regenerates_future_lessons(org, people, monkeypatch):
    monkeypatch.setattr("tutortrack.scheduling.services.now", lambda: at("2026-10-01", "12:00"))
    result = weekly(org, people, until=date(2026, 11, 1))
    with tenant_context(org):
        services.edit_series(result.series, scope="all", rrule="FREQ=WEEKLY;BYDAY=TU,TH")
        days = sorted(
            lesson.start.astimezone(LONDON).strftime("%a %d")
            for lesson in result.series.lessons.all()
        )
    assert days == ["Thu 22", "Thu 29", "Tue 20", "Tue 27"]


def test_series_api_and_invalid_rules(org, admin_api, people):
    body = {
        "service": str(people["service"].pk),
        "rrule": "FREQ=WEEKLY;BYDAY=MO,WE",
        "start_date": "2026-11-02",
        "start_time": "16:00",
        "duration_minutes": 60,
        "count": 4,
        "attendees": [{"student": str(people["student"].pk)}],
        "tutors": [{"tutor": str(people["tutor"].pk)}],
    }
    response = admin_api.post("/api/v1/lesson-series", body, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["lessons_created"] == 4
    bad = admin_api.post("/api/v1/lesson-series", {**body, "rrule": "FREQ=HOURLY"}, format="json")
    assert bad.status_code == 422
    assert "rrule" in bad.json()["errors"]


# --- actions, locking (T09, T10) -----------------------------------------------------------------


def test_lesson_actions(org, admin_api, people):
    past = make_lesson(org, people, at("2026-10-05", "16:00"))
    future = make_lesson(org, people, at("2026-11-02", "16:00"))
    assert admin_api.post(f"/api/v1/lessons/{future.pk}/complete").status_code == 422
    assert admin_api.post(f"/api/v1/lessons/{past.pk}/complete").json()["status"] == "completed"
    cancelled = admin_api.post(
        f"/api/v1/lessons/{future.pk}/cancel", {"reason": "Ill", "chargeable": False}, format="json"
    ).json()
    assert (cancelled["status"], cancelled["attendees"][0]["chargeable"]) == ("cancelled", False)
    copy = admin_api.post(
        f"/api/v1/lessons/{past.pk}/duplicate",
        {"start": iso(at("2026-11-09", "16:00"))},
        format="json",
    )
    assert copy.status_code == 201, copy.json()
    copy_id = copy.json()["lesson"]["id"]
    moved = admin_api.post(
        f"/api/v1/lessons/{copy_id}/reschedule",
        {
            "start": iso(at("2026-11-10", "17:00")),
            "end": iso(at("2026-11-10", "18:00")),
            "reason": "Clash",
        },
        format="json",
    )
    assert moved.json()["lesson"]["rescheduled_from"] is not None
    assert events_of(org, "lesson.rescheduled")[0]["reason"] == "Clash"
    assert admin_api.delete(f"/api/v1/lessons/{copy_id}").status_code == 204
    assert admin_api.delete(f"/api/v1/lessons/{past.pk}").status_code == 422


def test_locked_lessons_need_permission_and_emit_adjustment(org, people):
    lesson = make_lesson(org, people, at("2026-11-02", "16:00"))
    with tenant_context(org):
        services.set_lock([lesson], Lesson.Lock.INVOICED)
        lesson.refresh_from_db()
        with pytest.raises(BusinessRuleViolation, match="invoiced"):
            services.update_lesson(lesson, end=at("2026-11-02", "17:30"))
        services.update_lesson(lesson, end=at("2026-11-02", "17:30"), can_edit_locked=True)
    [edited] = events_of(org, "lesson.locked_edited")
    assert (edited["before"]["charge"], edited["after"]["charge"]) == ("40.00", "60.00")
    coordinator, _m = api_as(org, "coordinator")
    response = coordinator.patch(
        f"/api/v1/lessons/{lesson.pk}", {"end": iso(at("2026-11-02", "18:00"))}, format="json"
    )
    assert response.status_code == 422  # coordinators can't edit locked lessons


def test_bulk_actions(org, admin_api, people):
    a = make_lesson(org, people, at("2026-11-02", "16:00"))
    b = make_lesson(org, people, at("2026-11-03", "16:00"))
    response = admin_api.post(
        "/api/v1/lessons/bulk",
        {"action": "cancel", "ids": [str(a.pk), str(b.pk)], "reason": "Closed"},
        format="json",
    )
    assert sorted(response.json()["succeeded"]) == sorted([str(a.pk), str(b.pk)])
    again = admin_api.post(
        "/api/v1/lessons/bulk", {"action": "cancel", "ids": [str(a.pk)]}, format="json"
    )
    assert list(again.json()["failed"]) == [str(a.pk)]


# --- events and closures (T04) ------------------------------------------------------------------


def test_closure_cancels_lessons_in_range(org, admin_api, people):
    lesson = make_lesson(org, people, at("2026-12-23", "10:00"))
    response = admin_api.post(
        "/api/v1/events",
        {
            "type": "holiday",
            "title": "Christmas closure",
            "org_wide": True,
            "cancel_lessons": True,
            "start": iso(at("2026-12-22", "00:00")),
            "end": iso(at("2027-01-02", "00:00")),
            "timezone": "Europe/London",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    with tenant_context(org):
        lesson.refresh_from_db()
    assert (lesson.status, lesson.status_reason) == ("cancelled", "Christmas closure")


def test_blocked_event_makes_tutor_busy(org, tenant, people):
    services.save_event(
        None,
        type="training",
        title="Safeguarding training",
        timezone="Europe/London",
        start=at("2026-11-02", "15:00"),
        end=at("2026-11-02", "18:00"),
        tutors=[people["tutor"]],
    )
    with pytest.raises(services.ConflictError, match="busy"):
        make_lesson(org, people, at("2026-11-02", "16:00"))


# --- availability and slots (T05) ---------------------------------------------------------------


def test_free_slots_respect_lessons_buffer_and_time_off(org, people, monkeypatch):
    monkeypatch.setattr("tutortrack.scheduling.availability.now", lambda: at("2026-10-01", "09:00"))
    tutor = people["tutor"]
    with tenant_context(org):
        services.set_availability(
            tutor,
            windows=[
                {"weekday": 0, "start_time": time(16), "end_time": time(19)},
                {"weekday": 1, "start_time": time(16), "end_time": time(18)},
            ],
            effective_from=date(2026, 10, 1),
            timezone="Europe/London",
        )
    make_lesson(org, people, at("2026-11-02", "17:00"))
    with tenant_context(org):
        services.add_exception(
            tutor, type="off", start=at("2026-11-03", "00:00"), end=at("2026-11-04", "00:00")
        )

        def slots(buffer):
            found = availability.free_slots(
                tutor.pk,
                start=date(2026, 11, 2),
                end=date(2026, 11, 3),
                duration_minutes=60,
                step_minutes=60,
                buffer_minutes=buffer,
                min_notice_hours=0,
            )
            return [s.start.astimezone(LONDON).strftime("%a %H:%M") for s in found]

        assert slots(0) == ["Mon 16:00", "Mon 18:00"]
        assert slots(15) == []


def test_availability_api_for_own_tutor(org, people):
    membership = MembershipFactory(organisation=org, role="tutor")
    with tenant_context(org):
        tutor = people["tutor"]
        tutor.membership = membership
        tutor.save()
    tutor_api = client_for(org, membership.user)
    url = f"/api/v1/availability/{tutor.pk}"
    response = tutor_api.put(
        url,
        {
            "effective_from": "2026-10-01",
            "timezone": "Europe/London",
            "windows": [
                {"weekday": 2, "start_time": "15:00", "end_time": "19:00", "mode": "online"}
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert tutor_api.get(url).json()["windows"][0]["mode"] == "online"
    other = TutorProfileFactory(organisation=org, status="active")
    assert tutor_api.get(f"/api/v1/availability/{other.pk}").status_code == 404


# --- calendar projection (T07) ------------------------------------------------------------------


def test_calendar_projection_and_tutor_scope(org, admin_api, people):
    mine = make_lesson(org, people, at("2026-11-02", "16:00"))
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    theirs = make_lesson(org, people, at("2026-11-03", "16:00"), tutors=[{"tutor": other_tutor}])
    params = {"start": iso(at("2026-11-02", "00:00")), "end": iso(at("2026-11-09", "00:00"))}
    items = admin_api.get("/api/v1/calendar", params).json()
    assert {i["id"] for i in items} == {str(mine.pk), str(theirs.pk)}
    filtered = admin_api.get("/api/v1/calendar", {**params, "tutor": str(other_tutor.pk)}).json()
    assert [i["id"] for i in filtered] == [str(theirs.pk)]
    assert filtered[0]["students"][0]["name"] == "Arjun Patel"
    membership = MembershipFactory(organisation=org, role="tutor")
    with tenant_context(org):
        people["tutor"].membership = membership
        people["tutor"].save()
    tutor_items = client_for(org, membership.user).get("/api/v1/calendar", params).json()
    assert [i["id"] for i in tutor_items] == [str(mine.pk)]
    lesson = client_for(org, membership.user).get(f"/api/v1/lessons/{mine.pk}").json()
    assert "charge_amount" not in lesson["attendees"][0]
    assert "pay_amount" not in lesson["tutors"][0]


# --- jobs integration (T10) ---------------------------------------------------------------------


def test_quick_setup_creates_weekly_series(org, people):
    with tenant_context(org):
        job = jobs.quick_setup(
            student=people["student"],
            service=people["service"],
            tutor=people["tutor"],
            schedule=[{"weekday": 1, "time": "16:30"}],
            start_date=date(2026, 11, 1),
        )
    dispatch_batch()
    with tenant_context(org):
        series = LessonSeries.objects.get(job=job)
        first = series.lessons.order_by("start").first()
    assert series.rrule == "FREQ=WEEKLY;BYDAY=TU"
    assert first.start.astimezone(LONDON).strftime("%Y-%m-%d %H:%M") == "2026-11-03 16:30"


def test_replacing_a_tutor_moves_future_lessons(org, people):
    with tenant_context(org):
        job = jobs.create_job(
            client=people["client"],
            service=people["service"],
            students=[{"student": people["student"]}],
            tutors=[{"tutor": people["tutor"]}],
            status="active",
        )
    past = make_lesson(org, people, at("2026-10-05", "16:00"), job=job)
    future = make_lesson(org, people, at("2026-11-09", "16:00"), job=job)
    new = TutorProfileFactory(organisation=org, status="active")
    with tenant_context(org):
        link = job.tutors.get()
        preview = jobs.replace_tutor(
            link, new_tutor=new, effective_date=date(2026, 11, 1), dry_run=True
        )
        assert [x.id for x in preview.preview.lessons] == [str(future.pk)]
        jobs.replace_tutor(link, new_tutor=new, effective_date=date(2026, 11, 1))
    dispatch_batch()
    with tenant_context(org):
        assert future.tutors.get().tutor_id == new.pk
        assert past.tutors.get().tutor_id == people["tutor"].pk


def test_job_stats_hours_and_cancel(org, people):
    with tenant_context(org):
        job = jobs.create_job(
            client=people["client"],
            service=people["service"],
            students=[{"student": people["student"]}],
            tutors=[{"tutor": people["tutor"]}],
            status="active",
            hours_cap=Decimal("2"),
            hours_cap_period="month",
        )
    done = make_lesson(org, people, at("2026-10-05", "16:00"), job=job)
    upcoming = make_lesson(org, people, at("2026-11-02", "16:00"), job=job)
    with tenant_context(org):
        services.complete_lesson(done)
        stats = job_lessons.provider().stats(job)
        assert (stats.planned, stats.completed, stats.revenue, stats.tutor_cost) == (
            2,
            1,
            Money("40.00", "GBP"),
            Money("25.00", "GBP"),
        )
        with pytest.raises(services.ConflictError, match="capped hours"):
            make_lesson(org, people, at("2026-11-03", "16:00"), minutes=90, job=job)
        jobs.change_status(job, "cancelled")
    dispatch_batch()
    with tenant_context(org):
        upcoming.refresh_from_db()
        done.refresh_from_db()
    assert (upcoming.status, done.status) == ("cancelled", "completed")


# --- iCal (T11) ---------------------------------------------------------------------------------


def test_ical_feed(org, people):
    membership = MembershipFactory(organisation=org, role="tutor")
    with tenant_context(org):
        people["tutor"].membership = membership
        people["tutor"].save()
    lesson = make_lesson(org, people, at("2026-11-02", "16:00"), notes_for_client="")
    api = client_for(org, membership.user)
    created = api.post(
        "/api/v1/ical-feeds",
        {"kind": "tutor", "subject_id": str(people["tutor"].pk)},
        format="json",
    )
    assert created.status_code == 201, created.json()
    path = "/ical/" + created.json()["url"].rsplit("/ical/", 1)[1]
    feed = api.get(path)
    assert feed.status_code == 200
    body = feed.content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert f"UID:{lesson.pk}@" in body
    assert "DTSTART:20261102T160000Z" in body
    other = TutorProfileFactory(organisation=org, status="active")
    forbidden = api.post(
        "/api/v1/ical-feeds", {"kind": "tutor", "subject_id": str(other.pk)}, format="json"
    )
    assert forbidden.status_code == 404
    api.post(f"/api/v1/ical-feeds/{created.json()['id']}/revoke")
    assert api.get(path).status_code == 404


# --- isolation ----------------------------------------------------------------------------------


class TestLessonIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/lessons"

    def make_object(self, organisation):
        client = ClientFactory(organisation=organisation)
        people = {
            "client": client,
            "student": StudentFactory(organisation=organisation, client=client),
            "tutor": TutorProfileFactory(organisation=organisation, status="active"),
            "service": ServiceFactory(organisation=organisation),
        }
        return make_lesson(organisation, people, at("2026-11-02", "16:00"))


class TestEventIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/events?start=2026-11-01T00:00:00Z&end=2026-11-30T00:00:00Z"

    def detail_url(self, obj):
        return f"/api/v1/events/{obj.pk}"

    def make_object(self, organisation):
        with tenant_context(organisation):
            event, _n = services.save_event(
                None,
                type="meeting",
                title="Team",
                timezone="Europe/London",
                start=at("2026-11-02", "09:00"),
                end=at("2026-11-02", "10:00"),
            )
            return event


def test_location_opening_hours_warning(org, tenant, people):
    centre = LocationFactory(
        organisation=org, opening_hours={"mon": [{"start": "09:00", "end": "17:00"}]}
    )
    result = services.create_lesson(
        start=at("2026-11-02", "16:30"),
        end=at("2026-11-02", "17:30"),
        service=people["service"],
        attendees=[{"student": people["student"]}],
        tutors=[{"tutor": people["tutor"]}],
        location=centre,
    )
    assert [c.kind for c in result.warnings] == ["outside_opening_hours"]
    assert CalendarEvent.objects.count() == 0


def test_a_year_of_weekly_lessons_is_one_batch(org, people, django_assert_max_num_queries):
    """NFR: series generation uses bulk inserts and prices once, not per occurrence."""
    import time as clock

    from tutortrack.tenancy.settings_service import update_settings

    with tenant_context(org):
        update_settings("scheduling", {"scheduling.series_horizon_months": 13})
    started = clock.perf_counter()
    with django_assert_max_num_queries(80):
        result = weekly(org, people, count=52)
    assert len(result.created) == 52
    assert clock.perf_counter() - started < 1.5
