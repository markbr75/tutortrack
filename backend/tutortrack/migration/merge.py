"""Import links follow a merged client, contact or student (FR-05-13): a re-import from
the old system updates the survivor instead of creating the duplicate again."""

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
    repoint_generic,
)

SUBJECTS = ("people.client", "people.contact", "people.student")
SAME = {s: (s,) for s in SUBJECTS}
EXTERNAL = GenericRef("migration.ExternalRef", "target_type", "target_id", SAME)
ROWS = GenericRef("migration.ImportRow", "target_type", "target_id", SAME)


def _count(ctx: MergeContext) -> list[Move]:
    n = generic_rows(EXTERNAL, ctx.subject_type, ctx.source_id).count()
    return moves(("migration.external_refs", _l("Links to the old system"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    repoint_generic(ROWS, ctx)
    n = repoint_generic(EXTERNAL, ctx)
    return moves(("migration.external_refs", _l("Links to the old system"), n))


register(
    MergeProvider(
        key="migration",
        label="Imports",
        subject_types=frozenset(SUBJECTS),
        count=_count,
        merge=_merge,
        generic=(EXTERNAL, ROWS),
        order=140,
    )
)
