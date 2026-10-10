"""Reporting periods in the organisation's timezone (FR-26-1 period selector)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tutortrack.core.context import require_organisation_id
from tutortrack.core.time import local_date_range_to_utc, now

PRESETS = (
    "today",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "last_30_days",
    "last_90_days",
    "last_12_months",
    "custom",
)
COMPARISONS = ("previous_period", "previous_year", "none")


@dataclass(frozen=True)
class Period:
    start: date  # inclusive
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def utc_bounds(self, tz: str) -> tuple[datetime, datetime]:
        return local_date_range_to_utc(self.start, self.end, tz)

    def as_dict(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def org_timezone() -> str:
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.only("timezone").get(pk=require_organisation_id())
    return str(org.timezone or "UTC")


def org_today() -> date:
    return now().astimezone(ZoneInfo(org_timezone())).date()


def local_date(moment: datetime, tz: str) -> date:
    return moment.astimezone(ZoneInfo(tz)).date()


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _month_end(day: date) -> date:
    return _add_months(day, 1) - timedelta(days=1)


def resolve(
    preset: str = "this_month",
    *,
    start: date | None = None,
    end: date | None = None,
    today: date | None = None,
) -> Period:
    """The period for a preset (``custom`` uses ``start``/``end``)."""
    if preset == "custom" or (start and end and preset not in PRESETS):
        if start is None or end is None:
            raise ValueError("custom periods need from and to")
        if end < start:
            raise ValueError("to must not be before from")
        return Period(start, end)
    today = today or org_today()
    if preset == "today":
        return Period(today, today)
    if preset in ("this_week", "last_week"):
        monday = today - timedelta(days=today.weekday())
        if preset == "last_week":
            monday -= timedelta(days=7)
        return Period(monday, monday + timedelta(days=6))
    if preset in ("this_month", "last_month"):
        first = _month_start(today) if preset == "this_month" else _add_months(today, -1)
        return Period(first, _month_end(first))
    if preset in ("this_quarter", "last_quarter"):
        first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        if preset == "last_quarter":
            first = _add_months(first, -3)
        return Period(first, _add_months(first, 3) - timedelta(days=1))
    if preset in ("this_year", "last_year"):
        year = today.year if preset == "this_year" else today.year - 1
        return Period(date(year, 1, 1), date(year, 12, 31))
    if preset == "last_30_days":
        return Period(today - timedelta(days=29), today)
    if preset == "last_90_days":
        return Period(today - timedelta(days=89), today)
    if preset == "last_12_months":
        return Period(_add_months(today, -11), today)
    raise ValueError(f"unknown period {preset!r}")


def comparison(period: Period, kind: str = "previous_period") -> Period | None:
    """The period to compare with: the same length just before, or a year earlier."""
    if kind == "none":
        return None
    if kind == "previous_year":
        try:
            return Period(
                period.start.replace(year=period.start.year - 1),
                period.end.replace(year=period.end.year - 1),
            )
        except ValueError:  # 29 February
            return Period(period.start - timedelta(days=365), period.end - timedelta(days=365))
    # Whole calendar months compare with the same number of months before.
    if period.start.day == 1 and period.end == _month_end(period.end):
        months = (period.end.year - period.start.year) * 12 + period.end.month - period.start.month
        first = _add_months(period.start, -(months + 1))
        return Period(first, period.start - timedelta(days=1))
    return Period(period.start - timedelta(days=period.days), period.start - timedelta(days=1))
