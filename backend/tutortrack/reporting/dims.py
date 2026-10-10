"""Display labels for the ids reports group by (tenant-scoped, read-only)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tutortrack.core.context import branch_scope


def _names(model: Any, ids: list[Any], label: Any, fields: tuple[str, ...]) -> dict[str, str]:
    with branch_scope(None):  # labels only; the figures themselves are already scoped
        rows = model.objects.filter(pk__in=ids).only("pk", *fields)
        return {str(r.pk): label(r) for r in rows}


def labels(dimension: str, ids: Iterable[Any]) -> dict[str, str]:
    """``{id: label}`` for a dimension; unknown dimensions return ``{}``."""
    wanted = list({str(i) for i in ids if i})
    if not wanted:
        return {}
    if dimension == "tutor":
        from tutortrack.people.models import TutorProfile

        return _names(
            TutorProfile, wanted, lambda t: t.full_name, ("first_name", "last_name", "display_name")
        )
    if dimension == "client":
        from tutortrack.people.models import Client

        return _names(Client, wanted, lambda c: c.display_name, ("display_name",))
    if dimension == "student":
        from tutortrack.people.models import Student

        return _names(
            Student,
            wanted,
            lambda s: f"{s.preferred_name or s.first_name} {s.last_name}".strip(),
            ("first_name", "last_name", "preferred_name"),
        )
    if dimension == "service":
        from tutortrack.catalogue.models import Service

        return _names(Service, wanted, lambda s: s.name, ("name",))
    if dimension == "subject":
        from tutortrack.catalogue.models import Subject

        return _names(Subject, wanted, lambda s: s.name, ("name",))
    if dimension == "level":
        from tutortrack.catalogue.models import Level

        return _names(Level, wanted, lambda s: s.name, ("name",))
    if dimension == "branch":
        from tutortrack.tenancy.models import Branch

        rows = Branch.objects.filter(pk__in=wanted).only("pk", "name")
        return {str(b.pk): b.name for b in rows}
    if dimension == "job":
        from tutortrack.jobs.models import Job

        return _names(
            Job, wanted, lambda j: f"{j.reference} {j.name}".strip(), ("reference", "name")
        )
    if dimension == "location":
        from tutortrack.catalogue.models import Location

        return _names(Location, wanted, lambda x: x.name, ("name",))
    if dimension == "pay_run":
        from tutortrack.payroll.models import PayRun

        return _names(PayRun, wanted, lambda r: r.number, ("number",))
    return {}
