"""Webhook processing, seat sync, revenue-share metering and automatic top-ups (E04)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from celery import shared_task
from django.core.cache import cache

from tutortrack.core.tasks import TenantTask, fan_out_per_org

SEAT_SYNC_DELAY_SECONDS = 300


@shared_task(
    base=TenantTask,
    name="tutortrack.subscriptions.tasks.process_billing_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=8,
)
def process_billing_event(*, organisation_id: str, event_id: str) -> None:
    from . import services
    from .models import BillingEvent

    row = BillingEvent.objects.filter(pk=event_id).first()
    if row is None:
        return
    try:
        services.process_event(row)
    except Exception as exc:
        BillingEvent.objects.filter(pk=row.pk).update(error=repr(exc)[:2000])
        raise


def schedule_seat_sync(organisation_id: Any) -> None:
    """Debounce: the first change in a window schedules one sync for the whole window."""
    if cache.add(f"seat-sync:{organisation_id}", 1, SEAT_SYNC_DELAY_SECONDS):
        sync_seats.apply_async(
            kwargs={"organisation_id": str(organisation_id)}, countdown=SEAT_SYNC_DELAY_SECONDS
        )


@shared_task(base=TenantTask, name="tutortrack.subscriptions.tasks.sync_seats")
def sync_seats(*, organisation_id: str) -> int | None:
    from . import services

    cache.delete(f"seat-sync:{organisation_id}")
    return services.sync_seats()


@shared_task(name="tutortrack.subscriptions.tasks.sync_all_seats")
def sync_all_seats() -> int:
    """Nightly: billable tutor and branch counts to Stripe (FR-04-4)."""
    return fan_out_per_org(sync_seats)


@shared_task(base=TenantTask, name="tutortrack.subscriptions.tasks.report_revenue")
def report_revenue(*, organisation_id: str, day: str | None = None) -> bool:
    from datetime import date

    from tutortrack.core.time import now

    from . import services

    when = date.fromisoformat(day) if day else (now() - timedelta(days=1)).date()
    return services.report_revenue(when) is not None


@shared_task(name="tutortrack.subscriptions.tasks.report_all_revenue")
def report_all_revenue() -> int:
    """Daily: yesterday's processed payments to the revenue-share meter."""
    return fan_out_per_org(report_revenue)


@shared_task(base=TenantTask, name="tutortrack.subscriptions.tasks.auto_top_up")
def auto_top_up(*, organisation_id: str, credit_type: str) -> bool:
    from . import credits

    return credits.auto_top_up(credit_type) is not None
