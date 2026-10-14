"""AI assistant settings (E31): organisation-wide defaults. Per-feature opt-in, tone and
spelling live on ``AIFeatureSetting``."""

from __future__ import annotations

import uuid
from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.tenancy.settings_registry import register

TONES = (("friendly", _("Friendly")), ("formal", _("Formal")))
SPELLINGS = (("en-GB", _("UK English")), ("en-US", _("US English")))
INTENTS = ("reschedule", "cancellation", "billing", "complaint", "new_enquiry", "feedback", "other")


def _routing(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise serializers.ValidationError(_("Map intents to team members."))
    out: dict[str, str] = {}
    for intent, user_id in value.items():
        if intent not in INTENTS:
            raise serializers.ValidationError(_("Unknown intent: %(i)s") % {"i": intent})
        if user_id in (None, ""):
            continue
        try:
            out[intent] = str(uuid.UUID(str(user_id)))
        except ValueError as exc:
            raise serializers.ValidationError(_("Not a valid team member.")) from exc
    return out


register(
    "ai.tone",
    type="choice",
    default="friendly",
    choices=TONES,
    label=_("Tone of AI drafts"),
)
register(
    "ai.spelling",
    type="choice",
    default="en-GB",
    choices=SPELLINGS,
    label=_("Spelling in AI drafts"),
)
register(
    "ai.monthly_credit_cap",
    type="int",
    default=0,
    min_value=0,
    max_value=10_000_000,
    label=_("Most AI credits to use each month (0: no cap beyond your credits)"),
)
register(
    "ai.inbox_auto_classify",
    type="bool",
    default=False,
    label=_("Classify new inbox messages by intent automatically"),
)
register(
    "ai.inbox_routing",
    type="object",
    default={},
    schema={"type": "object", "additionalProperties": {"type": "string", "format": "uuid"}},
    validator=_routing,
    label=_("Assign unassigned conversations by intent"),
    help_text=_("Only internal routing: replies always need a person."),
)
