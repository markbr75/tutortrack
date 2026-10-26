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
    replaced_by="compliance_expiry",
)
register(
    "compliance.checks_auto_verify",
    type="bool",
    default=True,
    label=_("Verify a compliance record automatically when an online check comes back clear"),
)
register(
    "compliance.check_invite_days",
    type="int",
    default=30,
    min_value=3,
    max_value=90,
    label=_("Days a tutor has to complete an online background check"),
)
register(
    "compliance.dbs_update_recheck_days",
    type="int",
    default=90,
    min_value=0,
    max_value=365,
    label=_("Re-run DBS Update Service status checks every (days; 0 = never)"),
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
    "recruitment.probation_days",
    type="int",
    default=90,
    min_value=0,
    max_value=730,
    label=_("Probation review after activation (days; 0 = no automatic review)"),
)
register(
    "recruitment.probation_reminder_days",
    type="int",
    default=7,
    min_value=1,
    max_value=60,
    label=_("Remind staff before a probation review is due (days)"),
)
register(
    "recruitment.interview_hours",
    type="object",
    default={"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"},
    label=_(
        "Interview hours for interviewers without their own availability "
        "(weekdays 0 = Monday; local times)"
    ),
)
register(
    "recruitment.interview_video",
    type="bool",
    default=True,
    label=_("Create a video link automatically when an interview is booked"),
)
register(
    "recruitment.subject_test_retake_days",
    type="int",
    default=7,
    min_value=0,
    max_value=90,
    label=_("Days before a tutor can retake a failed subject test"),
)
register(
    "recruitment.auto_activate",
    type="bool",
    default=True,
    label=_("Activate tutors automatically when onboarding is complete"),
)
