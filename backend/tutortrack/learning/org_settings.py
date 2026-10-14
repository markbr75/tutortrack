"""Learning tools settings (E21)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "learning.portal_enabled",
    type="bool",
    default=True,
    label=_("Show homework, resources and progress in the family portal"),
)
register(
    "learning.homework_reminder_hours",
    type="int",
    default=24,
    min_value=0,
    max_value=336,
    label=_("Remind students this many hours before homework is due (0: no reminder)"),
)
register(
    "learning.homework_from_reports",
    type="bool",
    default=True,
    label=_("Set homework written in a lesson report for the lesson's students"),
)
register(
    "learning.homework_report_due_days",
    type="int",
    default=7,
    min_value=1,
    max_value=60,
    label=_("Days students have for homework set from a lesson report"),
)
register(
    "learning.late_submissions",
    type="bool",
    default=True,
    label=_("Accept homework after it is due (marked late)"),
)
register(
    "learning.goals_auto_achieve",
    type="bool",
    default=True,
    label=_("Mark a goal achieved when all its milestones are done"),
)
register(
    "learning.progress_requires_approval",
    type="bool",
    default=True,
    label=_("Progress reports need approval before families see them"),
)
register(
    "learning.share_on_approval",
    type="bool",
    default=True,
    label=_("Share progress reports with families as soon as they are approved"),
)
register(
    "learning.loan_days",
    type="int",
    default=28,
    min_value=1,
    max_value=365,
    label=_("Default loan period in days"),
)
register(
    "learning.loan_reminder_days",
    type="int",
    default=2,
    min_value=0,
    max_value=30,
    label=_("Remind families this many days before a loan is due (0: no reminder)"),
)
register(
    "learning.loan_overdue_notice_days",
    type="int",
    default=7,
    min_value=1,
    max_value=60,
    label=_("Days between overdue notices for a loan"),
)
register(
    "learning.loan_overdue_notices",
    type="int",
    default=3,
    min_value=0,
    max_value=10,
    label=_("Overdue notices to send for a loan"),
)
