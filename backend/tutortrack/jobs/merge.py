"""Jobs follow a merged client or student (FR-05-13). A job both students are on keeps
the survivor's link (its rate override wins)."""

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
    repoint_unique,
)

from .models import Job, JobStudent


def _count(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.client":
        return moves(
            ("jobs.jobs", _l("Jobs"), count(Job, "client", ctx)),
            ("jobs.paid_jobs", _l("Jobs they pay for"), count(Job, "bill_to", ctx)),
        )
    return moves(("jobs.job_students", _l("Jobs"), count(JobStudent, "student", ctx)))


def _merge(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.client":
        return moves(
            ("jobs.jobs", _l("Jobs"), repoint(Job, "client", ctx)),
            ("jobs.paid_jobs", _l("Jobs they pay for"), repoint(Job, "bill_to", ctx)),
        )
    moved, _dropped = repoint_unique(JobStudent, "student", ctx, ["job_id"])
    return moves(("jobs.job_students", _l("Jobs"), moved))


register(
    MergeProvider(
        key="jobs",
        label="Jobs",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        order=20,
    )
)
