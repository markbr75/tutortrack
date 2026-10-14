"""Lessons in DSARs and erasure (E29 Part 2). Lessons stay (they underpin charges and pay);
their titles and notes lose the person's name, booking contact details are removed, and
calendar feed tokens are revoked."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.core.time import now
from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import (
    AvailabilityException,
    BookingHold,
    ICalFeedToken,
    Lesson,
    LessonAttendee,
    RescheduleRequest,
)

NOTE_FIELDS = (
    "title",
    "notes_internal",
    "notes_for_tutor",
    "notes_for_client",
    "reschedule_reason",
    "status_reason",
)


def lessons_of(person: Person) -> Any:
    students = person.of("people.student")
    tutors = person.of("people.tutor")
    return Lesson.objects.filter(
        Q(attendees__student_id__in=students) | Q(tutors__tutor_id__in=tutors)
    ).distinct()


def export(person: Person) -> list[Section]:
    attended = [
        {
            "id": str(a.pk),
            "lesson": a.lesson.title,
            "start": a.lesson.start,
            "end": a.lesson.end,
            "status": a.lesson.status,
            "attendance": a.outcome,
        }
        for a in LessonAttendee.objects.filter(student_id__in=person.of("people.student"))
        .select_related("lesson")
        .order_by("-lesson__start")[:2000]
    ]
    taught = [
        {
            "id": str(lesson.pk),
            "lesson": lesson.title,
            "start": lesson.start,
            "status": lesson.status,
        }
        for lesson in Lesson.objects.filter(
            tutors__tutor_id__in=person.of("people.tutor")
        ).order_by("-start")[:2000]
    ]
    bookings = [
        {"id": str(b.pk), "start": b.start, "status": b.status, "contact": b.contact}
        for b in BookingHold.objects.filter(
            Q(client_id__in=person.of("people.client"))
            | Q(student_id__in=person.of("people.student"))
        )
    ]
    time_off = [
        {"id": str(e.pk), "type": e.type, "start": e.start, "end": e.end, "reason": e.reason}
        for e in AvailabilityException.objects.filter(tutor_id__in=person.of("people.tutor"))
    ]
    return [
        Section("scheduling.attended", _("Lessons attended"), attended),
        Section("scheduling.taught", _("Lessons taught"), taught),
        Section("scheduling.bookings", _("Online bookings"), bookings),
        Section("scheduling.time_off", _("Time off"), time_off),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for row in lessons_of(person).values("pk", *NOTE_FIELDS):
        changes = {f: ctx.scrub(row[f]) for f in NOTE_FIELDS if ctx.scrub(row[f]) != row[f]}
        if changes:
            Lesson.objects.filter(pk=row["pk"]).update(**changes)
            out.anonymised += 1
    for row in RescheduleRequest.objects.filter(lesson__in=lessons_of(person)).values(
        "pk", "reason", "decision_note"
    ):
        RescheduleRequest.objects.filter(pk=row["pk"]).update(
            reason=ctx.scrub(row["reason"]), decision_note=ctx.scrub(row["decision_note"])
        )
    out.anonymised += (
        BookingHold.objects.filter(
            Q(client_id__in=person.of("people.client"))
            | Q(student_id__in=person.of("people.student"))
        )
        .exclude(contact={})
        .update(contact={})
    )
    out.anonymised += (
        AvailabilityException.objects.filter(tutor_id__in=person.of("people.tutor"))
        .exclude(reason="")
        .update(reason="")
    )
    return out


def revoke(person: Person) -> int:
    return ICalFeedToken.objects.filter(
        user_id__in=person.of("identity.user"), revoked_at__isnull=True
    ).update(revoked_at=now())


register(
    Provider(key="scheduling", label="Lessons", export=export, erase=erase, revoke=revoke, order=30)
)
