"""Pathway settings (E34 FR-34-1)."""

from typing import Any

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from tutortrack.tenancy.settings_registry import register

KINDS = ("apply", "join", "finish")

register(
    "pathways.reminder_days",
    type="int",
    default=1,
    min_value=0,
    max_value=14,
    label=_("Days before a pathway step is due to remind whoever has to do it (0 = no reminder)"),
)
register(
    "pathways.block_lessons_until_joined",
    type="bool",
    default=True,
    label=_("Lessons can't be confirmed while the tutor is still joining the job"),
)


def _clean_defaults(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - set(KINDS):
        raise serializers.ValidationError(_("Give a pathway key for apply, join or finish."))
    if any(not isinstance(v, str) or len(v) > 60 for v in value.values()):
        raise serializers.ValidationError(_("Pathway keys are text."))
    return {k: v for k, v in value.items() if v}


register(
    "pathways.default_templates",
    type="object",
    default={},
    label=_("The pathways that start on their own, by kind (empty: none start on their own)"),
    schema={
        "type": "object",
        "properties": {k: {"type": "string"} for k in KINDS},
        "additionalProperties": False,
    },
    validator=_clean_defaults,
)
