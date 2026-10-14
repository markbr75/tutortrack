"""Enquiries, waiting-list entries and proposals follow a merged client, contact or
student (FR-05-13)."""

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

from .models import Enquiry, Proposal, WaitlistEntry


def _count(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.client":
        return moves(("leads.enquiries", _l("Enquiries"), count(Enquiry, "client", ctx)))
    if ctx.subject_type == "people.contact":
        return moves(
            ("leads.enquiries", _l("Enquiries"), count(Enquiry, "contact", ctx)),
            ("leads.proposals", _l("Proposals"), count(Proposal, "contact", ctx)),
        )
    return moves(
        ("leads.enquiries", _l("Enquiries"), Enquiry.objects.filter(students=ctx.source).count()),
        ("leads.waitlist", _l("Waiting-list entries"), count(WaitlistEntry, "student", ctx)),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    if ctx.subject_type == "people.client":
        return moves(("leads.enquiries", _l("Enquiries"), repoint(Enquiry, "client", ctx)))
    if ctx.subject_type == "people.contact":
        return moves(
            ("leads.enquiries", _l("Enquiries"), repoint(Enquiry, "contact", ctx)),
            ("leads.proposals", _l("Proposals"), repoint(Proposal, "contact", ctx)),
        )
    enquiries = list(Enquiry.objects.filter(students=ctx.source))
    for enquiry in enquiries:
        enquiry.students.remove(ctx.source)
        enquiry.students.add(ctx.target)
    return moves(
        ("leads.enquiries", _l("Enquiries"), len(enquiries)),
        ("leads.waitlist", _l("Waiting-list entries"), repoint(WaitlistEntry, "student", ctx)),
    )


register(
    MergeProvider(
        key="leads",
        label="Enquiries",
        subject_types=frozenset({"people.client", "people.contact", "people.student"}),
        count=_count,
        merge=_merge,
        order=70,
    )
)
