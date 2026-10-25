"""Lesson delivery settings (FR-09-1, FR-09-5..8)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "delivery.completion_opens",
    type="choice",
    default="start",
    choices=(("start", _("When the lesson starts")), ("near_end", _("Shortly before it ends"))),
    label=_("Lessons can be marked complete"),
)
register(
    "delivery.early_completion_minutes",
    type="int",
    default=10,
    label=_("How long before the end a lesson can be completed (minutes)"),
    min_value=0,
    max_value=240,
)
register(
    "delivery.bill_actual_duration",
    type="bool",
    default=False,
    label=_("Re-price lessons from their actual duration"),
)
register(
    "delivery.unconfirmed_after_hours",
    type="int",
    default=24,
    label=_("Lessons not marked after this many hours are unconfirmed"),
    min_value=1,
    max_value=720,
    replaced_by="unconfirmed_lessons",
)
register(
    "delivery.unconfirmed_action",
    type="choice",
    default="flag",
    choices=(
        ("flag", _("Flag them for staff")),
        ("auto_complete", _("Complete them as attended")),
    ),
    label=_("What happens to unconfirmed lessons"),
)
register(
    "delivery.report_required",
    type="bool",
    default=True,
    label=_("Tutors write a report after each lesson"),
)
register(
    "delivery.report_due_hours",
    type="int",
    default=24,
    label=_("Reports are due this many hours after the lesson ends"),
    min_value=1,
    max_value=720,
)
register(
    "delivery.report_reminder_hours",
    type="int",
    default=4,
    label=_("Remind tutors this many hours before a report is due"),
    min_value=0,
    max_value=168,
    replaced_by="report_chasing",
)
register(
    "delivery.report_escalate_hours",
    type="int",
    default=24,
    label=_("Tell staff when a report is this many hours overdue"),
    min_value=1,
    max_value=720,
    replaced_by="report_chasing",
)
register(
    "delivery.report_edit_window_hours",
    type="int",
    default=48,
    label=_("Tutors can edit a submitted report for this many hours"),
    min_value=0,
    max_value=720,
)
register(
    "delivery.report_approval_required",
    type="bool",
    default=False,
    label=_("Staff approve reports before clients see them"),
)
register(
    "delivery.report_auto_share",
    type="bool",
    default=True,
    label=_("Share reports with clients automatically"),
)
register(
    "delivery.report_submit_completes",
    type="bool",
    default=True,
    label=_("Submitting a report completes the lesson"),
)
register(
    "delivery.hold_pay_overdue_reports",
    type="bool",
    default=False,
    label=_("Hold tutor pay for lessons with overdue reports"),
)
register(
    "delivery.hold_invoice_without_report",
    type="bool",
    default=False,
    label=_("Don't invoice lessons until their report is submitted"),
)

# --- client feedback micro-surveys (FR-09-9, E09-T09) ---------------------------------------
register(
    "delivery.feedback_enabled",
    type="bool",
    default=False,
    label=_("Ask families for quick feedback after lessons"),
    replaced_by="lesson_feedback",
)
register(
    "delivery.feedback_delay_hours",
    type="int",
    default=2,
    label=_("Send the feedback request this many hours after the lesson"),
    min_value=0,
    max_value=72,
    replaced_by="lesson_feedback",
)
register(
    "delivery.feedback_every_n_lessons",
    type="int",
    default=4,
    label=_("Ask after every this many lessons with the same tutor"),
    min_value=1,
    max_value=52,
)
register(
    "delivery.feedback_expiry_days",
    type="int",
    default=7,
    label=_("Feedback links stop working after this many days"),
    min_value=1,
    max_value=60,
    replaced_by="lesson_feedback",
)
register(
    "delivery.feedback_alert_at_or_below",
    type="int",
    default=2,
    label=_("Alert staff when a lesson is rated this many stars or fewer"),
    min_value=1,
    max_value=5,
)
register(
    "delivery.feedback_invites_review",
    type="bool",
    default=False,
    label=_("Invite families who give 5 stars to write a public review"),
)
