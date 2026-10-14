"""Payment settings (FR-11-1, FR-11-3, FR-11-4, FR-11-11)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

from .surcharges import ALL_METHODS, clean_methods, clean_percent

register(
    "payments.manual_methods",
    type="object",
    default=["bank_transfer", "cash", "cheque", "other"],
    label=_("Ways clients can pay you directly"),
)
register(
    "payments.allow_partial",
    type="bool",
    default=False,
    label=_("Clients can pay part of an invoice online"),
)
register(
    "payments.send_receipts",
    type="bool",
    default=True,
    label=_("Email a receipt for each payment"),
)
register(
    "payments.card_retry_days",
    type="object",
    default=[3, 5],
    label=_("Retry failed card payments after these many days"),
)
register(
    "payments.debit_retry_days",
    type="object",
    default=[3],
    label=_("Retry failed direct debits after these many days"),
)
register(
    "payments.pause_autopay_after_failure",
    type="bool",
    default=False,
    label=_("Turn off auto-pay when every retry has failed"),
)
register(
    "payments.bank_auto_match",
    type="bool",
    default=False,
    label=_("Confirm bank lines automatically when the invoice number and amount both match"),
)
# --- gap G3 -----------------------------------------------------------------------------------
register(
    "payments.enabled_methods",
    type="object",
    default=list(ALL_METHODS),
    scope="branch",
    label=_("Ways this branch takes payment"),
    help_text=_("The pay page offers only these; staff can record only these by hand."),
    schema={"type": "array", "items": {"type": "string", "enum": list(ALL_METHODS)}},
    validator=clean_methods,
)
register(
    "payments.card_surcharge_percent",
    type="str",
    default="0",
    max_length=8,
    scope="branch",
    label=_("Card surcharge (%) on online card payments"),
    help_text=_(
        "Shown and invoiced as a separate line. Not allowed for consumers in the UK and EEA; "
        "check your state or province rules elsewhere."
    ),
    validator=clean_percent,
)
register(
    "payments.autopay_timing",
    type="choice",
    default="on_issue",
    choices=(
        ("on_issue", _("When the invoice is issued")),
        ("before_due", _("A number of days before it is due")),
    ),
    label=_("When auto-pay collects"),
)
register(
    "payments.autopay_days_before_due",
    type="int",
    default=3,
    min_value=0,
    max_value=30,
    label=_("Days before the due date that auto-pay collects"),
)
register(
    "payments.card_expiry_notices",
    type="bool",
    default=True,
    label=_("Tell clients when a saved card is about to expire"),
)
register(
    "payments.autopay_consent_text",
    type="str",
    default=(
        "I authorise {organisation} to charge my saved payment method for invoices when "
        "they are issued, until I withdraw this permission."
    ),
    max_length=1000,
    label=_("Auto-pay consent wording"),
)
