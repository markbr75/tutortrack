"""Report template fields: validation, the default "Simple" template and answer checks
(FR-09-4, FR-09-5)."""

from __future__ import annotations

import re
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

FIELD_TYPES = (
    "rich_text",
    "text",
    "rating",
    "select",
    "multi_select",
    "checklist",
    "topics",
    "homework",
    "next_steps",
    "attachment",
)
CHOICE_TYPES = {"select", "multi_select", "checklist"}
LIST_TYPES = {"multi_select", "checklist", "topics", "attachment"}
VISIBILITY = ("staff", "client", "student")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_TEXT = 20_000


def simple_fields() -> list[dict[str, Any]]:
    return [
        {
            "key": "covered",
            "label": _("What we covered"),
            "type": "rich_text",
            "required": True,
            "visibility": "student",
        },
        {
            "key": "homework",
            "label": _("Homework"),
            "type": "homework",
            "required": False,
            "visibility": "student",
        },
        {
            "key": "parent_notes",
            "label": _("Notes for parent"),
            "type": "rich_text",
            "required": False,
            "visibility": "client",
        },
        {
            "key": "private_notes",
            "label": _("Private notes"),
            "type": "text",
            "required": False,
            "visibility": "staff",
            "help_text": _("Only staff and tutors see this."),
        },
    ]


def _invalid(message: str, field: str = "fields") -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def clean_fields(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise _invalid(_("Add at least one field."))
    if len(raw) > 50:
        raise _invalid(_("A template can have at most 50 fields."))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise _invalid(_("Each field needs a key, label and type."))
        key = str(item.get("key", ""))
        if not KEY_RE.match(key):
            raise _invalid(
                _("Field keys use lower-case letters, digits and underscores: %(key)s")
                % {"key": key or "?"}
            )
        if key in seen:
            raise _invalid(_("Two fields share the key %(key)s.") % {"key": key})
        seen.add(key)
        kind = item.get("type")
        if kind not in FIELD_TYPES:
            raise _invalid(_("Unknown field type for %(key)s.") % {"key": key})
        label = str(item.get("label", "")).strip()
        if not label or len(label) > 200:
            raise _invalid(_("Give %(key)s a label (up to 200 characters).") % {"key": key})
        visibility = item.get("visibility", "client")
        if visibility not in VISIBILITY:
            raise _invalid(_("Unknown visibility for %(key)s.") % {"key": key})
        field: dict[str, Any] = {
            "key": key,
            "label": label,
            "type": kind,
            "required": bool(item.get("required", False)),
            "visibility": visibility,
        }
        if item.get("help_text"):
            field["help_text"] = str(item["help_text"])[:300]
        if kind in CHOICE_TYPES:
            options = item.get("options")
            if not isinstance(options, list) or not options or len(options) > 50:
                raise _invalid(_("Give %(key)s between 1 and 50 options.") % {"key": key})
            field["options"] = [str(o)[:100] for o in options]
        out.append(field)
    return out


def _bad(key: str) -> BusinessRuleViolation:
    message = _("This answer isn't valid.")
    return BusinessRuleViolation(message, extra={"errors": {key: [message]}})


def clean_answers(
    fields: list[dict[str, Any]], answers: Any, *, require: bool = False
) -> dict[str, Any]:
    """Keep answers for known fields, type-check them and (on submit) require them."""
    if not isinstance(answers, dict):
        raise _invalid(_("Answers must be an object."), "answers")
    out: dict[str, Any] = {}
    missing: dict[str, list[str]] = {}
    for field in fields:
        key, kind = field["key"], field["type"]
        value = answers.get(key)
        empty = value in (None, "", [], {})
        if empty:
            if require and field.get("required"):
                missing[key] = [_("This field is required.")]
            continue
        if kind == "rating":
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                raise _bad(key)
        elif kind == "select":
            if value not in field.get("options", []):
                raise _bad(key)
        elif kind in LIST_TYPES:
            if not isinstance(value, list) or len(value) > 100:
                raise _bad(key)
            if kind in CHOICE_TYPES and any(v not in field.get("options", []) for v in value):
                raise _bad(key)
            value = [str(v)[:500] for v in value]
        elif not isinstance(value, str) or len(value) > MAX_TEXT:
            raise _bad(key)
        out[key] = value
    if missing:
        raise BusinessRuleViolation(_("Fill in the required fields."), extra={"errors": missing})
    return out


AUDIENCE_FIELDS = {
    "staff": set(VISIBILITY),
    "client": {"client", "student"},
    "student": {"student"},
}


def visible_answers(
    fields: list[dict[str, Any]], answers: dict[str, Any], audience: str
) -> dict[str, Any]:
    """Answers the audience (``staff``, ``client`` or ``student``) may see (FR-09-4)."""
    allowed = AUDIENCE_FIELDS[audience]
    keys = {f["key"] for f in fields if f.get("visibility", "client") in allowed}
    return {k: v for k, v in answers.items() if k in keys}
