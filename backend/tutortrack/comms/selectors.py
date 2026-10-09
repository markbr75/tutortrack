"""Communications reads: the message log and record timelines (FR-13-4)."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import has_perm

from .models import InAppNotification, Message


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
