"""Matching reads (E19): scoped lists, the tutor's inbox and matching analytics (FR-19-6)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from statistics import median
from typing import Any

from django.db.models import Count, Q, QuerySet

from tutortrack.core.permissions import scope_queryset
from tutortrack.core.time import now
from tutortrack.jobs.models import Job, JobStatusHistory

from . import engine
from .models import CoverRequest, JobOffer, JobPosting, MatchQuery, OfferBatch


def visible_jobs(user: Any) -> QuerySet[Job]:
    return scope_queryset(user, Job.objects.all(), "jobs.job.view")


def batches(user: Any) -> QuerySet[OfferBatch]:
    return (
        OfferBatch.objects.filter(job__in=visible_jobs(user))
        .select_related("job")
        .prefetch_related("offers__tutor")
    )


def postings(user: Any) -> QuerySet[JobPosting]:
    return JobPosting.objects.filter(job__in=visible_jobs(user)).select_related("job")


# --- the tutor's inbox --------------------------------------------------------------------------


def my_offers(tutor: Any) -> QuerySet[JobOffer]:
    return (
        JobOffer.objects.filter(tutor=tutor)
        .exclude(status=JobOffer.Status.QUEUED)
        .select_related("batch")
        .order_by("-sent_at")
    )


def my_postings(tutor: Any) -> QuerySet[JobPosting]:
    today = now().date()
    return (
        JobPosting.objects.filter(status=JobPosting.Status.OPEN, eligible__contains=[str(tutor.pk)])
        .filter(Q(closes_on__isnull=True) | Q(closes_on__gte=today))
        .order_by("-published_at")
    )


def my_cover(tutor: Any) -> QuerySet[CoverRequest]:
    return (
        CoverRequest.objects.filter(
            Q(status=CoverRequest.Status.OPEN, notified__contains=[str(tutor.pk)])
            | Q(original_tutor=tutor)
            | Q(accepted_by=tutor)
        )
        .prefetch_related("lessons__lesson")
        .order_by("deadline")
    )


# --- analytics ----------------------------------------------------------------------------------


def _seeking_since(job: Job, until: Any) -> Any:
    entry = (
        JobStatusHistory.objects.filter(
            job=job, to_status=Job.Status.SEEKING_TUTOR, created_at__lte=until
        )
        .order_by("-created_at")
        .first()
    )
    return entry.created_at if entry else job.created_at


def analytics(*, days: int = 90) -> dict[str, Any]:
    """Time to match, offer answers per tutor and unmet demand (FR-19-6)."""
    since = now() - timedelta(days=days)
    filled: list[tuple[Job, Any]] = [
        (b.job, b.closed_at)
        for b in OfferBatch.objects.filter(
            status=OfferBatch.Status.FILLED, closed_at__gte=since
        ).select_related("job")
    ]
    filled += [
        (p.job, p.closed_at)
        for p in JobPosting.objects.filter(
            status=JobPosting.Status.FILLED, closed_at__gte=since
        ).select_related("job")
    ]
    hours = [
        max((closed - _seeking_since(job, closed)).total_seconds() / 3600, 0.0)
        for job, closed in filled
    ]
    S = JobOffer.Status
    tutors = (
        JobOffer.objects.filter(sent_at__gte=since)
        .values("tutor_id", "tutor__first_name", "tutor__last_name", "tutor__display_name")
        .annotate(
            sent=Count("id"),
            accepted=Count("id", filter=Q(status=S.ACCEPTED)),
            declined=Count("id", filter=Q(status=S.DECLINED)),
            expired=Count("id", filter=Q(status=S.EXPIRED)),
        )
        .order_by("-sent")
    )
    offer_rows = [
        {
            "tutor": str(r["tutor_id"]),
            "name": r["tutor__display_name"]
            or f"{r['tutor__first_name']} {r['tutor__last_name']}".strip(),
            "sent": r["sent"],
            "accepted": r["accepted"],
            "declined": r["declined"],
            "expired": r["expired"],
            "acceptance_rate": round(r["accepted"] / r["sent"], 3) if r["sent"] else 0.0,
        }
        for r in tutors[:50]
    ]
    demand: dict[tuple[str, str], dict[str, Any]] = {}
    current = now()
    for job in Job.objects.filter(status=Job.Status.SEEKING_TUTOR).select_related(
        "subject", "location__address"
    ):  # fmt: skip
        subject = job.subject.name if job.subject_id else ""
        area = "online" if job.online else engine.area_of(engine.job_place(job))
        row = demand.setdefault(
            (subject, area), {"subject": subject, "area": area, "jobs": 0, "oldest_days": 0}
        )
        row["jobs"] += 1
        waited = (current - _seeking_since(job, current)).days
        row["oldest_days"] = max(row["oldest_days"], waited)
    empty: dict[str, int] = defaultdict(int)
    for criteria in MatchQuery.objects.filter(created_at__gte=since, result_count=0).values_list(
        "criteria", flat=True
    ):  # fmt: skip
        empty[str((criteria or {}).get("subject") or "")] += 1
    return {
        "days": days,
        "time_to_match": {
            "jobs": len(hours),
            "average_hours": round(sum(hours) / len(hours), 1) if hours else None,
            "median_hours": round(median(hours), 1) if hours else None,
        },
        "offers": offer_rows,
        "unmatched": sorted(demand.values(), key=lambda r: (-r["jobs"], -r["oldest_days"])),
        "empty_searches": [
            {"subject": subject, "searches": count}
            for subject, count in sorted(empty.items(), key=lambda kv: -kv[1])
        ],
    }
