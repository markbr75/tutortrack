"""Matching settings (FR-19-1, FR-19-2, FR-19-4)."""

from django.utils.translation import gettext_lazy as _

from tutortrack.tenancy.settings_registry import register

DEFAULT_WEIGHTS = {
    "availability": 30,
    "distance": 15,
    "rating": 10,
    "experience": 10,
    "workload": 10,
    "history": 10,
    "margin": 5,
    "response": 5,
    "fairness": 5,
}

register(
    "matching.weights",
    type="object",
    default=DEFAULT_WEIGHTS,
    label=_("How much each factor counts in the match score"),
)
register(
    "matching.default_radius_km",
    type="int",
    default=15,
    min_value=1,
    max_value=200,
    label=_("Travel radius for tutors who haven't set one (km)"),
)
register(
    "matching.target_margin_percent",
    type="int",
    default=40,
    min_value=0,
    max_value=95,
    label=_("Target margin for the margin factor (%)"),
)
register(
    "matching.offer_expiry_hours",
    type="int",
    default=24,
    min_value=1,
    max_value=336,
    label=_("Hours a tutor has to answer a job offer"),
)
register(
    "matching.admin_confirms",
    type="bool",
    default=False,
    label=_("A coordinator confirms an accepted offer before the tutor is assigned"),
)
register(
    "matching.cover_cutoff_hours",
    type="int",
    default=2,
    min_value=0,
    max_value=72,
    label=_("Stop looking for cover this many hours before the lesson"),
)
register(
    "matching.cover_notify_limit",
    type="int",
    default=10,
    min_value=1,
    max_value=100,
    label=_("Tutors told about each cover request"),
)
