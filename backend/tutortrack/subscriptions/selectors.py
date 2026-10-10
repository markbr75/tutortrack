"""Usage figures the subscription is priced and limited on (FR-04-1, FR-04-7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Sum

from tutortrack.core.time import now

COUNTED_TUTOR_STATUSES = ("onboarding", "active", "restricted")
ACTIVE_STUDENT_STATUSES = ("active", "trial")
BYTES_PER_GB = 1024**3


def tutor_count() -> int:
    """Tutors that count towards ``max_tutors`` (not applicants, inactive or archived)."""
    from tutortrack.people.models import TutorProfile

    return TutorProfile.objects.filter(status__in=COUNTED_TUTOR_STATUSES).count()


def active_student_count() -> int:
    from tutortrack.people.models import Student

    return Student.objects.filter(status__in=ACTIVE_STUDENT_STATUSES).count()


def branch_count() -> int:
    from tutortrack.tenancy.models import Branch

    return Branch.objects.filter(archived_at__isnull=True).count()


def storage_bytes() -> int:
    from tutortrack.core.models import StoredFile

    total = StoredFile.objects.exclude(status="rejected").aggregate(total=Sum("size_bytes"))
    return int(total["total"] or 0)


def delivering_tutor_count(since: datetime, until: datetime | None = None) -> int:
    """Tutors with at least one completed lesson in the period."""
    from tutortrack.scheduling.models import Lesson, LessonTutor

    return (
        LessonTutor.objects.filter(
            lesson__status=Lesson.Status.COMPLETED,
            lesson__start__gte=since,
            lesson__start__lt=until or now(),
        )
        .values("tutor_id")
        .distinct()
        .count()
    )


def billable_tutors(subscription: Any) -> int:
    """Seats for the ``active_tutor`` price, by the plan's seat mode."""
    from tutortrack.people.models import TutorProfile

    if subscription.plan.seat_mode == "active":
        return TutorProfile.objects.filter(status="active").count()
    since = subscription.current_period_start or subscription.trial_started_at
    return delivering_tutor_count(since) if since else 0


def usage_counts() -> dict[str, int]:
    return {
        "max_tutors": tutor_count(),
        "max_branches": branch_count(),
        "max_active_students": active_student_count(),
        "storage_gb": storage_bytes(),
    }
