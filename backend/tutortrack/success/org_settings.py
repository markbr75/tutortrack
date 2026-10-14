"""Organisation settings for product analytics and surveys (E30 FR-30-6)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

register(
    "privacy.product_analytics",
    type="bool",
    default=True,
    label=_(
        "Let staff share anonymous product usage with TutorTrack (each person still chooses "
        "in their cookie settings)"
    ),
)
register(
    "privacy.satisfaction_surveys",
    type="bool",
    default=True,
    label=_("Ask staff for occasional feedback about TutorTrack (NPS)"),
)
