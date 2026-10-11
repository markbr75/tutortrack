"""Accounting settings (E23). Served at ``/api/v1/settings/accounting``; connection-specific
options (mode, start date, bills, lock dates) live on the accounting connection."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

EXPORT_FORMATS = (
    ("generic", _("Generic GL journal (CSV)")),
    ("sage50", _("Sage 50 (CSV)")),
    ("myob", _("MYOB (CSV)")),
    ("iif", _("QuickBooks Desktop (IIF)")),
)

register(
    "accounting.error_digest",
    type="bool",
    default=True,
    label=_("Email finance a daily digest of accounting sync errors"),
)
register(
    "accounting.export_format",
    type="choice",
    default="generic",
    choices=EXPORT_FORMATS,
    label=_("Default general ledger export format"),
)
