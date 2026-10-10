"""Tutor availability and free slots (FR-08-5).

Weekly windows are wall-clock times in the template's timezone. Free slots subtract the
tutor's lessons (plus the travel buffer), blocking calendar events, time off and
organisation-wide closures and busy time in connected calendars (E22, via
``scheduling.external``), and respect the minimum notice.
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
    from .external import external_busy

    busy.extend(external_busy([tutor_id], start, end).get(str(tutor_id), []))
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


def _templates_by_tutor(
    tutor_ids: list[str], start: date, end: date
) -> dict[str, list[AvailabilityTemplate]]:
    out: dict[str, list[AvailabilityTemplate]] = {t: [] for t in tutor_ids}
    templates = (
        AvailabilityTemplate.objects.filter(tutor_id__in=tutor_ids, effective_from__lte=end)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=start))
        .prefetch_related("windows")
        .order_by("-effective_from")
    )
    for template in templates:
        out[str(template.tutor_id)].append(template)
    return out


def interval_fit(
    tutor_ids: Iterable[object], groups: list[list[Interval]], *, buffer_minutes: int = 0
) -> dict[str, list[float]]:
    """For each tutor and each group of UTC intervals, the share of the intervals inside the
    tutor's availability that clash with nothing (lessons plus ``buffer_minutes``, blocking
    events, time off, closures). Batched for many tutors (E19-T02): a fixed number of queries
    whatever the number of tutors."""
    from .models import CalendarEventParticipant, LessonTutor

    ids = [str(t) for t in tutor_ids]
    flat = [i for group in groups for i in group]
    if not ids or not flat:
        return {t: [0.0 for _ in groups] for t in ids}
    lo = min(s for s, _e in flat)
    hi = max(e for _s, e in flat)
    buffer = timedelta(minutes=buffer_minutes)
    first_day = (lo - timedelta(days=1)).date()
    last_day = (hi + timedelta(days=1)).date()
    templates = _templates_by_tutor(ids, first_day, last_day)
    free: dict[str, list[Interval]] = {t: [] for t in ids}
    for tutor_id, tutor_templates in templates.items():
        day = first_day
        while day <= last_day:
            template = next(
                (
                    t for t in tutor_templates
                    if t.effective_from <= day and (t.effective_to is None or t.effective_to >= day)
                ),
                None,
            )  # fmt: skip
            if template is not None:
                for window in template.windows.all():
                    if window.weekday == day.weekday():
                        free[tutor_id].append(
                            (
                                to_utc(day, window.start_time, template.timezone),
                                to_utc(day, window.end_time, template.timezone),
                            )
                        )
            day += timedelta(days=1)
    busy: dict[str, list[Interval]] = {t: [] for t in ids}
    exceptions = AvailabilityException.objects.filter(
        tutor_id__in=ids,
        status=AvailabilityException.Status.APPROVED,
        start__lt=hi + buffer,
        end__gt=lo - buffer,
    )
    for exc in exceptions:
        target = free if exc.type == AvailabilityException.Type.EXTRA else busy
        target[str(exc.tutor_id)].append((exc.start, exc.end))
    lessons = (
        LessonTutor.objects.filter(
            tutor_id__in=ids, lesson__start__lt=hi + buffer, lesson__end__gt=lo - buffer
        )
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .values_list("tutor_id", "lesson__start", "lesson__end")
    )
    for tutor_id, start, end in lessons:
        busy[str(tutor_id)].append((start - buffer, end + buffer))
    for tutor_id, start, end in CalendarEventParticipant.objects.filter(
        tutor_id__in=ids, event__start__lt=hi, event__end__gt=lo
    ).values_list("tutor_id", "event__start", "event__end"):
        busy[str(tutor_id)].append((start, end))
    from .external import external_busy

    for tutor_id, intervals in external_busy(ids, lo, hi).items():
        busy.setdefault(tutor_id, []).extend(intervals)
    closures = [
        (e.start, e.end)
        for e in CalendarEvent.objects.filter(
            org_wide=True, type=CalendarEvent.Type.HOLIDAY, start__lt=hi, end__gt=lo
        )
    ]
    out: dict[str, list[float]] = {}
    for tutor_id in ids:
        available = _merge(free[tutor_id])
        blocked = _merge(busy[tutor_id] + closures)
        shares = []
        for group in groups:
            if not group:
                shares.append(0.0)
                continue
            fits = sum(
                1
                for s, e in group
                if any(a <= s and e <= b for a, b in available)
                and not any(bs < e and be > s for bs, be in blocked)
            )
            shares.append(round(fits / len(group), 4))
        out[tutor_id] = shares
    return out


def weekly_occurrences(
    slots: list[dict[str, object]], *, start: date, weeks: int, tz: str, default_minutes: int = 60
) -> list[list[Interval]]:
    """The next ``weeks`` occurrences of each weekly slot ``{weekday, time, duration_minutes}``
    (wall-clock in ``tz``) as UTC intervals, one list per slot."""
    from datetime import time as dtime

    groups = []
    for slot in slots:
        weekday = int(str(slot["weekday"]))
        hour, minute = (int(x) for x in str(slot["time"]).split(":"))
        minutes = int(str(slot.get("duration_minutes") or default_minutes))
        first = start + timedelta(days=(weekday - start.weekday()) % 7)
        group = []
        for week in range(weeks):
            begin = to_utc(first + timedelta(weeks=week), dtime(hour, minute), tz)
            group.append((begin, begin + timedelta(minutes=minutes)))
        groups.append(group)
    return groups
