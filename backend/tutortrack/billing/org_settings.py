"""Billing settings (FR-10-13). Tax settings (``billing.prices_include_tax``,
``billing.tax_registered``) are registered by the catalogue."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "billing.invoice_prefix",
    type="str",
    default="INV-",
    max_length=10,
    label=_("Invoice number prefix"),
)
register(
    "billing.credit_note_prefix",
    type="str",
    default="CN-",
    max_length=10,
    label=_("Credit note number prefix"),
)
register(
    "billing.payment_request_prefix",
    type="str",
    default="PR-",
    max_length=10,
    label=_("Payment request number prefix"),
)
register(
    "billing.invoice_schedule",
    type="choice",
    default="manual",
    choices=(
        ("manual", _("When I run invoicing")),
        ("weekly", _("Weekly")),
        ("monthly", _("Monthly")),
    ),
    label=_("Create invoices"),
    replaced_by="invoicing_cycle",
)
register(
    "billing.invoice_day",
    type="int",
    default=1,
    min_value=1,
    max_value=28,
    label=_("Invoice on this day of the month (or weekday 1\N{EN DASH}7 for weekly)"),
    replaced_by="invoicing_cycle",
)
register(
    "billing.review_days",
    type="int",
    default=2,
    min_value=0,
    max_value=30,
    label=_("Days to review draft invoices before they are issued"),
)
register(
    "billing.auto_issue",
    type="bool",
    default=True,
    label=_("Issue drafts automatically after the review period"),
)
register(
    "billing.auto_send", type="bool", default=True, label=_("Email invoices to clients when issued")
)
register(
    "billing.auto_apply_credit",
    type="bool",
    default=True,
    label=_("Use client credit on new invoices automatically"),
)
register(
    "billing.minimum_invoice_amount",
    type="int",
    default=0,
    min_value=0,
    label=_("Don't invoice less than this (whole currency units)"),
)
register(
    "billing.skip_zero_invoices",
    type="bool",
    default=True,
    label=_("Don't create invoices that total zero"),
)
register(
    "billing.show_tutor_names", type="bool", default=True, label=_("Show tutor names on invoices")
)
register(
    "billing.payment_instructions",
    type="str",
    default="",
    max_length=1000,
    label=_("Payment instructions on invoices"),
)
register(
    "billing.invoice_footer", type="str", default="", max_length=1000, label=_("Invoice footer")
)
register(
    "billing.reminders_enabled",
    type="bool",
    default=True,
    label=_("Send payment reminders"),
    replaced_by="payment_chasing",
)
register(
    "billing.reminder_offsets",
    type="object",
    default=[-3, 0, 3, 7, 14, 30],
    label=_("Reminder days relative to the due date"),
    help_text=_("Negative numbers are before the due date."),
    replaced_by="payment_chasing",
)
register(
    "billing.prevent_negative_balance",
    type="bool",
    default=True,
    label=_("Prepaid clients need credit before lessons are completed"),
)
register(
    "billing.prepaid_invoice_each_lesson",
    type="bool",
    default=True,
    label=_("Prepaid clients get a receipt invoice for each lesson, paid from credit"),
)
register(
    "billing.topup_threshold",
    type="int",
    default=0,
    min_value=0,
    label=_("Ask prepaid clients to top up when credit falls below (0: off)"),
)
register(
    "billing.topup_amount", type="int", default=200, min_value=1, label=_("Top-up request amount")
)

# --- Phase 2 (E10-T12..T14) ---------------------------------------------------------------------
register(
    "billing.package_invoice_immediately",
    type="bool",
    default=True,
    label=_("Invoice package sales straight away (otherwise on the next invoice run)"),
)
register(
    "billing.package_activation",
    type="choice",
    default="payment",
    choices=(
        ("payment", _("When the package invoice is paid")),
        ("issue", _("When the package invoice is issued")),
    ),
    label=_("Packages can be used"),
)
register(
    "billing.package_low_units",
    type="int",
    default=1,
    min_value=0,
    label=_("Tell clients when a package has this many units left (0: off)"),
)
register(
    "billing.package_expiry_reminder_days",
    type="int",
    default=14,
    min_value=0,
    max_value=180,
    label=_("Remind clients this many days before unused package units expire (0: off)"),
    replaced_by="package_expiry",
)
register(
    "billing.plan_invoice_immediately",
    type="bool",
    default=True,
    label=_("Invoice recurring fees as soon as each period starts"),
)
register(
    "billing.collections_after_days",
    type="int",
    default=0,
    min_value=0,
    max_value=365,
    label=_("Put clients in collections when an invoice is this many days overdue (0: off)"),
    replaced_by="payment_chasing",
)
register(
    "billing.collections_block",
    type="choice",
    default="soft",
    choices=(
        ("none", _("Don't block lessons")),
        ("soft", _("Warn staff when scheduling")),
        ("hard", _("Warn staff and stop online booking")),
    ),
    label=_("While a client is in collections"),
)

# --- gap G3 -----------------------------------------------------------------------------------
register(
    "billing.tutor_review",
    type="bool",
    default=False,
    scope="branch",
    label=_("Ask tutors to check their lessons on draft invoices"),
    help_text=_(
        "Tutors see the dates, students and lessons (never amounts). Drafts a tutor reports "
        "a problem with are held for you to correct."
    ),
)
register(
    "billing.tutor_review_days",
    type="int",
    default=2,
    min_value=1,
    max_value=14,
    scope="branch",
    label=_("Days tutors have to check draft invoices"),
)
register(
    "billing.statement_schedule",
    type="choice",
    default="none",
    choices=(("none", _("Don't send")), ("monthly", _("Every month"))),
    label=_("Email clients a statement"),
    help_text=_("Clients with account activity or a balance get last month's statement."),
    replaced_by="monthly_statements",
)
register(
    "billing.statement_day",
    type="int",
    default=1,
    min_value=1,
    max_value=28,
    label=_("Day of the month statements are sent"),
    replaced_by="monthly_statements",
)
