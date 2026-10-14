"""Tutor expenses recharged to a client follow a merged client (FR-05-13)."""

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

from .models import Expense


def _count(ctx: MergeContext) -> list[Move]:
    return moves(("payroll.expenses", _l("Tutor expenses"), count(Expense, "client", ctx)))


def _merge(ctx: MergeContext) -> list[Move]:
    return moves(("payroll.expenses", _l("Tutor expenses"), repoint(Expense, "client", ctx)))


register(
    MergeProvider(
        key="payroll",
        label="Payroll",
        subject_types=frozenset({"people.client"}),
        count=_count,
        merge=_merge,
        order=65,
    )
)
