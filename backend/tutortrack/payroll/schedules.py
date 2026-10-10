"""Per-branch pay run schedules (Temporal Schedules, E12-TW1)."""

from __future__ import annotations

from tutortrack.core.context import require_organisation_id
from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
from tutortrack.tenancy.models import Branch
from tutortrack.tenancy.settings_service import get_setting

from .processes import SCHEDULE_PROCESS, ScheduledPayRunInput, ScheduledPayRunWorkflow


def cron_for(cadence: str, day: int) -> list[str]:
    """07:00 local on the cut-off. Weekly and fortnightly: ``day`` 1 = Monday ... 7 = Sunday
    (fortnightly skips odd ISO weeks in the workflow); semi-monthly: the 1st and 16th."""
    if cadence in ("weekly", "fortnightly"):
        return [f"0 7 * * {day % 7}"]
    if cadence == "semi_monthly":
        return ["0 7 1,16 * *"]
    return [f"0 7 {min(day, 28)} * *"]


def sync_pay_schedules() -> list[str]:
    org_id = require_organisation_id()
    out = []
    for branch in Branch.objects.all():
        cadence = str(get_setting("payroll.pay_period", branch=branch))
        sid = schedule_id(SCHEDULE_PROCESS, org_id, branch.pk)
        if cadence == "manual":
            delete_schedule(org_id, sid)
            continue
        day = int(get_setting("payroll.cut_off_day", branch=branch))
        out.append(
            ensure_schedule(
                process=SCHEDULE_PROCESS,
                workflow=ScheduledPayRunWorkflow,
                input=ScheduledPayRunInput(
                    organisation_id=str(org_id), branch_id=str(branch.pk), cadence=cadence
                ),
                cron=cron_for(cadence, day),
                timezone=str(branch.timezone),
                parts=(branch.pk,),
            )
        )
    return out
