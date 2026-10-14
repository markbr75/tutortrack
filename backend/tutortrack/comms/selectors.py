"""Communications reads: the message log and record timelines (FR-13-4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.core.time import now

from .models import (
    Broadcast,
    CannedReply,
    InAppNotification,
    Message,
    PhoneNumber,
    PushSubscription,
    Segment,
    SenderDomain,
    Thread,
    ThreadMessage,
    ThreadParticipant,
    WhatsAppTemplate,
)


def messages(user: Any) -> QuerySet[Message]:
    if not has_perm(user, "comms.message.view_log"):
        return Message.objects.none()
    return Message.objects.exclude(channel="in_app")


def message_timeline(user: Any, target_type: str, target_id: str, limit: int) -> list[Any]:
    """Messages sent about a record, for its activity timeline (E05)."""
    from tutortrack.crm.selectors import TimelineItem

    rows = messages(user).filter(target_type=target_type, target_id=target_id)[:limit]
    return [
        TimelineItem(
            "message",
            str(m.pk),
            m.sent_at or m.created_at,
            m.subject or m.body[:80],
            f"{m.channel} · {m.status} · {m.recipient_name}",
            None,
        )
        for m in rows
    ]


def notifications_for(user: Any) -> QuerySet[InAppNotification]:
    return InAppNotification.objects.filter(user=user)


def push_subscriptions_for(user: Any) -> QuerySet[PushSubscription]:
    """Your own devices only (E16-T09): nobody else can see or push to them."""
    return PushSubscription.objects.filter(user=user)


# --- Phase 2: broadcasts (E13-T10) --------------------------------------------------------------


def broadcasts(user: Any) -> QuerySet[Broadcast]:
    return scope_queryset(
        user,
        Broadcast.objects.select_related("segment", "whatsapp_template"),
        "comms.broadcast.view",
    )


def segments_for(user: Any) -> QuerySet[Segment]:
    return scope_queryset(user, Segment.objects.all(), "comms.broadcast.view")


def may_open_broadcast_file(user: Any, stored: Any) -> bool:
    return has_perm(user, "comms.broadcast.view")


# --- Phase 2: the inbox (E13-T11) ---------------------------------------------------------------
# These reads are also the seam for E31 (suggested replies, intent, thread summaries):
# ``thread_transcript`` and ``thread_digest`` return plain data, never models.

BOXES = ("open", "mine", "unassigned", "snoozed", "closed", "flagged", "all")


def open_q() -> Q:
    """Open, or snoozed until a time that has passed (snoozes end by themselves)."""
    return Q(status=Thread.Status.OPEN) | Q(status=Thread.Status.SNOOZED, snoozed_until__lte=now())


def effective_status(thread: Thread) -> str:
    if (
        thread.status == Thread.Status.SNOOZED
        and thread.snoozed_until
        and thread.snoozed_until <= now()
    ):
        return Thread.Status.OPEN
    return thread.status


def threads(user: Any) -> QuerySet[Thread]:
    qs = Thread.objects.select_related("client", "tutor", "assignee")
    return scope_queryset(user, qs, "comms.inbox.view")


def filter_box(qs: QuerySet[Thread], box: str, user: Any) -> QuerySet[Thread]:
    if box == "mine":
        return qs.filter(open_q(), assignee=user)
    if box == "unassigned":
        return qs.filter(open_q(), assignee__isnull=True)
    if box == "snoozed":
        return qs.filter(status=Thread.Status.SNOOZED, snoozed_until__gt=now())
    if box == "closed":
        return qs.filter(status=Thread.Status.CLOSED)
    if box == "flagged":
        return qs.filter(flagged=True)
    if box == "open":
        return qs.filter(open_q())
    return qs


def sla_due_at(thread: Thread) -> datetime | None:
    if thread.awaiting_reply_since is None or effective_status(thread) == Thread.Status.CLOSED:
        return None
    from tutortrack.tenancy.settings_service import get_setting

    return thread.awaiting_reply_since + timedelta(hours=int(get_setting("comms.inbox_sla_hours")))


def thread_messages(thread: Thread, *, include_internal: bool) -> QuerySet[ThreadMessage]:
    qs = thread.messages.select_related("message").order_by("created_at", "id")
    return qs if include_internal else qs.exclude(direction=ThreadMessage.Direction.INTERNAL)


def unread_count(thread: Thread, user: Any, *, include_internal: bool = True) -> int:
    """Messages from others since ``user`` last read the thread (notes excluded for
    families and tutors)."""
    read = (
        ThreadParticipant.objects.filter(thread=thread, user=user)
        .values_list("last_read_at", flat=True)
        .first()
    )
    qs = thread.messages.exclude(author_user=user)
    if not include_internal:
        qs = qs.exclude(direction=ThreadMessage.Direction.INTERNAL)
    if read:
        qs = qs.filter(created_at__gt=read)
    return qs.count()


@dataclass(frozen=True)
class TranscriptLine:
    at: datetime
    direction: str  # inbound | outbound | internal
    channel: str
    author: str
    body: str


@dataclass(frozen=True)
class ThreadDigest:
    id: str
    subject: str
    kind: str
    status: str
    party: str
    channel: str
    awaiting_reply_since: datetime | None
    sla_due_at: datetime | None
    lines: list[TranscriptLine]


def thread_transcript(
    thread: Thread, *, include_internal: bool = True, limit: int = 50
) -> list[TranscriptLine]:
    """The latest ``limit`` entries, oldest first, as plain lines."""
    rows = list(
        thread_messages(thread, include_internal=include_internal).order_by("-created_at", "-id")[
            :limit
        ]
    )
    return [
        TranscriptLine(m.created_at, m.direction, m.channel, m.author_name, m.body)
        for m in reversed(rows)
    ]


def thread_digest(thread: Thread, *, limit: int = 50) -> ThreadDigest:
    party = (
        (thread.client.display_name if thread.client_id and thread.client else "")
        or (thread.tutor.full_name if thread.tutor_id and thread.tutor else "")
        or thread.contact_name
    )
    return ThreadDigest(
        id=str(thread.pk),
        subject=thread.subject,
        kind=thread.kind,
        status=effective_status(thread),
        party=party,
        channel=thread.channel,
        awaiting_reply_since=thread.awaiting_reply_since,
        sla_due_at=sla_due_at(thread),
        lines=thread_transcript(thread, limit=limit),
    )


def portal_threads(household: Any) -> QuerySet[Thread]:
    """A family's conversations (with the business, and with tutors). Students see only
    the ones they take part in."""
    kinds = [Thread.Kind.CLIENT, Thread.Kind.TUTOR_FAMILY]
    qs = Thread.objects.filter(client_id__in=household.client_ids, kind__in=kinds)
    if not household.is_client:
        mine = ThreadParticipant.objects.filter(
            person_type="student", person_id__in=[str(i) for i in household.student_ids]
        ).values("thread_id")
        qs = qs.filter(pk__in=mine)
    return qs.select_related("tutor", "client")


def tutor_threads(tutor: Any) -> QuerySet[Thread]:
    return Thread.objects.filter(
        tutor=tutor, kind__in=[Thread.Kind.TUTOR, Thread.Kind.TUTOR_FAMILY]
    ).select_related("client", "tutor")


def may_open_thread_file(user: Any, stored: Any) -> bool:
    """Staff who can read the inbox, or a participant of a thread whose message (not an
    internal note) carries the file."""
    entry = ThreadMessage.objects.filter(pk=stored.owner_object_id).select_related("thread").first()
    if entry is None:
        return False
    if has_perm(user, "comms.inbox.view") and threads(user).filter(pk=entry.thread_id).exists():
        return True
    if entry.direction == ThreadMessage.Direction.INTERNAL:
        return False
    return ThreadParticipant.objects.filter(thread_id=entry.thread_id, user=user).exists()


def canned_replies(user: Any) -> QuerySet[CannedReply]:
    if not has_perm(user, "comms.inbox.reply"):
        return CannedReply.objects.none()
    return CannedReply.objects.all()


# --- Phase 2: channels and senders (E13-T12) ----------------------------------------------------


def sender_domains(user: Any) -> QuerySet[SenderDomain]:
    if not has_perm(user, "comms.channels.manage"):
        return SenderDomain.objects.none()
    return SenderDomain.objects.all()


def phone_numbers(user: Any) -> QuerySet[PhoneNumber]:
    if not has_perm(user, "comms.channels.manage"):
        return PhoneNumber.objects.none()
    return PhoneNumber.objects.all()


def whatsapp_templates(user: Any) -> QuerySet[WhatsAppTemplate]:
    if not (has_perm(user, "comms.channels.manage") or has_perm(user, "comms.broadcast.send")):
        return WhatsAppTemplate.objects.none()
    return WhatsAppTemplate.objects.all()
