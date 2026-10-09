"""Tax settings (FR-06-3). E10 adds the rest of the billing area."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "billing.prices_include_tax",
    type="bool",
    default=False,
    label=_("Prices include tax"),
    help_text=_("Whether the prices you enter already include VAT/GST/sales tax."),
)
register(
    "billing.tax_registered",
    type="bool",
    default=False,
    label=_("Registered for VAT/GST/sales tax"),
)
