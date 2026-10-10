"""Conflict engine (FR-08-6).

Hard conflicts block unless the user may override (``scheduling.override_conflicts``):
the tutor is already teaching or busy (lesson, blocking event, time off, busy time in a
connected calendar, E22), or the job's hours cap would be exceeded. Everything else is a
warning.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _

from .models import AvailabilityException, CalendarEvent, Lesson

HARD = "hard"
SOFT = "soft"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Conflict:
    kind: str
    severity: str
    message: str
    lesson_id: str | None = None
    tutor_id: str | None = None
    student_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def check(
    *,
    start: datetime,
    end: datetime,
    tz: str,
    tutors: Iterable[Any] = (),
    students: Iterable[Any] = (),
    exclude_lesson_ids: Iterable[Any] = (),
    location: Any = None,
    online: bool = False,
    job: Any = None,
) -> list[Conflict]:
    from tutortrack.tenancy.settings_service import get_setting

    from . import availability, external

    tutors = list(tutors)
    outside = external.external_busy([t.pk for t in tutors], start, end)
    excluded = [str(i) for i in exclude_lesson_ids]
    found: list[Conflict] = []

    def add(kind: str, severity: str, message: str, **ids: Any) -> None:
        found.append(Conflict(kind, severity, message, **{k: str(v) for k, v in ids.items()}))

    overlapping = (
        Lesson.objects.filter(start__lt=end, end__gt=start)
        .exclude(status=Lesson.Status.CANCELLED)
        .exclude(pk__in=excluded)
    )
    buffer = timedelta(minutes=int(get_setting("scheduling.travel_buffer_minutes")))
    for tutor in tutors:
        name = {"tutor": tutor.full_name}
        clash = overlapping.filter(tutors__tutor=tutor).first()
        if clash:
            message = _("%(tutor)s already has %(lesson)s then.") % {**name, "lesson": clash.title}
            add("tutor_double_booked", HARD, message, lesson_id=clash.pk, tutor_id=tutor.pk)
        busy = CalendarEvent.objects.filter(
            start__lt=end, end__gt=start, participants__tutor=tutor
        ).first()
        if busy:
            message = _("%(tutor)s is busy: %(event)s.") % {**name, "event": busy.title}
            add("tutor_busy", HARD, message, tutor_id=tutor.pk)
        if any(
            b_start < end and b_end > start for b_start, b_end in outside.get(str(tutor.pk), [])
        ):
            message = _("%(tutor)s is busy in their own calendar then.") % name
            add("tutor_external_busy", HARD, message, tutor_id=tutor.pk)
        time_off = AvailabilityException.objects.filter(
            tutor=tutor, type="off", status="approved", start__lt=end, end__gt=start
        )
        if time_off.exists():
            add("tutor_time_off", HARD, _("%(tutor)s is on time off.") % name, tutor_id=tutor.pk)
        if availability.has_template(tutor.pk) and not availability.within_availability(
            tutor.pk, start, end, tz
        ):
            message = _("Outside %(tutor)s's availability.") % name
            add("outside_availability", SOFT, message, tutor_id=tutor.pk)
        if not online and buffer and _too_close(tutor, start, end, buffer, location, excluded):
            message = _("Less than %(minutes)s minutes between %(tutor)s's lessons.") % {
                **name,
                "minutes": int(buffer.total_seconds() // 60),
            }
            add("travel_buffer", SOFT, message, tutor_id=tutor.pk)
        if tutor.max_weekly_hours:
            hours = _weekly_hours(tutor, start, excluded) + _hours(start, end)
            if hours > tutor.max_weekly_hours:
                message = _("%(tutor)s would teach %(hours)s hours this week (limit %(max)s).") % {
                    **name,
                    "hours": round(hours, 1),
                    "max": tutor.max_weekly_hours,
                }
                add("max_weekly_hours", SOFT, message, tutor_id=tutor.pk)
    for student in students:
        clash = overlapping.filter(attendees__student=student).first()
        if clash:
            message = _("%(student)s already has %(lesson)s then.") % {
                "student": student.full_name,
                "lesson": clash.title,
            }
            add("student_double_booked", SOFT, message, lesson_id=clash.pk, student_id=student.pk)
    closure = CalendarEvent.objects.filter(
        org_wide=True, type=CalendarEvent.Type.HOLIDAY, start__lt=end, end__gt=start
    ).first()
    if closure:
        add("closure", SOFT, _("During a closure: %(event)s.") % {"event": closure.title})
    has_hours = location is not None and bool(location.opening_hours)
    if has_hours and not online and not _within_opening_hours(location, start, end, tz):
        message = _("Outside %(location)s's opening hours.") % {"location": location.name}
        add("outside_opening_hours", SOFT, message)
    if job is not None and job.hours_cap is not None:
        from tutortrack.jobs.services import check_hours

        result = check_hours(job, extra_hours=_hours(start, end), on=start.date())
        if result.level in {"warning", "blocked"}:
            message = _("%(used)s of %(cap)s capped hours on this job.") % {
                "used": round(result.used, 1),
                "cap": result.cap,
            }
            add("job_hours_cap", HARD if result.level == "blocked" else SOFT, message)
    return found


def _hours(start: datetime, end: datetime) -> Decimal:
    return Decimal((end - start).total_seconds()) / 3600


def _too_close(
    tutor: Any,
    start: datetime,
    end: datetime,
    buffer: timedelta,
    location: Any,
    excluded: list[str],
) -> bool:
    near = (
        Lesson.objects.filter(
            tutors__tutor=tutor, online=False, start__lt=end + buffer, end__gt=start - buffer
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .exclude(pk__in=excluded)
        .exclude(start__lt=end, end__gt=start)
    )
    if location is not None:
        near = near.exclude(location=location)
    return near.exists()


def _weekly_hours(tutor: Any, start: datetime, excluded: list[str]) -> Decimal:
    week_start = (start - timedelta(days=start.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    lessons = (
        Lesson.objects.filter(
            tutors__tutor=tutor, start__gte=week_start, start__lt=week_start + timedelta(days=7)
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .exclude(pk__in=excluded)
    )
    return sum((_hours(lesson.start, lesson.end) for lesson in lessons), Decimal(0))


def _within_opening_hours(location: Any, start: datetime, end: datetime, tz: str) -> bool:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(location.timezone or tz)
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    if local_start.date() != local_end.date():
        return False
    periods = location.opening_hours.get(DAYS[local_start.weekday()], [])
    begin, finish = local_start.strftime("%H:%M"), local_end.strftime("%H:%M")
    return any(p.get("start", "") <= begin and finish <= p.get("end", "") for p in periods)


def hard(conflicts: list[Conflict]) -> list[Conflict]:
    return [c for c in conflicts if c.severity == HARD]
