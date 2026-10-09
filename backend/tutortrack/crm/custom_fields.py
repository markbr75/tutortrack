"""Custom field validation (FR-05-5).

``clean_custom_fields(entity_type, incoming, existing=None, creating=...)`` validates the
submitted values against the organisation's active definitions and returns the merged,
normalised dict to store. Unknown keys are rejected. "Required" is enforced when a record
is created, and on update only for keys that are being changed, so a required field added
later does not block saving legacy records (the "missing required data" filter finds them).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator, validate_email
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from rest_framework import serializers

from .models import CustomFieldDefinition as Def


def definitions(entity_type: str) -> list[Def]:
    return list(Def.objects.filter(entity_type=entity_type, active=True))


def _coerce(definition: Def, value: Any) -> Any:
    t = definition.type
    if value in (None, "", []):
        return None
    if t in {Def.Type.TEXT, Def.Type.LONG_TEXT, Def.Type.PHONE}:
        text = str(value).strip()
        limit = 5000 if t == Def.Type.LONG_TEXT else 255
        if len(text) > limit:
            raise ValueError(_("Too long."))
        if definition.validation_regex and not re.fullmatch(definition.validation_regex, text):
            raise ValueError(_("Invalid format."))
        return text
    if t == Def.Type.NUMBER:
        if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value)):
            raise ValueError(_("Enter a whole number."))
        return int(value)
    if t in {Def.Type.DECIMAL, Def.Type.CURRENCY}:
        if isinstance(value, float):
            raise ValueError(_("Send decimals as strings."))
        try:
            return str(Decimal(str(value)))
        except InvalidOperation as exc:
            raise ValueError(_("Enter a number.")) from exc
    if t == Def.Type.DATE:
        parsed = value if isinstance(value, date) else parse_date(str(value))
        if parsed is None:
            raise ValueError(_("Enter a date (YYYY-MM-DD)."))
        return parsed.isoformat()
    if t == Def.Type.DATETIME:
        parsed_dt = value if isinstance(value, datetime) else parse_datetime(str(value))
        if parsed_dt is None or parsed_dt.tzinfo is None:
            raise ValueError(_("Enter a date and time with a timezone."))
        return parsed_dt.isoformat()
    if t == Def.Type.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError(_("Enter true or false."))
        return value
    if t == Def.Type.SELECT:
        if value not in definition.options:
            raise ValueError(_("Choose one of the options."))
        return value
    if t == Def.Type.MULTI_SELECT:
        if not isinstance(value, list) or not set(value) <= set(definition.options):
            raise ValueError(_("Choose from the options."))
        return sorted(set(value), key=definition.options.index)
    if t == Def.Type.EMAIL:
        try:
            validate_email(str(value))
        except DjangoValidationError as exc:
            raise ValueError(_("Enter a valid email.")) from exc
        return str(value).strip().lower()
    if t == Def.Type.URL:
        try:
            URLValidator(schemes=["https", "http"])(str(value))
        except DjangoValidationError as exc:
            raise ValueError(_("Enter a valid URL.")) from exc
        return str(value)
    if t in {Def.Type.FILE, Def.Type.USER}:
        return str(value)  # ids; existence checked by the owning API when rendered
    if t == Def.Type.ADDRESS:
        if not isinstance(value, dict):
            raise ValueError(_("Enter an address."))
        return {
            k: str(v)[:200]
            for k, v in value.items()
            if k in {"line1", "line2", "city", "region", "postcode", "country"}
        }
    raise ValueError(_("Unsupported field type."))


def clean_custom_fields(
    entity_type: str,
    incoming: dict[str, Any] | None,
    existing: dict[str, Any] | None = None,
    *,
    creating: bool,
) -> dict[str, Any]:
    incoming = incoming or {}
    if not isinstance(incoming, dict):
        raise serializers.ValidationError({"custom_fields": [_("Must be an object.")]})
    defs = {d.key: d for d in definitions(entity_type)}
    errors: dict[str, str] = {}
    merged = dict(existing or {})
    for key, value in incoming.items():
        definition = defs.get(key)
        if definition is None:
            errors[key] = _("Unknown field.")
            continue
        try:
            cleaned = _coerce(definition, value)
        except ValueError as exc:
            errors[key] = str(exc)
            continue
        if cleaned is None:
            merged.pop(key, None)
        else:
            merged[key] = cleaned
    for key, definition in defs.items():
        must_check = creating or key in incoming
        if definition.required and must_check and merged.get(key) in (None, "", []):
            errors[key] = _("This field is required.")
    if errors:
        raise serializers.ValidationError({"custom_fields": errors})
    return merged


def missing_required(entity_type: str) -> list[str]:
    """Keys of active required fields (for the "missing required data" filter)."""
    return [d.key for d in definitions(entity_type) if d.required]
