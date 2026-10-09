"""Payment settings (FR-11-1, FR-11-3, FR-11-4, FR-11-11)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

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
    "payments.autopay_consent_text",
    type="str",
    default=(
        "I authorise {organisation} to charge my saved payment method for invoices when "
        "they are issued, until I withdraw this permission."
    ),
    max_length=1000,
    label=_("Auto-pay consent wording"),
)
