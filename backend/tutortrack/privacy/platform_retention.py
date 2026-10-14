"""Retention for records outside any one app's personal data (G6, FR-29-5).

* **Dispatched outbox events** (per organisation): a retention category like the others
  (``dispatched_events``, 90 days by default), run by the organisation's nightly
  ``RetentionPurgeWorkflow``. Events carry ids and small payloads, but they are a copy of
  what happened, so they don't outlive their use: only dispatched rows go; pending and
  dead-lettered events stay for operations to replay.
* **Login history and platform events**: ``LoginEvent`` rows are global (one login, many
  organisations) and platform events have no organisation, so a per-organisation setting
  can't own them. ``purge_platform_records`` (a short Celery beat task, batched) deletes
  sign-in attempts older than ``LOGIN_HISTORY_RETENTION_DAYS`` (400: a year plus a margin
  for the yearly security review) and organisation-less dispatched events older than
  ``OUTBOX_RETENTION_DAYS``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils.translation import gettext_lazy

from tutortrack.core.context import require_organisation_id
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now

from . import registry
from .registry import RetentionCategory

BATCH = 5000


def _purge_dispatched_events(cutoff: datetime, dry_run: bool, limit: int) -> int:
    qs = OutboxEvent.objects.filter(
        organisation_id=require_organisation_id(),
        dispatched_at__isnull=False,
        dispatched_at__lt=cutoff,
    )
    if dry_run:
        return qs.count()
    ids = list(qs.order_by("dispatched_at").values_list("pk", flat=True)[:limit])
    if ids:
        OutboxEvent.objects.filter(pk__in=ids).delete()
    return len(ids)


registry.register_retention(
    RetentionCategory(
        key="dispatched_events",
        label=gettext_lazy("Delivered internal events (the outbox)"),
        default_days=90,
        purge=_purge_dispatched_events,
        order=950,
    )
)


def _delete_in_batches(qs: object, limit: int = BATCH) -> int:
    total = 0
    while True:
        ids = list(qs.values_list("pk", flat=True)[:limit])  # type: ignore[attr-defined]
        if not ids:
            return total
        model = qs.model  # type: ignore[attr-defined]
        total += model.objects.filter(pk__in=ids).delete()[1].get(model._meta.label, 0)


def purge_platform_records() -> dict[str, int]:
    """Login history and organisation-less dispatched events past their periods."""
    from tutortrack.identity.models import LoginEvent

    login_cutoff = now() - timedelta(days=int(settings.LOGIN_HISTORY_RETENTION_DAYS))
    event_cutoff = now() - timedelta(days=int(settings.OUTBOX_RETENTION_DAYS))
    return {
        "login_events": _delete_in_batches(LoginEvent.objects.filter(created_at__lt=login_cutoff)),
        "platform_events": _delete_in_batches(
            OutboxEvent.objects.filter(
                organisation_id__isnull=True,
                dispatched_at__isnull=False,
                dispatched_at__lt=event_cutoff,
            )
        ),
    }
