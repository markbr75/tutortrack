"""Portal configuration (FR-15-10)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

for key, default, label in (
    ("portal.enabled", True, _("Families can use the portal")),
    ("portal.allow_cancellations", True, _("Families can cancel lessons")),
    ("portal.allow_absence", True, _("Families can report absences")),
    ("portal.show_invoices", True, _("Show invoices and payments")),
    ("portal.show_reports", True, _("Show lesson reports")),
    ("portal.allow_profile_edits", True, _("Families can edit their details")),
    ("portal.show_tutor_contact", False, _("Show tutors' email and phone")),
    ("portal.show_prices", True, _("Show lesson prices")),
    ("portal.show_package_balances", True, _("Show package balances and sell packages")),
    ("portal.allow_messaging", True, _("Families can message you")),
    ("portal.allow_messaging_tutors", False, _("Families and tutors can message each other")),
    ("portal.allow_student_messaging", False, _("Students can send messages")),
):
    register(key, type="bool", default=default, label=label)
for key, label in (
    ("portal.welcome_text", _("Welcome message")),
    ("portal.help_url", _("Help page link")),
    ("portal.terms_url", _("Terms page link")),
):
    register(key, type="str", default="", max_length=1000, label=label)
