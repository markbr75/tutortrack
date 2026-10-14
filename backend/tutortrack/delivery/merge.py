"""Makeup credits, lesson feedback and client cancellation policies follow a merged
client, contact or student (FR-05-13). When both clients have their own cancellation
policy, the survivor's stays active and the merged client's is kept as an inactive
version (policy snapshots on past cancellations stay explainable)."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    clashes,
    count,
    generic_rows,
    moves,
    register,
    repoint,
    repoint_generic,
)

from .models import LessonFeedback, MakeupCredit

POLICIES = GenericRef(
    "delivery.CancellationPolicy", "scope_type", "scope_id", {"people.client": ("client",)}
)


def _policies(ctx: MergeContext) -> int:
    ours = generic_rows(POLICIES, ctx.subject_type, ctx.target_id).filter(active=True)
    if ours.exists():
        generic_rows(POLICIES, ctx.subject_type, ctx.source_id).update(active=False)
    return repoint_generic(POLICIES, ctx)


def _check(ctx: MergeContext) -> list[str]:
    if ctx.subject_type == "people.student" and (
        clashes(MakeupCredit, "student", ctx, ["source_lesson_id"])
        or clashes(LessonFeedback, "student", ctx, ["lesson_id"])
    ):
        return [_("Both students have makeup credits or feedback for the same lesson.")]
    return []


def _count(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.contact":
        return moves(
            ("delivery.feedback", _l("Lesson feedback"), count(LessonFeedback, "contact", ctx))
        )
    name = "client" if ctx.subject_type == "people.client" else "student"
    policies = generic_rows(POLICIES, ctx.subject_type, ctx.source_id).count()
    return moves(
        ("delivery.makeup_credits", _l("Makeup credits"), count(MakeupCredit, name, ctx)),
        ("delivery.feedback", _l("Lesson feedback"), count(LessonFeedback, name, ctx)),
        ("delivery.policies", _l("Cancellation policies"), policies),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.contact":
        return moves(
            ("delivery.feedback", _l("Lesson feedback"), repoint(LessonFeedback, "contact", ctx))
        )
    name = "client" if ctx.subject_type == "people.client" else "student"
    return moves(
        ("delivery.makeup_credits", _l("Makeup credits"), repoint(MakeupCredit, name, ctx)),
        ("delivery.feedback", _l("Lesson feedback"), repoint(LessonFeedback, name, ctx)),
        ("delivery.policies", _l("Cancellation policies"), _policies(ctx)),
    )


register(
    MergeProvider(
        key="delivery",
        label="Lesson delivery",
        subject_types=frozenset({"people.client", "people.contact", "people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        generic=(POLICIES,),
        order=40,
    )
)
