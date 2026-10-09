"""Nightly: extend recurring lessons to the rolling horizon (FR-08-2)."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org


@shared_task(
    base=TenantTask, name="tutortrack.scheduling.tasks.extend_series_horizons", ignore_result=True
)
def extend_series_horizons(*, organisation_id: str) -> int:
    from . import services
    from .models import LessonSeries

    created = 0
    for series in LessonSeries.objects.filter(status=LessonSeries.Status.ACTIVE):
        created += len(services.extend_series(series).created)
    return created


@shared_task(name="tutortrack.scheduling.tasks.extend_all_series_horizons", ignore_result=True)
def extend_all_series_horizons() -> int:
    return fan_out_per_org(extend_series_horizons)
