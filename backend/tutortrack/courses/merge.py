"""Class enrolments, makeup bookings and rollover offers follow a merged client or
student (FR-05-13). Two students with live places in the same class (or booked into the
same makeup session) can't be merged until one place is withdrawn."""

from __future__ import annotations

from django.utils.translation import gettext as _
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

from .models import Enrolment, MakeupBooking, RolloverOffer

LIVE = ("pending_payment", "enrolled", "trial")
RECORDS = (
    ("courses.enrolments", _l("Class enrolments"), Enrolment),
    ("courses.makeups", _l("Makeup bookings"), MakeupBooking),
    ("courses.rollover_offers", _l("Rollover offers"), RolloverOffer),
)


def _check(ctx: MergeContext) -> list[str]:
    if ctx.subject_type != "people.student":
        return []
    live = Enrolment.objects.filter(status__in=LIVE)
    ours = set(live.filter(student=ctx.target).values_list("group_class_id", flat=True))
    theirs = set(live.filter(student=ctx.source).values_list("group_class_id", flat=True))
    booked = MakeupBooking.objects.filter(status="booked")
    sessions = set(booked.filter(student=ctx.target).values_list("session_id", flat=True))
    other = set(booked.filter(student=ctx.source).values_list("session_id", flat=True))
    if ours & theirs or sessions & other:
        return [_("Both students have a place in the same class. Withdraw one place first.")]
    return []


def _field(ctx: MergeContext) -> str:
    return "client" if ctx.subject_type == "people.client" else "student"


def _count(ctx: MergeContext) -> list[Move]:
    return moves(*[(k, label, count(m, _field(ctx), ctx)) for k, label, m in RECORDS])


def _merge(ctx: MergeContext) -> list[Move]:
    return moves(*[(k, label, repoint(m, _field(ctx), ctx)) for k, label, m in RECORDS])


register(
    MergeProvider(
        key="courses",
        label="Classes and courses",
        subject_types=frozenset({"people.client", "people.student"}),
        count=_count,
        merge=_merge,
        check=_check,
        order=85,
    )
)
