"""Built-in workflows (E33 FR-33-2): sequences shipped in code and installed for every
organisation, which can edit, test, switch off (where that is safe) and reset them.

Each app declares its built-ins in ``<app>/workflows_builtin.py``::

    @builtin_workflow("payment_chasing", "invoicing", name=N_("Payment chasing"),
                      description=N_("..."), version=1, off_means=N_("..."))
    def payment_chasing() -> dict[str, Any]:
        return {"trigger_type": "event", "trigger_config": {"event": "invoice.issued"},
                "steps": [...], "stop_when": ["invoice.paid"]}

The function returns the default definition. Bump ``version`` when the default changes:
organisations that never edited theirs get the new one (``services.install_builtins``);
edited ones keep theirs and are told an update is available. ``first_version`` builds an
organisation's first version from its current settings, so behaviour doesn't change on the
day a built-in replaces a hard-wired process.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_noop as N_

Definition = dict[str, Any]

GROUPS: dict[str, str] = {
    "invoicing": N_("Invoicing and payment chasing"),
    "lessons": N_("Lesson communications"),
    "sales": N_("Sales and onboarding"),
    "expiry": N_("Expiry reminders"),
}
DEFINITION_KEYS = ("trigger_type", "trigger_config", "conditions", "steps", "stop_when")


@dataclass(frozen=True)
class BuiltinWorkflow:
    key: str
    group: str
    name: str  # gettext_noop strings, translated when shown
    description: str
    version: int
    default: Callable[[], Definition]
    first_version: Callable[[], Definition | None] | None = None
    can_switch_off: bool = True
    off_means: str = ""  # what happens instead while it's off ("Invoices are made by hand")
    enabled: bool = True  # switched on when installed
    max_runs_per_record: int = 1

    def definition(self, *, first: bool = False) -> Definition:
        """The default (or, for a first install, the version from the organisation's
        settings), with every definition key filled in."""
        found = self.first_version() if first and self.first_version else None
        raw = found or self.default()
        return {
            "trigger_type": raw["trigger_type"],
            "trigger_config": dict(raw.get("trigger_config") or {}),
            "conditions": dict(raw.get("conditions") or {}),
            "steps": list(raw.get("steps") or []),
            "stop_when": list(raw.get("stop_when") or []),
        }


_BUILTINS: dict[str, BuiltinWorkflow] = {}


def register(workflow: BuiltinWorkflow) -> BuiltinWorkflow:
    if workflow.group not in GROUPS:
        raise ValueError(f"Unknown built-in workflow group {workflow.group!r}")
    _BUILTINS[workflow.key] = workflow
    return workflow


def unregister(key: str) -> None:
    _BUILTINS.pop(key, None)


def builtin_workflow(
    key: str,
    group: str,
    *,
    name: str,
    description: str,
    version: int = 1,
    first_version: Callable[[], Definition | None] | None = None,
    can_switch_off: bool = True,
    off_means: str = "",
    enabled: bool = True,
    max_runs_per_record: int = 1,
) -> Callable[[Callable[[], Definition]], Callable[[], Definition]]:
    def decorator(default: Callable[[], Definition]) -> Callable[[], Definition]:
        register(
            BuiltinWorkflow(
                key=key, group=group, name=name, description=description, version=version,
                default=default, first_version=first_version, can_switch_off=can_switch_off,
                off_means=off_means, enabled=enabled, max_runs_per_record=max_runs_per_record,
            )
        )  # fmt: skip
        return default

    return decorator


def builtin(key: str) -> BuiltinWorkflow | None:
    return _BUILTINS.get(key)


def all_builtins() -> list[BuiltinWorkflow]:
    return list(_BUILTINS.values())


def discover() -> None:
    """Import every app's ``workflows_builtin`` module (from ``AppConfig.ready``)."""
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("workflows_builtin")
