"""Scheduling reads: the calendar range projection (FR-08-7, E08-T07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Prefetch, Q, QuerySet

from tutortrack.core.permissions import has_perm, scope_queryset

from .models import CalendarEvent, Lesson, LessonAttendee, LessonTutor


def lessons_in_range(
    user: Any, start: datetime, end: datetime, filters: dict[str, Any] | None = None
) -> QuerySet[Lesson]:
    """Lessons overlapping ``[start, end)`` that the user may see, with people prefetched."""
    filters = filters or {}
    qs = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.view").filter(
        start__lt=end, end__gt=start
    )
    if filters.get("tutor"):
        qs = qs.filter(tutors__tutor__in=filters["tutor"])
    if filters.get("student"):
        qs = qs.filter(attendees__student__in=filters["student"])
    if filters.get("client"):
        qs = qs.filter(attendees__client__in=filters["client"])
    for key in ("service", "job", "location", "branch"):
        if filters.get(key):
            qs = qs.filter(**{f"{key}__in": filters[key]})
    if filters.get("status"):
        qs = qs.filter(status__in=filters["status"])
    return (
        qs.distinct()
        .select_related("service", "location")
        .prefetch_related(
            Prefetch("tutors", queryset=LessonTutor.objects.select_related("tutor")),
            Prefetch("attendees", queryset=LessonAttendee.objects.select_related("student")),
        )
        .order_by("start")
    )


def events_in_range(
    user: Any, start: datetime, end: datetime, tutors: list[Any] | None = None
) -> QuerySet[CalendarEvent]:
    if not has_perm(user, "scheduling.event.view") and not has_perm(user, "scheduling.lesson.view"):
        return CalendarEvent.objects.none()
    qs = CalendarEvent.objects.filter(start__lt=end, end__gt=start)
    if not has_perm(user, "scheduling.event.view"):
        qs = qs.filter(CalendarEvent.own_scope_q(user))
    if tutors:
        qs = qs.filter(Q(org_wide=True) | Q(participants__tutor__in=tutors))
    return qs.distinct().prefetch_related("participants").order_by("start")


def project_lesson(lesson: Lesson) -> dict[str, Any]:
    """The lightweight calendar shape (``/calendar``)."""
    return {
        "kind": "lesson",
        "id": str(lesson.pk),
        "title": lesson.title,
        "start": lesson.start,
        "end": lesson.end,
        "timezone": lesson.timezone,
        "status": lesson.status,
        "colour": lesson.colour or lesson.service.colour,
        "service": str(lesson.service_id),
        "job": str(lesson.job_id) if lesson.job_id else None,
        "series": str(lesson.series_id) if lesson.series_id else None,
        "location": lesson.location.name if lesson.location else "",
        "online": lesson.online,
        "tutors": [{"id": str(t.tutor_id), "name": t.tutor.full_name} for t in lesson.tutors.all()],
        "students": [
            {"id": str(a.student_id), "name": a.student.full_name} for a in lesson.attendees.all()
        ],
        "locked": lesson.is_locked,
    }


def project_event(event: CalendarEvent) -> dict[str, Any]:
    return {
        "kind": "event",
        "id": str(event.pk),
        "title": event.title,
        "start": event.start,
        "end": event.end,
        "timezone": event.timezone,
        "status": event.type,
        "colour": "#64748b" if event.type != CalendarEvent.Type.HOLIDAY else "#b91c1c",
        "service": None,
        "job": None,
        "series": None,
        "location": "",
        "online": False,
        "tutors": [{"id": str(p.tutor_id), "name": ""} for p in event.participants.all()],
        "students": [],
        "locked": False,
        "org_wide": event.org_wide,
        "all_day": event.all_day,
    }


# --- matching inputs (E19) ----------------------------------------------------------------------


def scheduled_minutes(tutor_ids: list[str], start: datetime, end: datetime) -> dict[str, int]:
    """Minutes of planned or completed lessons per tutor between ``start`` and ``end``."""
    out: dict[str, int] = {}
    rows = (
        LessonTutor.objects.filter(
            tutor_id__in=tutor_ids, lesson__start__lt=end, lesson__end__gt=start
        )
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .values_list("tutor_id", "lesson__start", "lesson__end")
    )
    for tutor_id, s, e in rows:
        key = str(tutor_id)
        out[key] = out.get(key, 0) + int((e - s).total_seconds() // 60)
    return out


def completed_in_subject(tutor_ids: list[str], subject_id: object | None) -> dict[str, int]:
    """Completed lessons per tutor on jobs for ``subject_id`` (all subjects when ``None``)."""
    from django.db.models import Count

    qs = LessonTutor.objects.filter(tutor_id__in=tutor_ids, lesson__status=Lesson.Status.COMPLETED)
    if subject_id is not None:
        qs = qs.filter(lesson__job__subject_id=subject_id)
    return {str(r["tutor_id"]): r["n"] for r in qs.values("tutor_id").annotate(n=Count("id"))}
