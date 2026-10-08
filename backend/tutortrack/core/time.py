"""Time helpers. All storage is UTC; IANA timezones travel with orgs, users and lessons.

Recurrences are expanded in the *local* timezone of the series so lessons keep the same
wall-clock time across daylight-saving changes (docs/02-architecture.md §4).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from dateutil.rrule import rrulestr
from django.utils import timezone


def now() -> datetime:
    """Timezone-aware current time in UTC."""
    return timezone.now()


@cache
def _all_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_valid_timezone(name: str) -> bool:
    if not name or name not in _all_timezones():
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def get_zone(name: str) -> ZoneInfo:
    if not is_valid_timezone(name):
        raise ValueError(f"Unknown timezone: {name!r}")
    return ZoneInfo(name)


def to_tz(value: datetime, tz_name: str) -> datetime:
    """Convert an aware datetime to the given timezone."""
    if timezone.is_naive(value):
        raise ValueError("to_tz() requires an aware datetime")
    return value.astimezone(get_zone(tz_name))


def localize(naive: datetime, tz_name: str) -> datetime:
    """Attach ``tz_name`` to a naive wall-clock time and return it in UTC.

    * Ambiguous times (clocks go back) resolve to the first occurrence (fold=0).
    * Non-existent times (clocks go forward) resolve forward by the size of the gap,
      e.g. 01:30 on the UK spring-forward day becomes 02:30 BST.
    """
    if timezone.is_aware(naive):
        raise ValueError("localize() requires a naive datetime")
    return naive.replace(tzinfo=get_zone(tz_name), fold=0).astimezone(UTC)


def local_date_range_to_utc(start: date, end: date, tz_name: str) -> tuple[datetime, datetime]:
    """UTC bounds ``[start 00:00, end+1 00:00)`` for an inclusive local date range."""
    if end < start:
        raise ValueError("end must not be before start")
    return (
        localize(datetime.combine(start, time.min), tz_name),
        localize(datetime.combine(end + timedelta(days=1), time.min), tz_name),
    )


def expand_rrule(
    rule: str,
    *,
    dtstart_local: datetime,
    tz_name: str,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    limit: int = 1000,
) -> Iterator[datetime]:
    """Yield occurrences of an RFC 5545 RRULE as aware UTC datetimes.

    ``dtstart_local`` is the naive wall-clock start in ``tz_name``. Expansion happens on
    naive local times, then each occurrence is localised, so a weekly 16:00 lesson stays
    at 16:00 local on both sides of a DST change. ``window_start``/``window_end`` (aware)
    bound the output; ``limit`` guards against unbounded rules.
    """
    if timezone.is_aware(dtstart_local):
        raise ValueError("dtstart_local must be naive (wall-clock time in tz_name)")
    get_zone(tz_name)
    rule_set = rrulestr(rule, dtstart=dtstart_local, forceset=True)
    count = 0
    for occurrence in rule_set:
        occurrence_utc = localize(occurrence, tz_name)
        if window_end is not None and occurrence_utc >= window_end:
            return
        if window_start is not None and occurrence_utc < window_start:
            continue
        yield occurrence_utc
        count += 1
        if count >= limit:
            return
