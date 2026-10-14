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
    for key in ("service", "job", "location", "branch", "room"):
        if filters.get(key):
            qs = qs.filter(**{f"{key}__in": filters[key]})
    if filters.get("status"):
        qs = qs.filter(status__in=filters["status"])
    return (
        qs.distinct()
        .select_related("service", "location", "room")
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
        "room": str(lesson.room_id) if lesson.room_id else None,
        "room_name": lesson.room.name if lesson.room_id and lesson.room else "",
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
        "room": None,
        "room_name": "",
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


def completed_lesson_count(*, client_id: object = None, tutor_id: object = None) -> int:
    """Completed lessons of a client, a tutor, or a client with a tutor (E25 review
    requests, referral and tutor-referral milestones)."""
    qs = Lesson.objects.filter(status=Lesson.Status.COMPLETED)
    if client_id is not None:
        qs = qs.filter(attendees__client_id=client_id)
    if tutor_id is not None:
        qs = qs.filter(tutors__tutor_id=tutor_id)
    return qs.distinct().count()


# --- Phase 2 reads (E06 promo codes, E08-T12..T15) ----------------------------------------------


def online_cancellation_deadline(lesson: Lesson) -> datetime | None:
    """The last moment a family may cancel a lesson they booked online themselves
    (``BookingSettings.cancellation_window_hours``, FR-08-9, gap G3). ``None``: no limit
    (lessons staff booked, or a window of 0 hours). Later than this they contact the
    organisation; staff can still cancel under the cancellation policy."""
    from datetime import timedelta

    from .models import BookingSettings

    if lesson.created_via != Lesson.CreatedVia.CLIENT_BOOKING:
        return None
    found = BookingSettings.objects.first()
    hours = found.cancellation_window_hours if found is not None else 24
    if not hours:
        return None
    return lesson.start - timedelta(hours=hours)


def client_has_lessons(client: Any) -> bool:
    """Whether the client already has (non-cancelled) lessons: promo codes for new
    clients only (E06-T09)."""
    return (
        LessonAttendee.objects.filter(client=client)
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .exists()
    )


def room_schedule(
    user: Any, start: datetime, end: datetime, location: Any = None
) -> list[dict[str, Any]]:
    """Rooms (optionally at one location) with the lessons booked in them: the calendar's
    room resource view (E08-T12)."""
    from tutortrack.catalogue.models import Room

    rooms = Room.objects.filter(active=True).select_related("location")
    if location is not None:
        rooms = rooms.filter(location=location)
    lessons = lessons_in_range(user, start, end).filter(room__in=rooms)
    by_room: dict[Any, list[dict[str, Any]]] = {}
    for lesson in lessons:
        by_room.setdefault(lesson.room_id, []).append(project_lesson(lesson))
    return [
        {
            "id": str(room.pk),
            "name": room.name,
            "location": str(room.location_id),
            "location_name": room.location.name,
            "capacity": room.capacity,
            "colour": room.colour,
            "lessons": by_room.get(room.pk, []),
        }
        for room in rooms.order_by("location__name", "name")
    ]


def pending_reschedule_requests(user: Any) -> QuerySet[Any]:
    from .models import RescheduleRequest

    visible = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.edit")
    return (
        RescheduleRequest.objects.filter(lesson__in=visible.values("pk"))
        .select_related("lesson")
        .order_by("deadline")
    )


# --- record timelines (E05 FR-05-10) ------------------------------------------------------------


def lesson_timeline(user: Any, target_type: str, target_id: str, limit: int) -> list[Any]:
    """Lessons of a client, contact (their family), student or tutor, for the record's
    activity timeline; only lessons the viewer may see."""
    from tutortrack.crm.selectors import TimelineItem
    from tutortrack.people.selectors import timeline_scope

    if not has_perm(user, "scheduling.lesson.view"):
        return []
    scope = timeline_scope(target_type, target_id)
    condition = Q()
    if scope["client"]:
        condition |= Q(attendees__client_id__in=scope["client"])
    if scope["student"]:
        condition |= Q(attendees__student_id__in=scope["student"])
    if scope["tutor"]:
        condition |= Q(tutors__tutor_id__in=scope["tutor"])
    if not condition:
        return []
    ids = Lesson.objects.filter(condition).values("pk")
    lessons = scope_queryset(user, Lesson.objects.filter(pk__in=ids), "scheduling.lesson.view")
    return [
        TimelineItem("lesson", str(lesson.pk), lesson.start, lesson.title, lesson.status, None)
        for lesson in lessons.order_by("-start")[:limit]
    ]
