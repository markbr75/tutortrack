"""Per-branch invoicing schedules (Temporal Schedules, E10-TW1)."""

from __future__ import annotations

from tutortrack.core.context import require_organisation_id
from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
from tutortrack.tenancy.models import Branch
from tutortrack.tenancy.settings_service import get_setting

from .processes import SCHEDULE_PROCESS, ScheduledInvoiceRunWorkflow, ScheduledRunInput


def cron_for(cadence: str, day: int) -> str:
    """06:00 local on the day (monthly: day of month; weekly: 1 = Monday ... 7 = Sunday)."""
    if cadence == "weekly":
        return f"0 6 * * {day % 7}"
    return f"0 6 {min(day, 28)} * *"


def sync_invoice_schedules() -> list[str]:
    org_id = require_organisation_id()
    cadence = str(get_setting("billing.invoice_schedule"))
    out = []
    for branch in Branch.objects.all():
        if cadence == "manual":
            delete_schedule(org_id, schedule_id(SCHEDULE_PROCESS, org_id, branch.pk))
            continue
        day = int(get_setting("billing.invoice_day", branch=branch))
        out.append(
            ensure_schedule(
                process=SCHEDULE_PROCESS,
                workflow=ScheduledInvoiceRunWorkflow,
                input=ScheduledRunInput(
                    organisation_id=str(org_id), branch_id=str(branch.pk), cadence=cadence
                ),
                cron=[cron_for(cadence, day)],
                timezone=str(branch.timezone),
                parts=(branch.pk,),
            )
        )
    return out
