"""When a wait step ends (E33 FR-33-1): "N days after", "N days before the due date at
09:00", "on the next business day", "outside quiet hours".

``resume_at`` is pure (tested with Hypothesis across time zones and DST). ``calendar_for``
reads the organisation's settings for it, in the record's branch, inside an activity.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tutortrack.core.workflows.timers import BusinessCalendar, to_utc

AT = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
UTC = ZoneInfo("UTC")


def _local(moment: datetime | date, zone: ZoneInfo) -> datetime:
    """Naive wall-clock time in ``zone``. A plain date means its local midnight."""
    if isinstance(moment, datetime):
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return aware.astimezone(zone).replace(tzinfo=None)
    return datetime.combine(moment, time.min)


def resume_at(
    *,
    start: datetime,
    step: dict[str, Any],
    calendar: BusinessCalendar,
    anchor: datetime | date | None = None,
) -> datetime:
    """The aware UTC moment a wait step ends.

    * ``until`` waits count from ``anchor`` (a date or time on the record) by
      ``offset_days`` and ``offset_hours`` (negative is before); without an anchor the wait
      ends at once (``start``).
    * Other waits count ``days`` and ``hours`` from ``start``.
    * ``at`` ("HH:MM") moves the moment to that time on its local day.
    * ``business_day`` moves it off closed weekdays and holidays (same time of day).
    * ``quiet_hours`` moves it out of quiet hours, to when they end.
    """
    zone = ZoneInfo(calendar.timezone)
    if step.get("until"):
        if anchor is None:
            return start
        local = _local(anchor, zone) + timedelta(
            days=float(step.get("offset_days") or 0), hours=float(step.get("offset_hours") or 0)
        )
    else:
        local = _local(start, zone) + timedelta(
            days=float(step.get("days") or 0), hours=float(step.get("hours") or 0)
        )
    if step.get("at"):
        local = datetime.combine(local.date(), time.fromisoformat(str(step["at"])))
    for _ in range(400):  # bounded: a year of closed days at most
        if step.get("business_day") and calendar.is_closed(local.date()):
            local = datetime.combine(local.date() + timedelta(days=1), local.time())
            continue
        if step.get("quiet_hours") and calendar.quiet_end and calendar.is_quiet(local):
            end = time.fromisoformat(calendar.quiet_end)
            day = local.date() if local.time() < end else local.date() + timedelta(days=1)
            local = datetime.combine(day, end)
            continue
        break
    return to_utc(local, calendar.timezone)


def calendar_for(obj: Any, around: date) -> BusinessCalendar:
    """The record's branch calendar: its time zone, quiet hours, the weekdays with no
    business hours, and holidays and closures for the next year."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.scheduling.services import holiday_dates
    from tutortrack.tenancy.models import Branch, Organisation
    from tutortrack.tenancy.settings_service import get_setting

    branch_id = getattr(obj, "branch_id", None)
    branch = Branch.objects.filter(pk=branch_id).first() if branch_id else None
    org = Organisation.objects.get(pk=require_organisation_id())
    tz = str(branch.timezone if branch else org.timezone)
    hours = get_setting("general.business_hours", branch=branch) or {}
    closed = tuple(i for i, day in enumerate(DAYS) if not hours.get(day))
    holidays = holiday_dates(branch_id, around, around + timedelta(days=366), tz)
    return BusinessCalendar(
        timezone=tz,
        quiet_start=str(get_setting("comms.quiet_hours_start") or "") or None,
        quiet_end=str(get_setting("comms.quiet_hours_end") or "") or None,
        closed_weekdays=closed,
        holidays=tuple(sorted(day.isoformat() for day in holidays)),
    )
