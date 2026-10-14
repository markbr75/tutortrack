"""Guardian-managed logins follow a merged student (FR-05-13). If both students have one,
the merge waits until the family removes one (only one login can belong to a student)."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import MergeContext, MergeProvider, Move, count, moves, register
from tutortrack.people.merging import repoint as _repoint

from .models import StudentLogin


def _check(ctx: MergeContext) -> list[str]:
    both = (
        StudentLogin.objects.filter(student_id=ctx.source.pk).exists()
        and StudentLogin.objects.filter(student_id=ctx.target.pk).exists()
    )
    return (
        [_("Both students have a login set up by their guardian. Remove one first.")]
        if both
        else []
    )


def _count(ctx: MergeContext) -> list[Move]:
    return moves(
        ("portal.student_logins", _l("Student logins"), count(StudentLogin, "student", ctx))
    )


def _merge(ctx: MergeContext) -> list[Move]:
    moved = _repoint(StudentLogin, "student", ctx)
    return moves(("portal.student_logins", _l("Student logins"), moved))


register(
    MergeProvider(
        key="portal",
        label="Portal",
        subject_types=frozenset({"people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        order=96,
    )
)
