"""Monthly affiliate statements as a per-organisation Temporal Schedule (E25-T05)."""

from __future__ import annotations

from tutortrack.core.context import require_organisation_id
from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.settings_service import get_setting

from .processes import STATEMENT_PROCESS, AffiliateStatementRunWorkflow, StatementRunInput

CRON = ["0 6 1 * *"]  # 06:00 on the 1st, organisation time


def sync_statement_schedule() -> str | None:
    org = Organisation.objects.get(pk=require_organisation_id())
    if get_setting("growth.statement_schedule") != "monthly":
        delete_schedule(org.pk, schedule_id(STATEMENT_PROCESS, org.pk))
        return None
    return ensure_schedule(
        process=STATEMENT_PROCESS,
        workflow=AffiliateStatementRunWorkflow,
        input=StatementRunInput(organisation_id=str(org.pk)),
        cron=CRON,
        timezone=str(org.timezone or "UTC"),
    )
