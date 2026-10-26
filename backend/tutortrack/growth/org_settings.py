"""Review, referral and affiliate settings (E25)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

# --- reviews (FR-25-1) --------------------------------------------------------------------------
register(
    "growth.review_after_lessons",
    type="int",
    default=5,
    min_value=0,
    max_value=100,
    label=_("Ask for a review after this many completed lessons with a tutor (0: never)"),
)
register(
    "growth.review_after_trial",
    type="bool",
    default=True,
    label=_("Ask for a review after a trial lesson"),
)
register(
    "growth.review_reminder_days",
    type="int",
    default=4,
    min_value=1,
    max_value=60,
    label=_("Days before reminding a family who hasn't reviewed"),
    replaced_by="review_request",
)
register(
    "growth.review_expiry_days",
    type="int",
    default=21,
    min_value=2,
    max_value=180,
    label=_("Days a review link stays open"),
)
register(
    "growth.review_criteria",
    type="str",
    default="communication,knowledge,punctuality",
    max_length=300,
    label=_("Optional rating criteria (comma-separated)"),
)
register(
    "growth.tutors_see_reviews",
    type="bool",
    default=True,
    label=_("Tutors can see approved reviews about them"),
)
register(
    "growth.auto_testimonial",
    type="bool",
    default=False,
    label=_("Publish approved 4 and 5 star reviews as testimonials when the family agreed"),
)
register(
    "growth.google_review_url",
    type="str",
    default="",
    max_length=500,
    label=_("Google Business Profile review link (asked after 4 and 5 star reviews)"),
)
register(
    "growth.show_ratings_publicly",
    type="bool",
    default=False,
    label=_("Show tutors' average rating in the public directory"),
)

# --- referrals (FR-25-2) ------------------------------------------------------------------------
register(
    "growth.referrals_enabled",
    type="bool",
    default=True,
    label=_("Run the client referral programme"),
)
register(
    "growth.attribution_days",
    type="int",
    default=90,
    min_value=1,
    max_value=365,
    label=_("Days a referral or affiliate link is remembered on the website"),
)

# --- affiliates (FR-25-3) -----------------------------------------------------------------------
register(
    "growth.clawback_days",
    type="int",
    default=180,
    min_value=0,
    max_value=730,
    label=_("Refunds claw back commission within this many days of the payment"),
)
register(
    "growth.statement_schedule",
    type="choice",
    default="manual",
    choices=(
        ("manual", _("Staff issue statements")),
        ("monthly", _("Issue statements on the 1st of each month")),
    ),
    label=_("Affiliate statements"),
)

# --- tutor referral bonuses (FR-25-4) -----------------------------------------------------------
register(
    "growth.tutor_referral_bonus",
    type="int",
    default=0,
    min_value=0,
    max_value=100000,
    label=_("Bonus for a tutor who refers a tutor (whole currency units, 0: none)"),
)
register(
    "growth.tutor_client_referral_bonus",
    type="int",
    default=0,
    min_value=0,
    max_value=100000,
    label=_("Bonus for a tutor who refers a client (whole currency units, 0: none)"),
)
register(
    "growth.tutor_referral_milestone_lessons",
    type="int",
    default=5,
    min_value=0,
    max_value=200,
    label=_("Lessons the referred tutor must complete before the bonus (0: on approval)"),
)
