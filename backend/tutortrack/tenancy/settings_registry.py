"""Typed organisation/branch settings (FR-02-5).

Each epic registers the settings it owns in its app's ``org_settings.py`` module
(autodiscovered at startup) and reads them with ``tenancy.settings_service.get_setting``::

    from tutortrack.tenancy.settings_registry import register

    register("billing.auto_invoice_day", type="int", default=1, scope="branch",
             label=_("Auto-invoice day"), min_value=1, max_value=28)

    day = settings_service.get_setting("billing.auto_invoice_day", branch=lesson.branch)

The part before the first dot is the *area* (``general``, ``billing``, ...), which is what
``/api/v1/settings/{area}`` serves. ``scope="branch"`` settings may be overridden per
branch; resolution is branch override → organisation value → registered default.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.utils.functional import Promise
from rest_framework import serializers

TYPES = ("int", "str", "bool", "choice", "object")
SCOPES = ("organisation", "branch")


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    type: str
    default: Any
    scope: str = "organisation"
    label: str | Promise = ""
    help_text: str | Promise = ""
    choices: tuple[tuple[str, str | Promise], ...] = ()
    min_value: int | None = None
    max_value: int | None = None
    max_length: int | None = None
    # For type="object": a JSON-schema fragment describing the value (shown to the frontend)
    # and a validator that returns the cleaned value or raises serializers.ValidationError.
    schema: dict[str, Any] = field(default_factory=dict)
    validator: Callable[[Any], Any] | None = None

    @property
    def area(self) -> str:
        return self.key.split(".", 1)[0]

    def field(self) -> serializers.Field:
        kwargs: dict[str, Any] = {"required": False}
        if self.type == "int":
            return serializers.IntegerField(
                min_value=self.min_value, max_value=self.max_value, **kwargs
            )
        if self.type == "str":
            return serializers.CharField(
                max_length=self.max_length, allow_blank=True, trim_whitespace=True, **kwargs
            )
        if self.type == "bool":
            return serializers.BooleanField(**kwargs)
        if self.type == "choice":
            return serializers.ChoiceField(choices=list(self.choices), **kwargs)
        return serializers.JSONField(**kwargs)

    def clean(self, value: Any) -> Any:
        """Validate and normalise ``value``; raises ``serializers.ValidationError``."""
        cleaned = self.field().run_validation(value)
        if self.validator is not None:
            cleaned = self.validator(cleaned)
        return cleaned

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "type": self.type,
            "scope": self.scope,
            "default": copy.deepcopy(self.default),
            "label": str(self.label),
            "help_text": str(self.help_text),
        }
        if self.choices:
            out["choices"] = [{"value": v, "label": str(lbl)} for v, lbl in self.choices]
        for name in ("min_value", "max_value", "max_length"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        if self.schema:
            out["schema"] = self.schema
        return out


class SettingsRegistry:
    def __init__(self) -> None:
        self._defs: dict[str, SettingDefinition] = {}

    def register(self, key: str, *, type: str, default: Any, **options: Any) -> SettingDefinition:
        if "." not in key:
            raise ValueError(f"Setting keys are '<area>.<name>': {key!r}")
        if type not in TYPES:
            raise ValueError(f"Unknown setting type {type!r} for {key}")
        if options.get("scope", "organisation") not in SCOPES:
            raise ValueError(f"Unknown scope for {key}")
        definition = SettingDefinition(key=key, type=type, default=default, **options)
        existing = self._defs.get(key)
        if existing is not None and existing != definition:
            raise ValueError(f"Setting {key!r} is already registered differently")
        definition.clean(copy.deepcopy(default))  # the default must itself be valid
        self._defs[key] = definition
        return definition

    def get(self, key: str) -> SettingDefinition:
        try:
            return self._defs[key]
        except KeyError:
            raise KeyError(f"Unknown setting {key!r}") from None

    def area(self, area: str) -> list[SettingDefinition]:
        return [d for k, d in sorted(self._defs.items()) if d.area == area]

    def areas(self) -> list[str]:
        return sorted({d.area for d in self._defs.values()})


registry = SettingsRegistry()
register = registry.register
