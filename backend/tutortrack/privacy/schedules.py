"""The nightly retention purge as a per-organisation Temporal Schedule (E29-TW1)."""

from __future__ import annotations

from tutortrack.core.context import require_organisation_id
from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.settings_service import get_setting

from .processes import RETENTION_PROCESS, RetentionInput, RetentionPurgeWorkflow

CRON = ["0 2 * * *"]  # 02:00 organisation time


def sync_retention_schedule() -> str | None:
    org = Organisation.objects.get(pk=require_organisation_id())
    if get_setting("privacy.retention_purge") == "off":
        delete_schedule(org.pk, schedule_id(RETENTION_PROCESS, org.pk))
        return None
    return ensure_schedule(
        process=RETENTION_PROCESS,
        workflow=RetentionPurgeWorkflow,
        input=RetentionInput(organisation_id=str(org.pk)),
        cron=CRON,
        timezone=str(org.timezone or "UTC"),
    )
