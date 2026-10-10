"""Activities defined by this app (autodiscovered by the worker)."""

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

__all__ = [
    "application_reminder_days",
    "check_onboarding",
    "expire_record",
    "expire_reference",
    "reference_days",
    "remind_expiry",
    "remind_onboarding",
    "remind_recruiters",
    "remind_referee",
]
