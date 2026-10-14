"""Lessons follow a merged client or student (FR-05-13): attendances (with their charges'
amounts untouched), booking holds and calendar feed links. Two students booked on the
same lesson can't be merged: one booking has to be cancelled first."""

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

from .models import BookingHold, LessonAttendee

FEEDS = GenericRef(
    "scheduling.ICalFeedToken",
    "kind",
    "subject_id",
    {"people.client": ("client",), "people.student": ("student",)},
)


def _field(ctx: MergeContext) -> str:
    return "client" if ctx.subject_type == "people.client" else "student"


def _check(ctx: MergeContext) -> list[str]:
    if ctx.subject_type != "people.student":
        return []
    if clashes(LessonAttendee, "student", ctx, ["lesson_id"]):
        return [_("Both students are booked on the same lesson. Cancel one booking first.")]
    return []


def _count(ctx: MergeContext) -> list[Move]:
    name = _field(ctx)
    return moves(
        ("scheduling.attendances", _l("Lessons"), count(LessonAttendee, name, ctx)),
        ("scheduling.booking_holds", _l("Booking holds"), count(BookingHold, name, ctx)),
        (
            "scheduling.calendar_feeds",
            _l("Calendar feeds"),
            generic_rows(FEEDS, ctx.subject_type, ctx.source_id).count(),
        ),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    name = _field(ctx)
    return moves(
        ("scheduling.attendances", _l("Lessons"), repoint(LessonAttendee, name, ctx)),
        ("scheduling.booking_holds", _l("Booking holds"), repoint(BookingHold, name, ctx)),
        ("scheduling.calendar_feeds", _l("Calendar feeds"), repoint_generic(FEEDS, ctx)),
    )


register(
    MergeProvider(
        key="scheduling",
        label="Lessons",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        generic=(FEEDS,),
        order=30,
    )
)
