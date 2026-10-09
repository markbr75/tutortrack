"""Settings owned by tenancy: the "general" area (FR-02-5).

``billing.invoicing_style`` is registered here because the onboarding wizard (E02-T07)
sets it; E10 takes ownership and adds the rest of the billing area.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .settings_registry import register

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Words the UI lets each organisation rename ("Tutor" -> "Teacher", "Client" -> "Family").
TERMS = ("tutor", "student", "client", "lesson", "job")
DEFAULT_TERMINOLOGY: dict[str, dict[str, str]] = {
    "tutor": {"singular": "Tutor", "plural": "Tutors"},
    "student": {"singular": "Student", "plural": "Students"},
    "client": {"singular": "Client", "plural": "Clients"},
    "lesson": {"singular": "Lesson", "plural": "Lessons"},
    "job": {"singular": "Job", "plural": "Jobs"},
}

DEFAULT_BUSINESS_HOURS: dict[str, list[dict[str, str]]] = {
    **{d: [{"start": "09:00", "end": "20:00"}] for d in DAYS[:5]},
    "sat": [{"start": "09:00", "end": "17:00"}],
    "sun": [],
}


def validate_business_hours(value: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict) or set(value) - set(DAYS):
        raise serializers.ValidationError(_("Use the keys mon to sun."))
    cleaned: dict[str, list[dict[str, str]]] = {}
    for day in DAYS:
        periods = value.get(day, [])
        if not isinstance(periods, list):
            raise serializers.ValidationError(_("Each day is a list of periods."))
        out = []
        for period in periods:
            start, end = (period or {}).get("start", ""), (period or {}).get("end", "")
            if not (_HHMM.match(str(start)) and _HHMM.match(str(end))) or start >= end:
                raise serializers.ValidationError(
                    _("Periods need a start and end time (HH:MM), with start before end.")
                )
            out.append({"start": start, "end": end})
        out.sort(key=lambda p: p["start"])
        for a, b in pairwise(out):
            if b["start"] < a["end"]:
                raise serializers.ValidationError(_("Periods on the same day overlap."))
        cleaned[day] = out
    return cleaned


def validate_terminology(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) - set(TERMS):
        raise serializers.ValidationError(_("Unknown term."))
    cleaned = {}
    for term in TERMS:
        words = value.get(term, DEFAULT_TERMINOLOGY[term])
        if not isinstance(words, dict):
            raise serializers.ValidationError(_("Give a singular and plural form."))
        singular = str(words.get("singular", "")).strip()
        plural = str(words.get("plural", "")).strip()
        if not (0 < len(singular) <= 30 and 0 < len(plural) <= 30):
            raise serializers.ValidationError(
                _("Singular and plural forms are required (30 characters max).")
            )
        cleaned[term] = {"singular": singular, "plural": plural}
    return cleaned


register(
    "general.business_hours",
    type="object",
    default=DEFAULT_BUSINESS_HOURS,
    scope="branch",
    label=_("Business hours"),
    help_text=_("When you normally teach. Used for scheduling suggestions and booking."),
    schema={
        "type": "object",
        "properties": {
            d: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "pattern": "^\\d{2}:\\d{2}$"},
                        "end": {"type": "string", "pattern": "^\\d{2}:\\d{2}$"},
                    },
                },
            }
            for d in DAYS
        },
    },
    validator=validate_business_hours,
)
register(
    "general.default_lesson_duration",
    type="int",
    default=60,
    scope="branch",
    label=_("Default lesson length (minutes)"),
    min_value=5,
    max_value=480,
)
register(
    "general.terminology",
    type="object",
    default=DEFAULT_TERMINOLOGY,
    label=_("Terminology"),
    help_text=_('Rename key words across the app, e.g. "Tutor" to "Teacher".'),
    schema={
        "type": "object",
        "properties": {
            t: {
                "type": "object",
                "properties": {"singular": {"type": "string"}, "plural": {"type": "string"}},
            }
            for t in TERMS
        },
    },
    validator=validate_terminology,
)
register(
    "billing.invoicing_style",
    type="choice",
    default="payg",
    label=_("Invoicing style"),
    choices=(
        ("payg", _("Pay as you go, invoiced after lessons")),
        ("monthly_advance", _("Monthly in advance")),
        ("packages", _("Prepaid packages")),
    ),
)
register(
    "privacy.closure_grace_days",
    type="int",
    default=30,
    min_value=1,
    max_value=365,
    label=_("Days to keep a closed account before deletion"),
    help_text=_("Used by the account closure process (FR-02-8). E29 owns the privacy area."),
)
