"""When a wait ends (E33 T01): relative to a date, at a time of day, on business days and
outside quiet hours, in the branch's time zone (properties across zones and DST)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.automations.timing import resume_at
from tutortrack.core.workflows.timers import BusinessCalendar

LONDON = BusinessCalendar(
    timezone="Europe/London", quiet_start="21:00", quiet_end="08:00", closed_weekdays=(6,)
)


def local(moment: datetime, tz: str = "Europe/London") -> datetime:
    return moment.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def test_days_before_a_due_date_at_a_time_across_the_clock_change():
    # Due Wednesday 28 Oct 2026 (GMT); 3 days before is Sunday 25 Oct, the day BST ends.
    step = {"until": "invoice.due_date", "offset_days": -3, "at": "09:00"}
    moment = resume_at(
        start=datetime(2026, 10, 1, tzinfo=UTC), step=step, calendar=LONDON,
        anchor=date(2026, 10, 28),
    )  # fmt: skip
    assert local(moment) == datetime(2026, 10, 25, 9, 0)
    assert moment == datetime(2026, 10, 25, 9, 0, tzinfo=UTC)  # GMT after 02:00 that day


def test_a_business_day_skips_closed_days_and_holidays_keeping_the_time():
    calendar = BusinessCalendar(timezone="Europe/London", closed_weekdays=(6,),
                                holidays=("2026-12-28",))  # fmt: skip
    step = {"until": "x", "offset_days": 0, "at": "10:00", "business_day": True}
    # Sunday 27 Dec is closed and Monday 28 Dec is a holiday: Tuesday 29 Dec at 10:00.
    moment = resume_at(start=datetime(2026, 12, 1, tzinfo=UTC), step=step, calendar=calendar,
                       anchor=date(2026, 12, 27))  # fmt: skip
    assert local(moment) == datetime(2026, 12, 29, 10, 0)


def test_quiet_hours_move_a_late_evening_wait_to_the_morning():
    step = {"hours": 3, "quiet_hours": True}
    start = datetime(2026, 11, 2, 19, 30, tzinfo=UTC)  # 19:30 London → 22:30 is quiet
    assert local(resume_at(start=start, step=step, calendar=LONDON)) == datetime(2026, 11, 3, 8, 0)


def test_tomorrow_at_a_time_and_a_missing_date():
    start = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
    tomorrow = resume_at(start=start, step={"days": 1, "at": "09:00"}, calendar=LONDON)
    assert local(tomorrow) == datetime(2026, 11, 3, 9, 0)
    # A record with no date: the wait ends at once.
    assert resume_at(start=start, step={"until": "lesson.start"}, calendar=LONDON) == start


def test_a_time_on_the_record_counts_hours_before_it():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    lesson = datetime(2026, 11, 5, 17, 0, tzinfo=UTC)
    step = {"until": "lesson.start", "offset_hours": -24}
    assert resume_at(start=start, step=step, calendar=LONDON, anchor=lesson) == lesson - timedelta(
        hours=24
    )


ZONES = ["Europe/London", "America/New_York", "Australia/Sydney", "Asia/Kolkata", "UTC"]


@settings(max_examples=150, deadline=None)
@given(
    zone=st.sampled_from(ZONES),
    start=st.datetimes(
        min_value=datetime(2024, 1, 1), max_value=datetime(2030, 12, 31), timezones=st.just(UTC)
    ),
    days=st.integers(min_value=0, max_value=60),
    hour=st.integers(min_value=0, max_value=23),
    minute=st.sampled_from([0, 15, 30, 45]),
    closed=st.sets(st.integers(min_value=0, max_value=6), max_size=5),
    business=st.booleans(),
    quiet=st.booleans(),
)
def test_resume_times_land_where_they_were_asked_to(
    zone, start, days, hour, minute, closed, business, quiet
):
    """Property: the result is an aware UTC moment; with "at", the local wall-clock time is
    that time (or an hour later when the clocks jump over it); a business-day wait never
    lands on a closed day; a quiet-hours wait never lands in quiet hours."""
    calendar = BusinessCalendar(
        timezone=zone, quiet_start="21:00", quiet_end="08:00", closed_weekdays=tuple(closed)
    )
    at = time(hour, minute)
    step = {"days": days, "at": at.strftime("%H:%M"), "business_day": business,
            "quiet_hours": quiet}  # fmt: skip
    moment = resume_at(start=start, step=step, calendar=calendar)
    assert moment.tzinfo is not None
    wall = local(moment, zone)
    if business:
        assert not calendar.is_closed(wall.date())
    if quiet:
        assert not calendar.is_quiet(wall)
    if not quiet or not calendar.is_quiet(datetime.combine(wall.date(), at)):
        gap = datetime.combine(wall.date(), wall.time()) - datetime.combine(wall.date(), at)
        assert gap in (timedelta(0), timedelta(hours=1))  # an hour on only when skipped over
    # Never before the day asked for (moving only goes forward).
    asked = (start.astimezone(ZoneInfo(zone)) + timedelta(days=days)).date()
    assert wall.date() >= asked


@settings(max_examples=100, deadline=None)
@given(
    zone=st.sampled_from(ZONES),
    due=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
    before=st.integers(min_value=-30, max_value=30),
)
def test_days_from_a_date_count_calendar_days_in_the_local_zone(zone, due, before):
    """Property: "N days before/after a date at 09:00" lands on that local date at 09:00
    whatever the clocks did in between (09:00 always exists)."""
    calendar = BusinessCalendar(timezone=zone)
    step = {"until": "invoice.due_date", "offset_days": before, "at": "09:00"}
    moment = resume_at(start=datetime(2024, 1, 1, tzinfo=UTC), step=step, calendar=calendar,
                       anchor=due)  # fmt: skip
    assert local(moment, zone) == datetime.combine(due + timedelta(days=before), time(9, 0))
