"""Portal invitations follow a merged contact or student (FR-05-13): accepting an
invitation sent to the duplicate links the login to the survivor."""

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

INVITATIONS = GenericRef(
    "identity.Invitation",
    "target_type",
    "target_id",
    {"people.contact": ("people.contact",), "people.student": ("people.student",)},
)


def _count(ctx: MergeContext) -> list[Move]:
    n = generic_rows(INVITATIONS, ctx.subject_type, ctx.source_id).count()
    return moves(("identity.invitations", _l("Portal invitations"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    return moves(
        ("identity.invitations", _l("Portal invitations"), repoint_generic(INVITATIONS, ctx))
    )


register(
    MergeProvider(
        key="identity",
        label="Portal access",
        subject_types=frozenset({"people.contact", "people.student"}),
        count=_count,
        merge=_merge,
        generic=(INVITATIONS,),
        order=105,
    )
)
