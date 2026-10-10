"""Celery tasks (thin): the 30-day delivery log purge is housekeeping on Celery Beat,
fanned out per organisation."""

from __future__ import annotations

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org


@shared_task(
    base=TenantTask, name="tutortrack.developer.tasks.purge_webhook_deliveries", ignore_result=True
)
def purge_webhook_deliveries(*, organisation_id: str) -> int:
    from . import services

    return services.purge_deliveries()


@shared_task(name="tutortrack.developer.tasks.purge_all_webhook_deliveries", ignore_result=True)
def purge_all_webhook_deliveries() -> int:
    return fan_out_per_org(purge_webhook_deliveries)
