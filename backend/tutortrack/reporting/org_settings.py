"""Reporting settings (FR-26-1, FR-26-6)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "reporting.dashboard_preset",
    type="choice",
    default="auto",
    choices=(
        ("auto", _("Simple for sole traders, by role otherwise")),
        ("simple", _("Simple: revenue, outstanding, lessons and today's lessons")),
        ("role", _("By role")),
    ),
    label=_("Default dashboard"),
)
register(
    "reporting.currency",
    type="str",
    default="",
    max_length=3,
    label=_("Reporting currency (blank: show each currency separately)"),
)
