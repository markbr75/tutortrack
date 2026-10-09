"""Scheduling settings (FR-08-1, FR-08-2, FR-08-5)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "scheduling.minute_increment",
    type="int",
    default=5,
    label=_("Lesson times snap to this many minutes"),
    min_value=1,
    max_value=60,
)
register(
    "scheduling.series_horizon_months",
    type="int",
    default=6,
    label=_("Create recurring lessons this many months ahead"),
    min_value=1,
    max_value=24,
)
register(
    "scheduling.travel_buffer_minutes",
    type="int",
    default=15,
    scope="branch",
    label=_("Gap between a tutor's in-person lessons"),
    help_text=_("Used for free slots and travel warnings."),
    min_value=0,
    max_value=240,
)
register(
    "scheduling.min_notice_hours",
    type="int",
    default=0,
    label=_("Minimum notice for new lessons (hours)"),
    help_text=_("Free slots start this long from now."),
    min_value=0,
    max_value=336,
)
