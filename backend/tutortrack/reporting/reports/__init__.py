"""Standard reports (E26-T04..T06). ``run(key, user, data)`` is the single entry point."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.utils.translation import gettext_lazy as _

from tutortrack.core.exceptions import NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm

from .base import (
    Params,
    ReportDef,
    Result,
    all_reports,
    finalise,
    get,
    parse_params,
)

__all__ = [
    "Params",
    "ReportDef",
    "Result",
    "available",
    "find",
    "load_all",
    "run",
]


def load_all() -> None:
    from . import finance, operations, payroll, people, sales  # noqa: F401


def available(user: Any) -> list[ReportDef]:
    return [r for r in all_reports() if has_perm(user, r.codename)]


def find(key: str, user: Any) -> ReportDef:
    report = get(key)
    if report is None:
        raise NotFound(str(_("Unknown report.")))
    if not has_perm(user, report.codename):
        raise PermissionDenied(str(_("You can't run this report.")))
    return report


def run(key: str, user: Any, data: Mapping[str, Any]) -> tuple[ReportDef, Params, Result]:
    report = find(key, user)
    params = parse_params(report, data)
    result = report.run(user, params)
    return report, params, finalise(report, params, result)
