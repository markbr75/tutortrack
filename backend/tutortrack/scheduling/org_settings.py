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

# --- Phase 2: time-off approval (T15) and reschedule requests (T13) -----------------------------
register(
    "scheduling.time_off_approval",
    type="bool",
    default=True,
    label=_("Tutors' time off needs approval"),
    help_text=_(
        "Time off a tutor asks for waits for an admin. Approved time off flags clashing "
        "lessons and looks for cover."
    ),
)
register(
    "scheduling.time_off_cover",
    type="bool",
    default=True,
    label=_("Look for cover when time off is approved"),
)
register(
    "scheduling.reschedule_requests",
    type="bool",
    default=True,
    label=_("Families and tutors can ask to move a lesson"),
)
register(
    "scheduling.reschedule_min_notice_hours",
    type="int",
    default=24,
    label=_("Reschedule requests close this many hours before the lesson"),
    min_value=0,
    max_value=336,
)
register(
    "scheduling.reschedule_max_per_month",
    type="int",
    default=2,
    label=_("Reschedule requests per student per month (0 = no limit)"),
    min_value=0,
    max_value=31,
)
register(
    "scheduling.reschedule_decision_hours",
    type="int",
    default=48,
    label=_("Unanswered reschedule requests are declined after (hours)"),
    min_value=1,
    max_value=336,
)
