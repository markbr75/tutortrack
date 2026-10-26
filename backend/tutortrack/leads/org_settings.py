"""Lead settings (FR-17-2, FR-17-6)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "leads.lost_reasons",
    type="object",
    default=[
        "too_expensive",
        "chose_competitor",
        "no_tutor_available",
        "no_response",
        "timing",
        "other",
    ],
    label=_("Reasons an enquiry can be lost"),
)
register(
    "leads.acknowledge",
    type="bool",
    default=True,
    label=_("Send an automatic reply to new enquiries"),
    replaced_by="enquiry_follow_up",
)
register(
    "leads.waitlist_offer_hours",
    type="int",
    default=48,
    min_value=1,
    max_value=336,
    label=_("Hours a family has to accept a waitlist place"),
)
register(
    "leads.waitlist_auto_cascade",
    type="bool",
    default=True,
    label=_("Offer an unclaimed place to the next student automatically"),
)
register(
    "leads.trial_follow_up_hours",
    type="int",
    default=24,
    min_value=1,
    max_value=168,
    label=_("Remind the owner to record the trial outcome after (hours)"),
    replaced_by="trial_follow_up",
)

register(
    "leads.proposal_valid_days",
    type="int",
    default=14,
    min_value=1,
    max_value=90,
    label=_("Days a proposal can be accepted"),
)
register(
    "leads.proposal_reminder_days",
    type="int",
    default=3,
    min_value=0,
    max_value=60,
    label=_("Remind the family this many days before a proposal expires (0: no reminder)"),
)
register(
    "leads.proposal_terms",
    type="str",
    default="",
    max_length=5000,
    label=_("Standard terms shown on proposals"),
)
