"""Course and class settings (E20)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "courses.proration_basis",
    type="choice",
    default="sessions",
    choices=(
        ("sessions", _("Remaining sessions")),
        ("weeks", _("Remaining teaching weeks (breaks left out)")),
    ),
    label=_("Charge students who join part way through by"),
)
register(
    "courses.prorate_mid_term_joins",
    type="bool",
    default=True,
    label=_("Charge less when a student joins after the class has started"),
)
register(
    "courses.fee_timing",
    type="choice",
    default="at_enrolment",
    choices=(
        ("at_enrolment", _("Invoice when the student enrols")),
        ("term_start", _("Charge from the start of term (next invoice run)")),
    ),
    label=_("Term and course fees"),
)
register(
    "courses.withdrawal_refund",
    type="choice",
    default="unused_sessions",
    choices=(
        ("unused_sessions", _("Credit unused sessions")),
        ("none", _("No refund")),
    ),
    label=_("When a student withdraws"),
)
register(
    "courses.online_payment",
    type="choice",
    default="none",
    choices=(
        ("none", _("Invoice as usual")),
        ("full", _("Pay in full when enrolling online")),
        ("deposit", _("Pay the course deposit when enrolling online")),
    ),
    label=_("Payment when families enrol online"),
)
register(
    "courses.payment_hold_minutes",
    type="int",
    default=30,
    min_value=5,
    max_value=2880,
    label=_("Minutes a place is held while a family pays"),
)
register(
    "courses.waitlist_auto_offer",
    type="bool",
    default=True,
    label=_("Offer a free place to the next student on the waitlist automatically"),
)
register(
    "courses.waitlist_offer_hours",
    type="int",
    default=48,
    min_value=1,
    max_value=336,
    label=_("Hours a family has to accept a place"),
)
register(
    "courses.makeup_credit_days",
    type="int",
    default=60,
    min_value=1,
    max_value=365,
    label=_("Days a makeup credit for a missed class lasts"),
)
register(
    "courses.breaks_skip_all_lessons",
    type="bool",
    default=False,
    label=_("Term breaks also pause one-to-one lessons in the branch"),
)
register(
    "courses.enrolment_terms",
    type="str",
    default="",
    max_length=5000,
    label=_("Terms families accept when enrolling online"),
)
