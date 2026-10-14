"""Reporting facts follow a merged client or student (FR-05-13), so revenue and lesson
reports count the merged family once."""

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

from .models import FactCharge, FactPayment


def _count(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.student":
        return moves(("reporting.facts", _l("Report figures"), count(FactCharge, "student", ctx)))
    n = count(FactCharge, "client", ctx) + count(FactPayment, "client", ctx)
    return moves(("reporting.facts", _l("Report figures"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.student":
        n = repoint(FactCharge, "student", ctx)
    else:
        n = repoint(FactCharge, "client", ctx) + repoint(FactPayment, "client", ctx)
    return moves(("reporting.facts", _l("Report figures"), n))


register(
    MergeProvider(
        key="reporting",
        label="Reporting",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        order=200,
    )
)
