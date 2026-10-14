"""Tutor shortlists shared with a family follow a merged contact (FR-05-13)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    count,
    moves,
    register,
    repoint,
)

from .models import ShortlistShare


def _count(ctx: MergeContext) -> list[Move]:
    return moves(
        ("matching.shortlists", _l("Shared shortlists"), count(ShortlistShare, "contact", ctx))
    )


def _merge(ctx: MergeContext) -> list[Move]:
    return moves(
        ("matching.shortlists", _l("Shared shortlists"), repoint(ShortlistShare, "contact", ctx))
    )


register(
    MergeProvider(
        key="matching",
        label="Matching",
        subject_types=frozenset({"people.contact"}),
        count=_count,
        merge=_merge,
        order=75,
    )
)
