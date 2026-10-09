"""Job settings (FR-07-4, FR-07-5)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "jobs.dormant_after_days",
    type="int",
    default=30,
    label=_("Flag jobs with no lessons for this many days"),
    min_value=7,
    max_value=365,
)
register(
    "jobs.block_at_hours_cap",
    type="bool",
    default=True,
    label=_("Block scheduling past a job's hours cap"),
    help_text=_("Otherwise only warn. A warning is always shown at 80%."),
)
