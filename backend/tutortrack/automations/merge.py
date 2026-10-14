"""Automation run history follows a merged client or student (FR-05-13), so "once per
record" automations don't run again for the survivor. A run both records had for the same
occurrence keeps the survivor's key; the merged record's copy is renamed."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    generic_rows,
    moves,
    register,
)

from .models import AutomationRun

RUNS = GenericRef(
    "automations.AutomationRun",
    "subject_type",
    "subject_id",
    {"people.client": ("client",), "people.student": ("student",)},
)


def _count(ctx: MergeContext) -> list[Move]:
    n = generic_rows(RUNS, ctx.subject_type, ctx.source_id).count()
    return moves(("automations.runs", _l("Automation runs"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    taken = set(
        generic_rows(RUNS, ctx.subject_type, ctx.target_id).values_list("automation_id", "run_key")
    )
    for run in generic_rows(RUNS, ctx.subject_type, ctx.source_id):
        if (run.automation_id, run.run_key) in taken:
            suffix = f"|merged:{ctx.source_id}"
            AutomationRun.objects.filter(pk=run.pk).update(
                run_key=run.run_key[: 200 - len(suffix)] + suffix
            )
    n = generic_rows(RUNS, ctx.subject_type, ctx.source_id).update(subject_id=ctx.target_id)
    return moves(("automations.runs", _l("Automation runs"), n))


register(
    MergeProvider(
        key="automations",
        label="Automations",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        generic=(RUNS,),
        order=120,
    )
)
