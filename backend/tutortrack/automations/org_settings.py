"""Automation guardrails (FR-14-5)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "automations.enabled",
    type="bool",
    default=True,
    label=_("Run automations (switch off to stop them all at once)"),
)
register(
    "automations.max_runs_per_hour",
    type="int",
    default=500,
    min_value=1,
    max_value=10000,
    label=_("Most automation runs per hour for the organisation"),
)
