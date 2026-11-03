"""Ready-made pathways (E34 FR-34-1, T02): templates shipped in code and installed for every
organisation, which can edit, switch off and reset them, like E33 built-in workflows.

Each app declares its ready-made pathways in ``<app>/pathways_builtin.py``::

    @builtin_pathway("join_job", "join", name=N_("Join a job"), description=N_("..."), version=1)
    def join_job() -> dict[str, Any]:
        return {"record_type": "job", "stages": [...]}

The function returns the default stages. Bump ``version`` when the default changes:
organisations that never edited theirs get the new one (``services.install_builtins``);
edited ones keep theirs and are told an update is available. Strings in the stages are
``gettext_noop`` texts, translated when the template is installed or reset.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Definition = dict[str, Any]


@dataclass(frozen=True)
class BuiltinPathway:
    key: str
    kind: str  # apply | join | finish | custom
    name: str  # gettext_noop strings, translated when installed
    description: str
    version: int
    default: Callable[[], Definition]

    def definition(self) -> Definition:
        raw = self.default()
        return {"record_type": raw.get("record_type", "job"), "stages": list(raw["stages"])}


_BUILTINS: dict[str, BuiltinPathway] = {}


def register(pathway: BuiltinPathway) -> BuiltinPathway:
    _BUILTINS[pathway.key] = pathway
    return pathway


def unregister(key: str) -> None:
    _BUILTINS.pop(key, None)


def builtin_pathway(
    key: str, kind: str, *, name: str, description: str, version: int = 1
) -> Callable[[Callable[[], Definition]], Callable[[], Definition]]:
    def decorator(default: Callable[[], Definition]) -> Callable[[], Definition]:
        register(BuiltinPathway(key, kind, name, description, version, default))
        return default

    return decorator


def builtin(key: str) -> BuiltinPathway | None:
    return _BUILTINS.get(key)


def all_builtins() -> list[BuiltinPathway]:
    return list(_BUILTINS.values())


def discover() -> None:
    """Import every app's ``pathways_builtin`` module (from ``AppConfig.ready``)."""
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("pathways_builtin")
