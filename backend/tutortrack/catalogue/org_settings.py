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

# --- Phase 2 pricing (E06-T07..T09) ---------------------------------------------------------------
register(
    "pricing.tier_affects_charge",
    type="bool",
    default=False,
    label=_("Pay tiers also set the charge rate"),
    help_text=_("When a tier has a charge rate for a service, clients pay it for that tutor."),
)
register(
    "pricing.pay_percent_basis",
    type="choice",
    default="gross",
    choices=(
        ("gross", _("The charge before discounts")),
        ("net", _("The charge after discounts")),
    ),
    label=_("Percentage pay is worked out from"),
)
register(
    "pricing.discount_display",
    type="choice",
    default="netted",
    choices=(
        ("netted", _("Net them into the lesson price")),
        ("separate", _("Show them as separate negative lines")),
    ),
    label=_("Discounts on invoices"),
)
