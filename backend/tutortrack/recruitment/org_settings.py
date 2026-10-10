"""Recruitment and compliance settings (FR-18-5, FR-18-6)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "compliance.hold_pay",
    type="bool",
    default=True,
    label=_("Hold pay while a tutor is restricted for compliance"),
)
register(
    "compliance.reminder_days",
    type="object",
    default=[60, 30, 7],
    label=_("Remind before a check expires (days)"),
)
register(
    "recruitment.reference_days",
    type="int",
    default=14,
    min_value=3,
    max_value=60,
    label=_("Days a referee has to reply"),
)
register(
    "recruitment.auto_activate",
    type="bool",
    default=True,
    label=_("Activate tutors automatically when onboarding is complete"),
)
