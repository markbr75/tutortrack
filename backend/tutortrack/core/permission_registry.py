"""Permission codename registry (FR-03-5).

Each app declares its codenames in ``<app>/permissions.py`` as
``PERMISSIONS = {"billing.invoice.issue": "Issue invoices", ...}`` (autodiscovered).
Codenames are ``<category>.<object>.<action>``; the first segment is the category shown
in the roles UI. Roles grant codename *patterns* (``"billing.*"``, ``"*"``), so a new app's
permissions flow into the built-in roles without editing them.
"""

from __future__ import annotations

import fnmatch
import importlib
from dataclasses import dataclass
from functools import cache

from django.apps import apps


@dataclass(frozen=True)
class PermissionDef:
    codename: str
    description: str

    @property
    def category(self) -> str:
        return self.codename.split(".", 1)[0]


_extra: dict[str, str] = {}


def register(codename: str, description: str) -> None:
    """Register a codename outside a permissions module (tests, plugins)."""
    _extra[codename] = description
    all_permissions.cache_clear()


@cache
def all_permissions() -> dict[str, PermissionDef]:
    found: dict[str, str] = {}
    for config in apps.get_app_configs():
        try:
            module = importlib.import_module(f"{config.name}.permissions")
        except ModuleNotFoundError:
            continue
        found.update(getattr(module, "PERMISSIONS", {}) or {})
    found.update(_extra)
    return {code: PermissionDef(code, desc) for code, desc in sorted(found.items())}


def matches(pattern: str, codename: str) -> bool:
    return pattern == codename or fnmatch.fnmatchcase(codename, pattern)


def expand(pattern: str) -> list[str]:
    """Registered codenames a pattern grants."""
    return [c for c in all_permissions() if matches(pattern, c)]
