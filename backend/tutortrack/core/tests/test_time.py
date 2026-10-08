from datetime import UTC, date, datetime

import pytest

from tutortrack.core.time import (
    expand_rrule,
    is_valid_timezone,
    local_date_range_to_utc,
    localize,
    to_tz,
)


def test_weekly_series_keeps_wall_clock_time_across_uk_dst_change():
    # Thursdays 16:00 Europe/London across the end of BST (Sun 26 Oct 2025).
    occurrences = list(
        expand_rrule(
            "RRULE:FREQ=WEEKLY;COUNT=4",
            dtstart_local=datetime(2025, 10, 16, 16, 0),
            tz_name="Europe/London",
        )
    )
    local = [to_tz(o, "Europe/London") for o in occurrences]
    assert [d.strftime("%Y-%m-%d %H:%M") for d in local] == [
        "2025-10-16 16:00",
        "2025-10-23 16:00",
        "2025-10-30 16:00",
        "2025-11-06 16:00",
    ]
    # ...which means the UTC instant shifts by an hour after the change.
    assert [o.hour for o in occurrences] == [15, 15, 16, 16]


def test_viewer_in_new_york_sees_correct_local_time():
    london_lesson = localize(datetime(2025, 7, 3, 16, 0), "Europe/London")
    assert to_tz(london_lesson, "America/New_York").strftime("%H:%M") == "11:00"


def test_window_bounds_and_limit():
    occurrences = list(
        expand_rrule(
            "RRULE:FREQ=DAILY",
            dtstart_local=datetime(2025, 1, 1, 9, 0),
            tz_name="UTC",
            window_start=datetime(2025, 1, 5, tzinfo=UTC),
            window_end=datetime(2025, 1, 8, tzinfo=UTC),
        )
    )
    assert [o.day for o in occurrences] == [5, 6, 7]
    assert (
        len(
            list(
                expand_rrule(
                    "RRULE:FREQ=DAILY",
                    dtstart_local=datetime(2025, 1, 1),
                    tz_name="UTC",
                    limit=10,
                )
            )
        )
        == 10
    )


def test_nonexistent_local_time_moves_forward():
    # 01:30 doesn't exist in London on 30 Mar 2025 (clocks go 01:00 -> 02:00).
    result = localize(datetime(2025, 3, 30, 1, 30), "Europe/London")
    assert to_tz(result, "Europe/London").strftime("%H:%M") == "02:30"


def test_ambiguous_local_time_uses_first_occurrence():
    # 01:30 happens twice in London on 26 Oct 2025; the first is BST (00:30 UTC).
    result = localize(datetime(2025, 10, 26, 1, 30), "Europe/London")
    assert result == datetime(2025, 10, 26, 0, 30, tzinfo=UTC)


def test_local_date_range_to_utc():
    start, end = local_date_range_to_utc(date(2025, 7, 1), date(2025, 7, 31), "Europe/London")
    assert start == datetime(2025, 6, 30, 23, 0, tzinfo=UTC)
    assert end == datetime(2025, 7, 31, 23, 0, tzinfo=UTC)


def test_timezone_validation():
    assert is_valid_timezone("Australia/Sydney")
    assert not is_valid_timezone("Mars/Olympus_Mons")
    assert not is_valid_timezone("")
    with pytest.raises(ValueError, match="naive"):
        expand_rrule(
            "RRULE:FREQ=DAILY", dtstart_local=datetime(2025, 1, 1, tzinfo=UTC), tz_name="UTC"
        ).__next__()
