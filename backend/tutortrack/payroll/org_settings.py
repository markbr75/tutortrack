"""Pay settings (FR-12-2). Branch-scoped where branches pay on different cycles."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "payroll.pay_period",
    type="choice",
    default="monthly",
    choices=(
        ("manual", _("Manual (create pay runs yourself)")),
        ("weekly", _("Weekly")),
        ("fortnightly", _("Every two weeks")),
        ("semi_monthly", _("Twice a month (15th and month end)")),
        ("monthly", _("Monthly")),
    ),
    label=_("Pay period"),
    scope="branch",
)
register(
    "payroll.cut_off_day",
    type="int",
    default=28,
    min_value=1,
    max_value=28,
    label=_("Cut-off day (monthly: day of month; weekly: 1 = Monday ... 7 = Sunday)"),
    scope="branch",
)
register(
    "payroll.pay_when_client_paid",
    type="bool",
    default=False,
    label=_("Only pay tutors for lessons once the client has paid"),
)
register(
    "payroll.hold_on_overdue_report",
    type="bool",
    default=True,
    label=_("Hold lesson pay while the lesson report is overdue"),
)
register(
    "payroll.include_cancellations",
    type="bool",
    default=True,
    label=_("Pay tutors their share of chargeable cancellations"),
)
register(
    "payroll.min_payout",
    type="str",
    default="0",
    label=_("Carry forward payouts smaller than this amount"),
)
register(
    "payroll.dual_approval_threshold",
    type="str",
    default="",
    label=_("Pay runs above this total need a second approver (empty = never)"),
)
register(
    "payroll.bank_file_format",
    type="choice",
    default="csv",
    choices=(
        ("csv", _("Generic CSV")),
        ("bacs18", _("UK BACS Standard 18")),
        ("sepa", _("SEPA credit transfer (pain.001)")),
        ("nacha", _("US NACHA (ACH)")),
        ("aba", _("Australian ABA")),
    ),
    label=_("Bank payment file format"),
)
register(
    "payroll.expense_markup_percent",
    type="str",
    default="0",
    label=_("Markup when rebilling expenses to clients (%)"),
)
register(
    "payroll.mileage_from_home",
    type="bool",
    default=False,
    label=_("Suggest mileage from the tutor's home to the first lesson of the day"),
)
register(
    "payroll.self_billing_vat_percent",
    type="str",
    default="20",
    label=_("VAT rate on self-billing invoices for VAT-registered tutors (%)"),
)
