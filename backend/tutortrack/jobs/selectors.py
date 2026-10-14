"""Job reads (E07): rate context for the engine, financial summary, attention list."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.catalogue import rates
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now

from . import lessons
from .models import Job, JobStudent, JobTutor


def rate_context(
    job: Job,
    *,
    duration_minutes: int | None = None,
    student_links: list[JobStudent] | None = None,
    tutor_links: list[JobTutor] | None = None,
) -> rates.RateContext:
    """The job's rates as an engine context (E08 adds lesson-level overrides on top)."""
    students = (
        student_links
        if student_links is not None
        else list(job.students.filter(active_to__isnull=True).select_related("student"))
    )
    tutors = (
        tutor_links
        if tutor_links is not None
        else list(job.tutors.filter(status=JobTutor.Status.ACTIVE))
    )
    return rates.RateContext(
        service=job.service,
        duration_minutes=duration_minutes or job.default_duration_minutes or 60,
        currency=job.currency,
        job_charge_rate=job.charge_rate,
        attendees=[
            rates.AttendeeInput(
                student_id=str(link.student_id),
                client_id=str(job.bill_to_id or job.client_id),
                job_rate_override=link.charge_rate_override,
            )
            for link in students
        ],
        tutors=[
            rates.TutorInput(tutor_id=str(link.tutor_id), job_rate_override=link.pay_rate_override)
            for link in tutors
        ],
    )


@dataclass
class Economics:
    charge: Money
    pay: Money
    margin: Money
    margin_percent: Decimal | None


def _economics(charge: Money, pay: Money) -> Economics:
    margin = charge - pay
    percent = (
        (margin.amount / charge.amount * 100).quantize(Decimal("0.1")) if charge.amount else None
    )
    return Economics(charge, pay, margin, percent)


@dataclass
class JobSummary:
    per_lesson: Economics | None  # expected, from the rate engine at the default duration
    trace: list[str] = field(default_factory=list)
    lessons_planned: int = 0
    lessons_completed: int = 0
    hours_delivered: Decimal = Decimal(0)
    delivered: Economics | None = None
    next_lesson_at: Any = None
    last_lesson_at: Any = None


def summary(job: Job) -> JobSummary:
    """Financial summary (FR-07-1 computed fields). Callers hide it from tutors and clients."""
    per_lesson = None
    trace: list[str] = []
    try:
        quote = rates.resolve_rates(rate_context(job))
        per_lesson = _economics(quote.total_charge, quote.total_pay)
        trace = [t for line in quote.charges for t in line.trace]
    except BusinessRuleViolation as exc:  # e.g. no students yet, or no price in the currency
        trace = [str(exc)]
    stats = lessons.provider().stats(job)
    delivered = (
        _economics(stats.revenue, stats.tutor_cost)
        if stats.revenue is not None and stats.tutor_cost is not None
        else None
    )
    return JobSummary(
        per_lesson=per_lesson,
        trace=trace,
        lessons_planned=stats.planned,
        lessons_completed=stats.completed,
        hours_delivered=stats.hours_delivered,
        delivered=delivered,
        next_lesson_at=stats.next_lesson_at,
        last_lesson_at=stats.last_lesson_at,
    )


ATTENTION_REASONS = (
    "seeking_tutor",
    "open_offer",
    "no_upcoming_lessons",
    "low_balance",
    "overdue_reports",
)


def _low_balance_job_ids(queryset: QuerySet[Job]) -> list[Any]:
    """Active prepaid jobs whose paying client's projected credit is under the top-up
    threshold, and active package jobs whose client has no package with more than the
    "low" number of units left (FR-07-6, gap G3). Read through billing's selectors."""
    from tutortrack.billing.selectors import low_balance_clients

    jobs = list(
        queryset.filter(
            status=Job.Status.ACTIVE, billing_method__in=["prepaid_credit", "package"]
        ).values("pk", "client_id", "bill_to_id", "billing_method", "currency")
    )
    if not jobs:
        return []
    wanted = {
        (str(j["bill_to_id"] or j["client_id"]), j["currency"], j["billing_method"]) for j in jobs
    }
    low = low_balance_clients(wanted)
    return [
        j["pk"]
        for j in jobs
        if (str(j["bill_to_id"] or j["client_id"]), j["currency"], j["billing_method"]) in low
    ]


def with_attention(queryset: QuerySet[Job], *, seeking_days: int = 7) -> QuerySet[Job]:
    """Annotate each job with the reasons it needs attention (``att_*`` booleans).

    * seeking a tutor for more than ``seeking_days``;
    * an open tutor offer;
    * active with no planned lessons from now on (E08);
    * low prepaid balance or package units (E10);
    * a lesson report overdue (E09).
    """
    from django.db.models import BooleanField, Case, Exists, OuterRef, Value, When

    from tutortrack.delivery.models import LessonReport
    from tutortrack.scheduling.models import Lesson

    if "att_seeking_tutor" in queryset.query.annotations:
        return queryset
    cutoff = now() - timedelta(days=seeking_days)
    upcoming = Lesson.objects.filter(
        job=OuterRef("pk"), status=Lesson.Status.PLANNED, start__gte=now()
    )
    overdue = LessonReport.objects.filter(
        lesson__job=OuterRef("pk"),
        status__in=[
            LessonReport.Status.PENDING,
            LessonReport.Status.DRAFT,
            LessonReport.Status.RETURNED,
        ],
        due_at__lte=now(),
    )
    offers = JobTutor.objects.filter(job=OuterRef("pk"), status=JobTutor.Status.OFFERED)
    low = _low_balance_job_ids(queryset)
    return queryset.annotate(
        att_seeking_tutor=Case(
            When(
                Q(status=Job.Status.SEEKING_TUTOR)
                & (
                    Q(status_changed_at__lt=cutoff)
                    | Q(status_changed_at__isnull=True, created_at__lt=cutoff)
                ),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
        att_open_offer=Case(
            When(
                Q(status__in=[Job.Status.SEEKING_TUTOR, Job.Status.ACTIVE]) & Exists(offers),
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
        att_no_upcoming_lessons=Case(
            When(Q(status=Job.Status.ACTIVE) & ~Exists(upcoming), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
        att_low_balance=Case(
            When(pk__in=low, then=Value(True)), default=Value(False), output_field=BooleanField()
        ),
        att_overdue_reports=Exists(overdue),
    )


def needing_attention(
    queryset: QuerySet[Job], *, seeking_days: int = 7, reason: str = ""
) -> QuerySet[Job]:
    """Jobs needing attention for any reason (or the one ``reason``), with ``att_*``
    annotations for the list to show why (FR-07-6)."""
    annotated = with_attention(queryset, seeking_days=seeking_days)
    reasons = [reason] if reason in ATTENTION_REASONS else list(ATTENTION_REASONS)
    q = Q()
    for name in reasons:
        q |= Q(**{f"att_{name}": True})
    return annotated.filter(q)


def attention_reasons(job: Job) -> list[str]:
    """The reasons a job (annotated by ``with_attention``) needs attention."""
    return [r for r in ATTENTION_REASONS if getattr(job, f"att_{r}", False)]


def last_assignment(tutor_ids: list[str]) -> dict[str, Any]:
    """When each tutor was last given a job (offered or assigned), for fair distribution."""
    from django.db.models import Max

    rows = (
        JobTutor.objects.filter(tutor_id__in=tutor_ids)
        .exclude(status=JobTutor.Status.DECLINED)
        .values("tutor_id")
        .annotate(last=Max("created_at"))
    )
    return {str(r["tutor_id"]): r["last"] for r in rows}
