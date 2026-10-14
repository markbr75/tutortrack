"""Learning records follow a merged student (FR-05-13): shared resources and activity,
homework, topic mastery, goals, assessment results, progress reports, loans and quiz
attempts. Mastery is recalculated from evidence, so where both students have a level for
the same topic the survivor's is kept; two pieces of homework, assessment results or
progress reports for the same thing block the merge (someone must decide which counts)."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    MergeContext,
    MergeProvider,
    Move,
    clashes,
    count,
    moves,
    register,
    repoint,
    repoint_unique,
)

from .models import (
    AssessmentResult,
    Goal,
    HomeworkAssignment,
    Loan,
    ProgressReport,
    QuizAttempt,
    ResourceActivity,
    ResourceShare,
    TopicMastery,
)

RECORDS = (
    ("learning.homework", _l("Homework"), HomeworkAssignment),
    ("learning.goals", _l("Goals"), Goal),
    ("learning.assessments", _l("Assessment results"), AssessmentResult),
    ("learning.progress_reports", _l("Progress reports"), ProgressReport),
    ("learning.resources", _l("Shared resources"), ResourceShare),
    ("learning.activity", _l("Resource activity"), ResourceActivity),
    ("learning.loans", _l("Loans"), Loan),
    ("learning.quizzes", _l("Quiz attempts"), QuizAttempt),
)


def _check(ctx: MergeContext) -> list[str]:
    if (
        clashes(HomeworkAssignment, "student", ctx, ["homework_id"])
        or clashes(AssessmentResult, "student", ctx, ["assessment_id"])
        or clashes(ProgressReport, "student", ctx, ["period_start", "period_end"])
    ):
        return [
            _(
                "Both students have homework, an assessment result or a progress report for "
                "the same thing. Remove one first."
            )
        ]
    return []


def _count(ctx: MergeContext) -> list[Move]:
    return moves(
        *[(k, label, count(m, "student", ctx)) for k, label, m in RECORDS],
        ("learning.mastery", _l("Topic mastery"), count(TopicMastery, "student", ctx)),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    mastery, _dropped = repoint_unique(TopicMastery, "student", ctx, ["node_id"])
    return moves(
        *[(k, label, repoint(m, "student", ctx)) for k, label, m in RECORDS],
        ("learning.mastery", _l("Topic mastery"), mastery),
    )


register(
    MergeProvider(
        key="learning",
        label="Learning",
        subject_types=frozenset({"people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        order=95,
    )
)
