"""RRULE expansion in the lesson's local timezone (FR-08-2).

Occurrences are computed as *local* wall-clock times and then converted to UTC, so a
weekly 16:00 Europe/London lesson stays at 16:00 local across daylight-saving changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrule, rrulestr
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

ALLOWED_PARTS = {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYSETPOS", "WKST"}
ALLOWED_FREQ = {"DAILY", "WEEKLY", "MONTHLY"}


@dataclass(frozen=True)
class Occurrence:
    date: date  # local date the occurrence falls on
    start: datetime  # UTC
    end: datetime  # UTC


def clean_rrule(value: str) -> str:
    """Normalise and validate a rule: daily, weekly or monthly; no times, no UNTIL/COUNT
    (those are separate fields)."""
    text = value.strip().removeprefix("RRULE:").upper()
    parts: dict[str, str] = {}
    for chunk in filter(None, text.split(";")):
        key, _sep, val = chunk.partition("=")
        if key not in ALLOWED_PARTS or not val:
            raise BusinessRuleViolation(
                _("Unsupported repeat rule part: %(part)s") % {"part": key or chunk},
                extra={"errors": {"rrule": [_("Use daily, weekly or monthly repeats.")]}},
            )
        parts[key] = val
    if parts.get("FREQ") not in ALLOWED_FREQ:
        raise BusinessRuleViolation(
            _("Use daily, weekly or monthly repeats."),
            extra={"errors": {"rrule": [_("Use daily, weekly or monthly repeats.")]}},
        )
    interval = parts.get("INTERVAL", "1")
    if not interval.isdigit() or not 1 <= int(interval) <= 52:
        raise BusinessRuleViolation(
            _("The interval must be between 1 and 52."),
            extra={"errors": {"rrule": [_("The interval must be between 1 and 52.")]}},
        )
    normalised = ";".join(f"{k}={parts[k]}" for k in ["FREQ", *sorted(set(parts) - {"FREQ"})])
    try:
        rrulestr(normalised, dtstart=datetime(2026, 1, 5, 9, 0))  # noqa: DTZ001 (wall clock)
    except (ValueError, TypeError) as exc:
        raise BusinessRuleViolation(
            _("That repeat rule isn't valid."),
            extra={"errors": {"rrule": [_("That repeat rule isn't valid.")]}},
        ) from exc
    return normalised


def to_utc(local_date: date, local_time: time, tz: str) -> datetime:
    """A wall-clock time in ``tz`` as UTC. In a spring-forward gap the earlier offset is
    used (the lesson shows an hour later on the clock); ambiguous times take the first."""
    return datetime.combine(local_date, local_time, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def local_date_of(instant: datetime, tz: str) -> date:
    return instant.astimezone(ZoneInfo(tz)).date()


def expand(
    *,
    rule: str,
    start_date: date,
    start_time: time,
    tz: str,
    duration_minutes: int,
    window_start: date,
    window_end: date,
    until: date | None = None,
    count: int | None = None,
    skip_dates: set[date] | frozenset[date] = frozenset(),
) -> list[Occurrence]:
    """Occurrences whose local date is within ``[window_start, window_end]``."""
    dtstart = datetime.combine(start_date, start_time)
    recurrence: rrule = rrulestr(rule, dtstart=dtstart)  # type: ignore[assignment]
    if count:
        recurrence = recurrence.replace(count=count)
    elif until:
        recurrence = recurrence.replace(until=datetime.combine(until, time.max))
    last = min(window_end, until) if until else window_end
    if last < window_start:
        return []
    out = []
    for local in recurrence.between(
        datetime.combine(max(window_start, start_date), time.min),
        datetime.combine(last, time.max),
        inc=True,
    ):
        if local.date() in skip_dates:
            continue
        start = to_utc(local.date(), local.time(), tz)
        out.append(Occurrence(local.date(), start, start + timedelta(minutes=duration_minutes)))
    return out
