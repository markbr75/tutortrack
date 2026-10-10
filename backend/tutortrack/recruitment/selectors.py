"""Reads other apps use (E19 matching): compliance gaps, required checks and references."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from django.db.models import Avg, Q

from .models import ComplianceRecord, ReferenceRequest


def _valid_q(on: date) -> Q:
    return Q(status=ComplianceRecord.Status.VERIFIED) & (
        Q(expiry_date__isnull=True) | Q(expiry_date__gt=on)
    )


def lapsed_tutor_ids(tutor_ids: Iterable[object], on: date) -> set[str]:
    """Tutors holding a blocking check that has lapsed (expired, or past its expiry date
    before the nightly sweep has caught up)."""
    lapsed = ComplianceRecord.objects.filter(
        tutor_id__in=list(tutor_ids), requirement__blocking=True, requirement__mandatory=True
    ).filter(
        Q(status=ComplianceRecord.Status.EXPIRED)
        | Q(status=ComplianceRecord.Status.VERIFIED, expiry_date__lte=on)
    )
    return {str(t) for t in lapsed.values_list("tutor_id", flat=True)}


def tutors_with_valid(keys: Iterable[str], on: date) -> set[str] | None:
    """Tutors with a valid record for every requirement key (``None`` when no keys)."""
    keys = [k for k in keys if k]
    if not keys:
        return None
    result: set[str] | None = None
    for key in keys:
        holders = {
            str(t)
            for t in ComplianceRecord.objects.filter(
                _valid_q(on), requirement__key=key
            ).values_list("tutor_id", flat=True)
        }
        result = holders if result is None else result & holders
    return result or set()


def reference_ratings(tutor_ids: Iterable[object]) -> dict[str, float]:
    """Average referee rating (1-5) per tutor, from their approved application."""
    rows = (
        ReferenceRequest.objects.filter(
            application__tutor_id__in=list(tutor_ids), rating__isnull=False
        )
        .values("application__tutor_id")
        .annotate(avg=Avg("rating"))
    )
    return {str(r["application__tutor_id"]): float(r["avg"]) for r in rows}
