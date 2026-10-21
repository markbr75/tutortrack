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
    "accounting.package_deferred_revenue",
    type="bool",
    default=False,
    label=_("Treat package sales as deferred revenue until lessons use them"),
    help_text=_(
        "Package sales post to the deferred revenue account; a daily journal moves the "
        "revenue to sales as units are used or expire."
    ),
)
register(
    "accounting.export_format",
    type="choice",
    default="generic",
    choices=EXPORT_FORMATS,
    label=_("Default general ledger export format"),
)
register(
    "accounting.bad_debt_vat_relief",
    type="bool",
    default=False,
    label=_("Reclaim the VAT on written-off invoices (bad debt relief)"),
    help_text=_(
        "Write-offs post the VAT in the amount written off back to the VAT account at the "
        "invoice's rates, instead of the whole amount to bad debts. Check that your tax "
        "authority's conditions for bad debt relief are met."
    ),
)
