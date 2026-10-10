"""Organisation settings owned by identity: security and tutor access (FR-03-2/3/6)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "security.require_mfa_for_staff",
    type="bool",
    default=False,
    label=_("Require two-factor authentication for staff"),
    help_text=_("Staff without 2FA must set it up at their next sign-in."),
)
register(
    "security.staff_idle_timeout_hours",
    type="int",
    default=8,
    min_value=1,
    max_value=72,
    label=_("Sign staff out after (hours idle)"),
)
register(
    "security.portal_remember_days",
    type="int",
    default=30,
    min_value=1,
    max_value=90,
    label=_('Portal "remember me" (days)'),
)

# Tutor access toggles (FR-03-6). identity.tutor_access maps them to Tutor permissions.
register(
    "tutor_access.client_contact_details",
    type="choice",
    default="phone",
    choices=(("none", _("Hidden")), ("phone", _("Phone only")), ("full", _("Full details"))),
    label=_("Tutors can see client contact details"),
)
for key, label, default in (
    ("message_clients_directly", _("Tutors can message clients directly"), False),
    ("create_lessons", _("Tutors can create lessons"), False),
    ("reschedule_lessons", _("Tutors can reschedule lessons"), True),
    ("cancel_lessons", _("Tutors can cancel lessons"), False),
    ("edit_rates", _("Tutors can edit rates"), False),
    ("view_other_calendars", _("Tutors can see other tutors' calendars"), False),
    ("add_students", _("Tutors can add new students"), False),
):
    register(f"tutor_access.{key}", type="bool", default=default, label=label)
register(
    "security.support_access_requires_grant",
    type="bool",
    default=False,
    label=_("TutorTrack support needs a grant from you to view your account"),
    help_text=_("Off: support can view (read-only) when you raise a ticket. On: only while a "
                "grant you created is active."),
)  # fmt: skip
