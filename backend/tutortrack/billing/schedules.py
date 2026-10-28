"""Per-branch invoicing schedules (Temporal Schedules, E10-TW1), replaced by the **Invoicing
cycle** built-in workflow (E33 T04). ``retire_invoice_schedules`` deletes an organisation's
schedules when the built-in is installed."""

from __future__ import annotations

from tutortrack.core.context import require_organisation_id
from tutortrack.core.workflows.schedules import delete_schedule, schedule_id
from tutortrack.tenancy.models import Branch

from .processes import SCHEDULE_PROCESS


def retire_invoice_schedules() -> int:
    """Delete the organisation's per-branch invoicing schedules; returns how many."""
    org_id = require_organisation_id()
    return sum(
        delete_schedule(org_id, schedule_id(SCHEDULE_PROCESS, org_id, branch.pk))
        for branch in Branch.objects.all()
    )
