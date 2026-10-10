"""Tutor portal reads (E16): the tutor's own day, students and earnings. Lesson actions
reuse the scheduling and delivery APIs, which already limit tutors to their own lessons."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile


def tutor_for(user: Any) -> TutorProfile | None:
    return TutorProfile.objects.filter(membership__user=user).first()


def _zone(tutor: TutorProfile) -> ZoneInfo:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)


def _join(lesson: Any) -> dict[str, Any]:
    """The tutor's (host) join link and when the join button opens (E22-T09)."""
    from tutortrack.scheduling.external import join_link

    link = join_link(lesson, "host")
    return {"join_url": link.url if link else "", "join_opens_at": link.opens_at if link else None}


def lesson_pay(link: Any) -> Money | None:
    if link.pay_amount is None or not link.payable:
        return None
    return (link.pay_amount * link.pay_percent / Decimal(100)).round_to_minor()


def today(tutor: TutorProfile, user: Any) -> dict[str, Any]:
    from tutortrack.comms.models import InAppNotification
    from tutortrack.delivery.models import LessonReport
    from tutortrack.jobs.models import JobTutor
    from tutortrack.matching.models import JobOffer
    from tutortrack.scheduling.models import Lesson

    zone = _zone(tutor)
    local = now().astimezone(zone)
    start = datetime.combine(local.date(), time.min, tzinfo=zone)
    lessons = (
        Lesson.objects.filter(
            tutors__tutor=tutor, start__gte=start, start__lt=start + timedelta(days=1)
        )
        .exclude(status=Lesson.Status.CANCELLED)
        .select_related("location")
        .prefetch_related("attendees__student")
        .order_by("start")
    )
    written = (LessonReport.Status.SUBMITTED, LessonReport.Status.APPROVED)
    month_start = local.date().replace(day=1)
    return {
        "date": local.date(),
        "lessons": [
            {
                "id": str(lesson.pk),
                "title": lesson.title,
                "start": lesson.start,
                "end": lesson.end,
                "status": lesson.status,
                "online": lesson.online,
                "meeting_url": lesson.meeting_url,
                **_join(lesson),
                "location": lesson.location.name if lesson.location else "",
                "students": [a.student.full_name for a in lesson.attendees.all()],
            }
            for lesson in lessons
        ],
        "reports_due": LessonReport.objects.filter(tutor=tutor).exclude(status__in=written).count(),
        "offers": JobTutor.objects.filter(tutor=tutor, status=JobTutor.Status.OFFERED).count()
        + JobOffer.objects.filter(tutor=tutor, status=JobOffer.Status.SENT).count(),
        "unread": InAppNotification.objects.filter(user=user, read_at__isnull=True).count(),
        "earnings_this_month": earnings(tutor, month_start, local.date())["total"],
    }


def earnings(tutor: TutorProfile, start: date, end: date) -> dict[str, Any]:
    """Pay for delivered lessons (and chargeable cancellations) in ``[start, end]``.
    Provisional until payroll (E12) turns them into pay items."""
    from tutortrack.scheduling.models import Lesson, LessonTutor

    zone = _zone(tutor)
    links = (
        LessonTutor.objects.filter(
            tutor=tutor,
            lesson__status__in=[Lesson.Status.COMPLETED, Lesson.Status.CANCELLED],
            lesson__start__gte=datetime.combine(start, time.min, tzinfo=zone),
            lesson__start__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
        )
        .select_related("lesson")
        .order_by("lesson__start")
    )
    rows = []
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for link in links:
        pay = lesson_pay(link)
        if pay is None or pay.is_zero():
            continue
        totals[pay.currency] += pay.amount
        rows.append(
            {
                "lesson": str(link.lesson_id),
                "title": link.lesson.title,
                "start": link.lesson.start,
                "status": link.lesson.status,
                "pay": pay.to_dict(),
            }
        )
    currency = tutor_currency(links) or "GBP"
    total = Money(totals.get(currency, Decimal(0)), currency).round_to_minor()
    return {"start": start, "end": end, "lessons": rows, "total": total.to_dict()}


def tutor_currency(links: Any) -> str | None:
    first = links.first()
    return first.currency if first else None


def students(tutor: TutorProfile) -> list[dict[str, Any]]:
    from tutortrack.jobs.models import JobTutor
    from tutortrack.scheduling.models import Lesson

    seen: dict[str, dict[str, Any]] = {}
    for link in (
        JobTutor.objects.filter(tutor=tutor, status=JobTutor.Status.ACTIVE)
        .select_related("job")
        .prefetch_related("job__students__student")
    ):
        for js in link.job.students.all():
            student = js.student
            seen.setdefault(
                str(student.pk),
                {
                    "id": str(student.pk),
                    "name": student.full_name,
                    "year_group": student.year_group,
                    "jobs": [],
                    "next_lesson": None,
                },
            )["jobs"].append(link.job.name)
    for row in seen.values():
        upcoming = (
            Lesson.objects.filter(
                tutors__tutor=tutor,
                attendees__student_id=row["id"],
                status=Lesson.Status.PLANNED,
                start__gte=now(),
            )
            .order_by("start")
            .first()
        )
        row["next_lesson"] = upcoming.start if upcoming else None
    return sorted(seen.values(), key=lambda r: r["name"])
