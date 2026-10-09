"""Tutor availability and free slots (FR-08-5).

Weekly windows are wall-clock times in the template's timezone. Free slots subtract the
tutor's lessons (plus the travel buffer), blocking calendar events, time off and
organisation-wide closures, and respect the minimum notice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Q

from tutortrack.core.time import now

from .models import (
    AvailabilityException,
    AvailabilityTemplate,
    CalendarEvent,
    Lesson,
)
from .recurrence import to_utc

Interval = tuple[datetime, datetime]


def _merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _subtract(base: list[Interval], remove: list[Interval]) -> list[Interval]:
    result = []
    for start, end in base:
        pieces = [(start, end)]
        for r_start, r_end in remove:
            next_pieces = []
            for p_start, p_end in pieces:
                if r_end <= p_start or r_start >= p_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if r_start > p_start:
                    next_pieces.append((p_start, r_start))
                if r_end < p_end:
                    next_pieces.append((r_end, p_end))
            pieces = next_pieces
        result.extend(pieces)
    return result


def template_for(tutor_id: object, day: date) -> AvailabilityTemplate | None:
    return (
        AvailabilityTemplate.objects.filter(tutor_id=tutor_id, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day))
        .prefetch_related("windows")
        .order_by("-effective_from")
        .first()
    )


def available_intervals(tutor_id: object, start: date, end: date) -> list[Interval]:
    """Windows from the weekly template plus approved extra availability, in UTC."""
    intervals: list[Interval] = []
    day = start
    cache: dict[object, AvailabilityTemplate | None] = {}
    while day <= end:
        template = template_for(tutor_id, day)
        cache[day] = template
        if template is not None:
            for window in template.windows.all():
                if window.weekday == day.weekday():
                    intervals.append(
                        (
                            to_utc(day, window.start_time, template.timezone),
                            to_utc(day, window.end_time, template.timezone),
                        )
                    )
        day += timedelta(days=1)
    range_start = datetime.combine(start, datetime.min.time()).astimezone() - timedelta(days=1)
    range_end = datetime.combine(end, datetime.max.time()).astimezone() + timedelta(days=1)
    extras = AvailabilityException.objects.filter(
        tutor_id=tutor_id,
        type=AvailabilityException.Type.EXTRA,
        status=AvailabilityException.Status.APPROVED,
        start__lt=range_end,
        end__gt=range_start,
    )
    intervals.extend((e.start, e.end) for e in extras)
    return _merge(intervals)


def has_template(tutor_id: object) -> bool:
    return AvailabilityTemplate.objects.filter(tutor_id=tutor_id).exists()


def busy_intervals(
    tutor_id: object, start: datetime, end: datetime, *, buffer_minutes: int = 0,
    exclude_lesson_ids: Iterable[object] = (),
) -> list[Interval]:  # fmt: skip
    buffer = timedelta(minutes=buffer_minutes)
    busy: list[Interval] = []
    lessons = (
        Lesson.objects.filter(
            tutors__tutor_id=tutor_id, start__lt=end + buffer, end__gt=start - buffer
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .exclude(pk__in=list(exclude_lesson_ids))
    )
    busy.extend((lesson.start - buffer, lesson.end + buffer) for lesson in lessons)
    events = CalendarEvent.objects.filter(start__lt=end, end__gt=start).filter(
        Q(org_wide=True, type=CalendarEvent.Type.HOLIDAY) | Q(participants__tutor_id=tutor_id)
    )
    busy.extend((e.start, e.end) for e in events)
    off = AvailabilityException.objects.filter(
        tutor_id=tutor_id,
        type=AvailabilityException.Type.OFF,
        status=AvailabilityException.Status.APPROVED,
        start__lt=end,
        end__gt=start,
    )
    busy.extend((o.start, o.end) for o in off)
    return _merge(busy)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


def free_slots(
    tutor_id: object,
    *,
    start: date,
    end: date,
    duration_minutes: int,
    step_minutes: int = 15,
    buffer_minutes: int | None = None,
    min_notice_hours: int | None = None,
) -> list[Slot]:
    """Start times (every ``step_minutes``) where a lesson of ``duration_minutes`` fits."""
    from tutortrack.tenancy.settings_service import get_setting

    if buffer_minutes is None:
        buffer_minutes = int(get_setting("scheduling.travel_buffer_minutes"))
    if min_notice_hours is None:
        min_notice_hours = int(get_setting("scheduling.min_notice_hours"))
    free = available_intervals(tutor_id, start, end)
    if not free:
        return []
    busy = busy_intervals(tutor_id, free[0][0], free[-1][1], buffer_minutes=buffer_minutes)
    earliest = now() + timedelta(hours=min_notice_hours)
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    slots = []
    for f_start, f_end in _subtract(free, busy):
        cursor = max(f_start, earliest)
        # Align to the step within the window so slots land on :00/:15/...
        offset = (cursor - f_start) % step
        if offset:
            cursor += step - offset
        while cursor + duration <= f_end:
            slots.append(Slot(cursor, cursor + duration))
            cursor += step
    return slots


def within_availability(tutor_id: object, start: datetime, end: datetime, tz: str) -> bool:
    from .recurrence import local_date_of

    day = local_date_of(start, tz)
    intervals = available_intervals(tutor_id, day - timedelta(days=1), day + timedelta(days=1))
    return any(a <= start and end <= b for a, b in intervals)
