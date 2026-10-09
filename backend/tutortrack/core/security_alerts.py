"""Suspicious-activity detection (FR-29-2). Alerts are domain events (``security.alert``);
identity's handler emails the organisation's owners."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, ClassVar

from django.conf import settings
from django.core.cache import cache

from .events import DomainEvent, publish
from .models import AuditEntry
from .time import now


@dataclass(frozen=True, kw_only=True)
class SecurityAlert(DomainEvent):
    event_type: ClassVar[str] = "security.alert"
    subject_type: ClassVar[str] = "user"

    kind: str
    detail: str


def check_mass_export(user: Any, organisation_id: Any) -> bool:
    """Alert when one person exports a lot in a short time (call inside a transaction)."""
    window = timedelta(minutes=settings.MASS_EXPORT_WINDOW_MINUTES)
    recent = AuditEntry.objects.filter(
        organisation_id=organisation_id,
        actor_id=user.pk,
        action="export",
        created_at__gte=now() - window,
    ).count()
    if recent < settings.MASS_EXPORT_ALERT_THRESHOLD:
        return False
    # One alert per person per window.
    if not cache.add(
        f"alert:mass-export:{organisation_id}:{user.pk}", 1, int(window.total_seconds())
    ):
        return False
    publish(
        SecurityAlert(
            subject_id=user.pk,
            kind="mass_export",
            detail=f"{recent} exports in {settings.MASS_EXPORT_WINDOW_MINUTES} minutes",
        ),
        organisation_id=organisation_id,
    )
    return True
