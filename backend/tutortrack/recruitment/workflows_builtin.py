"""The compliance expiry built-in workflow (E33 T06): remind the tutor and compliance staff
60, 30 and 7 days before a check expires. It replaces ``ComplianceRecordWorkflow``'s
reminders; expiring the record (and restricting the tutor) at the expiry date stays in
code.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_noop as N_

from tutortrack.automations.builtin_workflows import builtin_workflow

DEFAULT_DAYS = [60, 30, 7]  # compliance.reminder_days' default
MAX_REMINDERS = 6  # automations.services.MAX_OFFSETS


def _compliance_expiry(days_before: list[int]) -> dict[str, Any]:
    before = sorted({int(d) for d in days_before}, reverse=True)
    trigger = {"subject": "compliance_record", "field": "expiry_date",
               "offset_days": [-d for d in before[:MAX_REMINDERS]], "time": "09:00"}  # fmt: skip
    return {
        "trigger_type": "date",
        "trigger_config": trigger,
        "conditions": {"predicate": "compliance_record.verified"},
        "steps": [{"type": "action", "action": "remind_compliance_expiry", "config": {}}],
    }


def compliance_from_settings() -> dict[str, Any]:
    """``compliance.reminder_days`` (none: switched off)."""
    from tutortrack.tenancy.settings_service import get_setting

    raw = get_setting("compliance.reminder_days") or []
    days = [d for d in raw if isinstance(d, int) and 0 < d <= 366]
    return _compliance_expiry(days or DEFAULT_DAYS) | {"enabled": bool(days)}


@builtin_workflow(
    "compliance_expiry", "expiry",
    name=N_("Compliance expiry reminders"),
    description=N_("Remind the tutor and compliance staff 60, 30 and 7 days before a "
                   "verified check expires. The check still expires, and restricts the "
                   "tutor, on its expiry date."),
    first_version=compliance_from_settings,
    off_means=N_("Nobody is reminded before checks expire: Compliance lists what is "
                 "expiring."),
)  # fmt: skip
def compliance_expiry() -> dict[str, Any]:
    return _compliance_expiry(DEFAULT_DAYS)
