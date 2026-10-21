"""Activities defined by this app (autodiscovered by the worker)."""

from .check_processes import (
    check_settings,
    expire_check,
    initiate_check,
    poll_check,
    recheck_update_service,
)
from .processes import (
    application_reminder_days,
    check_onboarding,
    expire_record,
    expire_reference,
    reference_days,
    remind_expiry,
    remind_onboarding,
    remind_recruiters,
    remind_referee,
)
from .review_processes import (
    confirm_interview,
    interview_snapshot,
    probation_alert,
    probation_snapshot,
    provision_interview_meeting,
    remind_interview,
)

__all__ = [
    "application_reminder_days",
    "check_onboarding",
    "check_settings",
    "confirm_interview",
    "expire_check",
    "expire_record",
    "expire_reference",
    "initiate_check",
    "interview_snapshot",
    "poll_check",
    "probation_alert",
    "probation_snapshot",
    "provision_interview_meeting",
    "recheck_update_service",
    "reference_days",
    "remind_expiry",
    "remind_interview",
    "remind_onboarding",
    "remind_recruiters",
    "remind_referee",
]
