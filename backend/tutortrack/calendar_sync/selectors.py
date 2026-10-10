"""Calendar sync reads (E22-T02). ``tutor_busy`` is registered as a scheduling busy source,
so conflicts, free slots and matching see busy time from connected calendars without
scheduling depending on this app."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from django.db.models import QuerySet

from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.integrations.models import IntegrationConnection

from .models import ExternalBusyBlock, OnlineMeeting

LIVE = (IntegrationConnection.Status.ACTIVE, IntegrationConnection.Status.ERROR)


def tutor_busy(
    tutor_ids: list[str], start: datetime, end: datetime
) -> dict[str, list[tuple[datetime, datetime]]]:
    from tutortrack.people.models import TutorProfile

    users = dict(
        TutorProfile.objects.filter(pk__in=tutor_ids, membership__isnull=False).values_list(
            "membership__user_id", "pk"
        )
    )
    out: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    if not users:
        return out
    rows = ExternalBusyBlock.objects.filter(
        user_id__in=list(users), start__lt=end, end__gt=start, connection__status__in=LIVE
    ).values_list("user_id", "start", "end")
    for user_id, b_start, b_end in rows:
        out[str(users[user_id])].append((b_start, b_end))
    return out


def busy_blocks(user: Any) -> QuerySet[Any]:
    """Own blocks; everyone's for people who manage others' availability or integrations."""
    qs = ExternalBusyBlock.objects.filter(connection__status__in=LIVE)
    if has_perm(user, "scheduling.availability.manage_others") or has_perm(
        user, "integrations.view"
    ):
        return qs
    return qs.filter(user=user)


def meetings(user: Any) -> QuerySet[Any]:
    """Meetings of lessons the user can see."""
    from tutortrack.scheduling.models import Lesson

    lessons = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.view")
    return OnlineMeeting.objects.filter(lesson__in=lessons).select_related("lesson")
