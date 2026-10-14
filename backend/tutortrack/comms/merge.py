"""Communications follow a merged client, contact or student (FR-05-13): sent messages
(recipient and timeline record), inbox threads, their participants and authors,
notification preferences and broadcast recipients. Where both records have a row that
must be unique (a preference for the same category, a place in the same thread), the
survivor's is kept. Suppressions and opt-outs are kept per address, so they still apply."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    count,
    generic_rows,
    moves,
    register,
    repoint,
)

from .models import Message, Thread

PERSON = {"people.contact": ("contact",), "people.student": ("student",)}
RECORD = {s: (s,) for s in ("people.client", "people.contact", "people.student")}
RECIPIENTS = GenericRef("comms.Message", "recipient_type", "recipient_id", PERSON)
TIMELINE = GenericRef("comms.Message", "target_type", "target_id", RECORD)
RELATED = GenericRef("comms.Message", "related_type", "related_id", RECORD)
PREFERENCES = GenericRef("comms.CommunicationPreference", "person_type", "person_id", PERSON)
DIGESTS = GenericRef("comms.DigestPreference", "person_type", "person_id", PERSON)
BROADCASTS = GenericRef("comms.BroadcastRecipient", "recipient_type", "recipient_id", PERSON)
PARTICIPANTS = GenericRef("comms.ThreadParticipant", "person_type", "person_id", PERSON)
AUTHORS = GenericRef("comms.ThreadMessage", "author_type", "author_id", PERSON)
GENERIC = (
    RECIPIENTS,
    TIMELINE,
    RELATED,
    PREFERENCES,
    DIGESTS,
    BROADCASTS,
    PARTICIPANTS,
    AUTHORS,
)


def _repoint_unique(ref: GenericRef, ctx: MergeContext, together: tuple[str, ...]) -> int:
    """Re-point a generic reference, dropping the duplicate's rows that would clash."""
    target_rows = generic_rows(ref, ctx.subject_type, ctx.target_id)
    taken = set(target_rows.values_list(*together))
    rows = generic_rows(ref, ctx.subject_type, ctx.source_id)
    for row in rows:
        if tuple(getattr(row, f) for f in together) in taken:
            row.delete()
    return generic_rows(ref, ctx.subject_type, ctx.source_id).update(
        **{ref.id_field: ctx.target_id}
    )


def _n(ref: GenericRef, ctx: MergeContext) -> int:
    return generic_rows(ref, ctx.subject_type, ctx.source_id).count()


def _count(ctx: MergeContext) -> list[Move]:
    messages = Message.objects.filter(
        pk__in=generic_rows(RECIPIENTS, ctx.subject_type, ctx.source_id).values("pk")
    ) | Message.objects.filter(
        pk__in=generic_rows(TIMELINE, ctx.subject_type, ctx.source_id).values("pk")
    )
    threads = count(Thread, "client", ctx) if ctx.subject_type == "people.client" else 0
    return moves(
        ("comms.messages", _l("Messages"), messages.distinct().count()),
        ("comms.threads", _l("Inbox conversations"), threads + _n(PARTICIPANTS, ctx)),
        (
            "comms.preferences",
            _l("Notification preferences"),
            _n(PREFERENCES, ctx) + _n(DIGESTS, ctx),
        ),
        ("comms.broadcasts", _l("Broadcast recipients"), _n(BROADCASTS, ctx)),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    def plain(ref: GenericRef) -> int:
        return generic_rows(ref, ctx.subject_type, ctx.source_id).update(
            **{ref.id_field: ctx.target_id}
        )

    messages = plain(RECIPIENTS) + plain(TIMELINE) + plain(RELATED)
    threads = repoint(Thread, "client", ctx) if ctx.subject_type == "people.client" else 0
    threads += _repoint_unique(PARTICIPANTS, ctx, ("thread_id", "person_type"))
    plain(AUTHORS)
    preferences = _repoint_unique(PREFERENCES, ctx, ("category", "person_type"))
    preferences += _repoint_unique(DIGESTS, ctx, ("kind", "person_type"))  # G4
    broadcasts = _repoint_unique(BROADCASTS, ctx, ("broadcast_id", "recipient_type"))
    return moves(
        ("comms.messages", _l("Messages"), messages),
        ("comms.threads", _l("Inbox conversations"), threads),
        ("comms.preferences", _l("Notification preferences"), preferences),
        ("comms.broadcasts", _l("Broadcast recipients"), broadcasts),
    )


register(
    MergeProvider(
        key="comms",
        label="Communications",
        subject_types=frozenset({"people.client", "people.contact", "people.student"}),
        count=_count,
        merge=_merge,
        generic=GENERIC,
        order=80,
    )
)
