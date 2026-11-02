"""Pathway settings (E34 FR-34-1)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "pathways.reminder_days",
    type="int",
    default=1,
    min_value=0,
    max_value=14,
    label=_("Days before a pathway step is due to remind whoever has to do it (0 = no reminder)"),
)
