"""Lesson delivery reads (E09)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.permissions import scope_queryset
from tutortrack.core.time import now
from tutortrack.scheduling.models import Lesson, LessonAttendee
from tutortrack.tenancy.settings_service import get_setting

from .models import LessonFeedback, LessonReport, MakeupCredit

WRITTEN = (LessonReport.Status.SUBMITTED, LessonReport.Status.APPROVED)


def reports(user: Any, *, sla: str | None = None) -> QuerySet[LessonReport]:
    """Reports the user may see; ``sla`` = ``due | overdue | submitted | approved |
    shared | awaiting_approval``."""
    qs = scope_queryset(user, LessonReport.objects.all(), "delivery.report.view")
    moment = now()
    if sla == "due":
        qs = qs.exclude(status__in=WRITTEN).filter(due_at__gt=moment)
    elif sla == "overdue":
        qs = qs.exclude(status__in=WRITTEN).filter(due_at__lte=moment)
    elif sla == "submitted":
        qs = qs.filter(status=LessonReport.Status.SUBMITTED, shared_at__isnull=True)
    elif sla == "awaiting_approval":
        qs = qs.filter(status=LessonReport.Status.SUBMITTED)
    elif sla == "approved":
        qs = qs.filter(status=LessonReport.Status.APPROVED, shared_at__isnull=True)
    elif sla == "shared":
        qs = qs.filter(shared_at__isnull=False)
    return qs.select_related(
        "lesson", "lesson__service", "tutor", "template_version"
    ).prefetch_related("lesson__attendees__student")


def unconfirmed_lessons(user: Any) -> QuerySet[Lesson]:
    """FR-09-8: past lessons still planned beyond the unconfirmed threshold (or flagged)."""
    hours = int(get_setting("delivery.unconfirmed_after_hours"))
    cutoff = now() - timedelta(hours=hours)
    qs = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.view")
    return (
        qs.filter(status=Lesson.Status.PLANNED)
        .filter(Q(end__lte=cutoff) | Q(unconfirmed_at__isnull=False))
        .select_related("service")
        .prefetch_related("tutors__tutor", "attendees__student")
        .order_by("start")
    )


def lessons_with_open_reports(lesson_ids: list[Any]) -> set[str]:
    """Lessons whose report isn't submitted yet (E10 holds their invoices when the
    ``delivery.hold_invoice_without_report`` setting is on)."""
    return {
        str(i)
        for i in LessonReport.objects.filter(lesson_id__in=lesson_ids)
        .exclude(status__in=WRITTEN)
        .values_list("lesson_id", flat=True)
    }


def makeup_students(lesson: Lesson) -> set[str]:
    """Students attending ``lesson`` as a makeup (not charged, E10)."""
    return {
        str(s)
        for s in MakeupCredit.objects.filter(consumed_by_lesson=lesson).values_list(
            "student_id", flat=True
        )
    }


def makeup_credits(user: Any, *, student: Any = None, client: Any = None) -> QuerySet[MakeupCredit]:
    qs = scope_queryset(user, MakeupCredit.objects.all(), "delivery.makeup.view")
    if student:
        qs = qs.filter(student_id=student)
    if client:
        qs = qs.filter(client_id=client)
    return qs.select_related("student", "source_lesson")


@dataclass
class AttendanceStats:
    lessons: int
    attended: int
    rate_percent: str
    streak: int  # consecutive attended lessons, most recent first
    by_outcome: dict[str, int]


ATTENDED = {LessonAttendee.Outcome.PRESENT, LessonAttendee.Outcome.LATE}


def attendance_stats(student_id: Any) -> AttendanceStats:
    """FR-09-2: attendance over completed lessons (cancellations by us or the tutor don't
    count against the student)."""
    excluded = {LessonAttendee.Outcome.CANCELLED_TUTOR, LessonAttendee.Outcome.CANCELLED_ADMIN}
    outcomes = list(
        LessonAttendee.objects.filter(student_id=student_id)
        .exclude(outcome="")
        .exclude(outcome__in=excluded)
        .order_by("-lesson__start")
        .values_list("outcome", flat=True)
    )
    by_outcome: dict[str, int] = {}
    for outcome in outcomes:
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    attended = sum(1 for o in outcomes if o in ATTENDED)
    streak = 0
    for outcome in outcomes:
        if outcome not in ATTENDED:
            break
        streak += 1
    rate = f"{(attended * 100 / len(outcomes)):.1f}" if outcomes else "0.0"
    return AttendanceStats(len(outcomes), attended, rate, streak, by_outcome)


# --- client feedback (E09-T09) --------------------------------------------------------------


def feedback(
    user: Any,
    *,
    status: str = "",
    tutor: str = "",
    rating: str = "",
    since: Any = None,
) -> QuerySet[LessonFeedback]:
    """Feedback the user may see (tutors: about their own lessons). ``rating`` is a number
    of stars or ``low`` (at or below the alert threshold)."""
    qs = scope_queryset(user, LessonFeedback.objects.all(), "delivery.feedback.view")
    if status:
        qs = qs.filter(status=status)
    if tutor:
        qs = qs.filter(tutor_id=tutor)
    if rating == "low":
        qs = qs.filter(rating__lte=int(get_setting("delivery.feedback_alert_at_or_below")))
    elif rating.isdigit():
        qs = qs.filter(rating=int(rating))
    if since is not None:
        qs = qs.filter(lesson_date__gte=since)
    return qs.select_related("lesson", "student", "tutor", "contact")


def feedback_summary(qs: QuerySet[LessonFeedback]) -> dict[str, Any]:
    """Average stars, answer rate and star distribution, overall and per tutor."""
    from django.db.models import Avg, Count

    asked = qs.exclude(status=LessonFeedback.Status.SKIPPED)
    answered = asked.filter(status=LessonFeedback.Status.ANSWERED)
    overall = answered.aggregate(avg=Avg("rating"), n=Count("id"))
    stars = {str(i): 0 for i in range(1, 6)}
    for rating, n in (
        answered.order_by().values("rating").annotate(n=Count("id")).values_list("rating", "n")
    ):
        stars[str(rating)] = int(n)
    sent_by_tutor = dict(
        asked.order_by().values("tutor_id").annotate(n=Count("id")).values_list("tutor_id", "n")
    )
    tutors = []
    rows: Any = (
        answered.order_by()
        .values("tutor_id", "tutor__first_name", "tutor__last_name", "tutor__display_name")
        .annotate(avg=Avg("rating"), n=Count("id"))
        .order_by("-n")
    )
    for row in rows:
        name = row["tutor__display_name"] or (
            f"{row['tutor__first_name'] or ''} {row['tutor__last_name'] or ''}".strip()
        )
        tutors.append(
            {
                "tutor_id": str(row["tutor_id"]) if row["tutor_id"] else None,
                "tutor": name,
                "average": _one_place(row["avg"]),
                "answered": int(row["n"]),
                "asked": int(sent_by_tutor.get(row["tutor_id"], 0)),
            }
        )
    total = asked.count()
    return {
        "asked": total,
        "answered": int(overall["n"] or 0),
        "answer_rate": _one_place((overall["n"] or 0) * 100 / total) if total else "0.0",
        "average": _one_place(overall["avg"]) if overall["avg"] is not None else None,
        "stars": stars,
        "tutors": tutors,
    }


def _one_place(value: Any) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def tutor_feedback_ratings(tutor_ids: list[Any]) -> dict[str, tuple[float, int]]:
    """Average answered feedback and count per tutor (E19 matching blends it with E25
    reviews)."""
    from django.db.models import Avg, Count

    rows = (
        LessonFeedback.objects.filter(
            tutor_id__in=list(tutor_ids), status=LessonFeedback.Status.ANSWERED
        )
        .values("tutor_id")
        .annotate(avg=Avg("rating"), n=Count("id"))
    )
    return {str(r["tutor_id"]): (float(r["avg"]), int(r["n"])) for r in rows}
