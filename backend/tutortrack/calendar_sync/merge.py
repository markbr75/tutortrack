"""Video meeting attendance follows a merged student (FR-05-13)."""

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

from .models import MeetingParticipantEvent


def _count(ctx: MergeContext) -> list[Move]:
    n = count(MeetingParticipantEvent, "student", ctx)
    return moves(("calendar_sync.attendance", _l("Video meeting attendance"), n))


def _merge(ctx: MergeContext) -> list[Move]:
    n = repoint(MeetingParticipantEvent, "student", ctx)
    return moves(("calendar_sync.attendance", _l("Video meeting attendance"), n))


register(
    MergeProvider(
        key="calendar_sync",
        label="Video meetings",
        subject_types=frozenset({"people.student"}),
        count=_count,
        merge=_merge,
        order=110,
    )
)
