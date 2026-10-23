"""Support chats, survey answers and usage events in DSARs, erasure and retention
(E30 Part 2 on the E29 provider registry).

Usage events are pseudonymous but still personal data: the person's pseudonym is
recomputed from their user id, so their events can be exported (counts) and deleted."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.context import require_organisation_id
from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    RetentionCategory,
    Section,
    register,
    register_retention,
)

from .analytics import pseudonym
from .models import GuidanceState, ProductEvent, SupportConversation, SupportMessage, SurveyResponse


def _actors(person: Person) -> list[str]:
    org = require_organisation_id()
    return [pseudonym(org, user_id) for user_id in person.of("identity.user")]


def export(person: Person) -> list[Section]:
    users = person.of("identity.user")
    if not users:
        return []
    messages = [
        {
            "id": str(m.pk),
            "conversation": m.conversation.subject,
            "body": m.body,
            "created_at": m.created_at,
        }
        for m in SupportMessage.objects.filter(author_id__in=users, from_support=False)
        .select_related("conversation")
        .order_by("created_at")
    ]
    surveys = [
        {
            "id": str(r.pk),
            "kind": r.kind,
            "score": r.score,
            "comment": r.comment,
            "created_at": r.created_at,
        }
        for r in SurveyResponse.objects.filter(user_id__in=users)
    ]
    events = ProductEvent.objects.filter(actor__in=_actors(person))
    usage = [{"id": "usage", "events": events.count()}] if events.exists() else []
    return [
        Section("support_chat", _("Messages to TutorTrack support"), messages),
        Section("surveys", _("Feedback surveys"), surveys),
        Section("product_usage", _("Product usage events (pseudonymous)"), usage),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    users = person.of("identity.user")
    if not users:
        return out
    for message in SupportMessage.objects.filter(author_id__in=users):
        message.body = ctx.scrub(message.body)
        message.author = None
        message.save(update_fields=["body", "author", "updated_at"])
        out.anonymised += 1
    for conversation in SupportConversation.objects.filter(
        Q(opened_by_id__in=users) | Q(assignee_id__in=users)
    ):
        conversation.subject = ctx.scrub(conversation.subject)
        if str(conversation.opened_by_id) in users:
            conversation.opened_by = None
        if str(conversation.assignee_id) in users:
            conversation.assignee = None
        conversation.save(update_fields=["subject", "opened_by", "assignee", "updated_at"])
        out.anonymised += 1
    out.anonymised += SurveyResponse.objects.filter(user_id__in=users).update(user=None, comment="")
    out.deleted += GuidanceState.objects.filter(user_id__in=users).delete()[0]
    out.deleted += ProductEvent.objects.filter(actor__in=_actors(person)).delete()[0]
    return out


def _purge_usage(cutoff: datetime, dry_run: bool, limit: int) -> int:
    old = ProductEvent.objects.filter(occurred_at__lt=cutoff)
    if dry_run:
        return old.count()
    ids = list(old.values_list("pk", flat=True)[:limit])
    if ids:
        ProductEvent.objects.filter(pk__in=ids).delete()
    return len(ids)


register(
    Provider(
        key="success", label=gettext_lazy("Support chat and feedback"), export=export, erase=erase
    )
)
register_retention(
    RetentionCategory(
        key="product_usage",
        label=gettext_lazy("Product usage events (pseudonymous)"),
        default_days=395,
        purge=_purge_usage,
        order=90,
    )
)
