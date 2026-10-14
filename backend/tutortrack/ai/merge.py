"""The AI-assisted marker follows a merged client, contact or student (FR-05-13)."""

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
ASSISTS = GenericRef(
    "ai.AIAssist", "subject_type", "subject_id", {s: (s, s.split(".")[1]) for s in SUBJECTS}
)


def _count(ctx: MergeContext) -> list[Move]:
    n = generic_rows(ASSISTS, ctx.subject_type, ctx.source_id).count()
    return moves(("ai.assists", _l("AI-assisted records"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    return moves(("ai.assists", _l("AI-assisted records"), repoint_generic(ASSISTS, ctx)))


register(
    MergeProvider(
        key="ai",
        label="AI assistant",
        subject_types=frozenset(SUBJECTS),
        count=_count,
        merge=_merge,
        generic=(ASSISTS,),
        order=130,
    )
)
