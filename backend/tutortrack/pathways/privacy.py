"""Pathways in DSARs and erasure (E34 FR-34-1; ADR 0028). A tutor's runs are exported with
their answers; erasing the tutor removes answers, uploads and typed names from the steps
(the steps stay, so the business can see what was done and when)."""

from __future__ import annotations

from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import PathwayRun, PathwayStep


def _runs(person: Person) -> Any:
    return PathwayRun.objects.filter(tutor_id__in=person.of("people.tutor"))


def export(person: Person) -> list[Section]:
    rows = []
    for run in _runs(person).select_related("template").order_by("-started_at")[:500]:
        rows.append(
            {
                "id": str(run.pk),
                "pathway": run.template.name,
                "status": run.status,
                "started_at": run.started_at.isoformat(),
                "steps": [
                    {"name": s.name, "status": s.status, "result": s.result}
                    for s in run.steps.order_by("position")
                ],
            }
        )
    return [Section("pathways.runs", _("Pathways"), rows)]


def files(person: Person) -> list[Any]:
    from tutortrack.core.models import StoredFile

    steps = PathwayStep.objects.filter(run__in=_runs(person)).values_list("pk", flat=True)
    return list(
        StoredFile.objects.filter(
            owner_content_type=ContentType.objects.get_for_model(PathwayStep),
            owner_object_id__in=[str(pk) for pk in steps],
        )
    )


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    out.file_ids += [str(f.pk) for f in files(person)]
    for step in PathwayStep.objects.filter(run__in=_runs(person)).exclude(result={}):
        PathwayStep.objects.filter(pk=step.pk).update(result={"erased": True})
        out.anonymised += 1
    return out


register(
    Provider(
        key="pathways", label=gettext_lazy("Pathways"), export=export, files=files, erase=erase,
        order=31,
    )
)  # fmt: skip
