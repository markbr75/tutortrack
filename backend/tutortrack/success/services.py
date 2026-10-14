"""Writes for help, tours, the setup checklist, surveys and support chat (E30 Part 2).
Every function runs in the organisation's tenant context; platform staff answer support
conversations through the same functions (``platform_admin.services`` enters the context)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from . import events
from .models import (
    GuidanceState,
    SetupChecklist,
    SetupChecklistItem,
    SupportConversation,
    SupportMessage,
    SurveyResponse,
)

TOUR_KEY_MAX = 40
NPS_SNOOZE_AFTER_ANSWER = timedelta(days=90)
NPS_SNOOZE_AFTER_DISMISS = timedelta(days=30)
SCORE_RANGES: dict[str, tuple[int, int]] = {"nps": (0, 10), "csat": (1, 5)}


# --- guidance (tours, "What's new") -------------------------------------------------------------


def guidance(user: Any) -> GuidanceState:
    state, _created = GuidanceState.objects.get_or_create(user=user)
    return state


@transaction.atomic
def finish_tour(user: Any, key: str, *, dismissed: bool = False) -> GuidanceState:
    key = key.strip()[:TOUR_KEY_MAX]
    if not key:
        raise BusinessRuleViolation(_("Name the tour."))
    state = GuidanceState.objects.select_for_update().get(pk=guidance(user).pk)
    field = "dismissed_tours" if dismissed else "completed_tours"
    values = list(getattr(state, field))
    if key not in values:
        values.append(key)
        setattr(state, field, values)
        state.save(update_fields=[field, "updated_at"])
    return state


@transaction.atomic
def restart_tour(user: Any, key: str) -> GuidanceState:
    state = GuidanceState.objects.select_for_update().get(pk=guidance(user).pk)
    state.completed_tours = [k for k in state.completed_tours if k != key]
    state.dismissed_tours = [k for k in state.dismissed_tours if k != key]
    state.save(update_fields=["completed_tours", "dismissed_tours", "updated_at"])
    return state


def mark_changelog_seen(user: Any) -> GuidanceState:
    state = guidance(user)
    state.changelog_seen_at = now()
    state.save(update_fields=["changelog_seen_at", "updated_at"])
    return state


# --- setup checklist (FR-30-5) ------------------------------------------------------------------


def checklist() -> SetupChecklist:
    state, created = SetupChecklist.objects.get_or_create()
    if created:
        backfill_checklist()
        state.refresh_from_db()
    return state


def _existing_progress() -> dict[str, bool]:
    """Steps already done before the checklist existed (organisations from before E30
    Part 2, imports, demo data). Read-only checks against the owning apps' data."""
    from tutortrack.billing.models import Invoice
    from tutortrack.catalogue.models import Service
    from tutortrack.payments.models import ProviderAccount
    from tutortrack.people.models import Student
    from tutortrack.scheduling.models import Lesson

    Key = SetupChecklistItem.Key
    return {
        Key.SERVICE: Service.objects.exists(),
        Key.STUDENT: Student.objects.exists(),
        Key.LESSON: Lesson.objects.exists(),
        Key.PAYMENTS: ProviderAccount.objects.filter(
            Q(status__in=["active", "restricted"]) | Q(connected_at__isnull=False)
        )
        .exclude(status="disconnected")
        .exists(),
        Key.INVOICE: Invoice.objects.exclude(issued_at__isnull=True).exists(),
    }


def backfill_checklist() -> list[str]:
    done = []
    for key, present in _existing_progress().items():
        if present and complete_item(key, source=SetupChecklistItem.Source.EXISTING):
            done.append(str(key))
    return done


@transaction.atomic
def complete_item(key: str, *, source: str = SetupChecklistItem.Source.EVENT) -> bool:
    """Tick one step (idempotent); returns whether it was newly ticked."""
    if key not in SetupChecklistItem.Key.values:
        raise BusinessRuleViolation(_("Unknown checklist step."))
    state, _created = SetupChecklist.objects.get_or_create()
    try:
        with transaction.atomic():
            item = SetupChecklistItem.objects.create(key=key, completed_at=now(), source=source)
    except IntegrityError:
        return False
    audit.record_create(item)
    publish(events.SetupItemCompleted(subject_id=state.pk, key=key, source=source))
    done = set(SetupChecklistItem.objects.values_list("key", flat=True))
    if done >= set(SetupChecklistItem.Key.values) and state.completed_at is None:
        with audit.track(state, action="setup_checklist_completed"):
            state.completed_at = now()
            state.save(update_fields=["completed_at", "updated_at"])
        publish(events.SetupChecklistCompleted(subject_id=state.pk))
    return True


@transaction.atomic
def dismiss_checklist(*, dismissed: bool) -> SetupChecklist:
    state = checklist()
    with audit.track(state, action="setup_checklist_dismissed" if dismissed else "update"):
        state.dismissed_at = now() if dismissed else None
        state.save(update_fields=["dismissed_at", "updated_at"])
    return state


# --- surveys (FR-30-6) --------------------------------------------------------------------------


@transaction.atomic
def answer_survey(
    user: Any,
    *,
    kind: str,
    score: int | None,
    comment: str = "",
    context: str = "",
    role: str = "",
) -> SurveyResponse:
    """Record an NPS (0-10) or CSAT (1-5) answer; ``score=None`` dismisses an NPS prompt.
    Either way the NPS prompt rests (90 days after an answer, 30 after a dismissal)."""
    if kind not in SCORE_RANGES:
        raise BusinessRuleViolation(_("Unknown survey."))
    low, high = SCORE_RANGES[kind]
    if score is None and kind != SurveyResponse.Kind.NPS:
        raise BusinessRuleViolation(_("Choose a score."))
    if score is not None and not low <= score <= high:
        raise BusinessRuleViolation(
            _("Choose a score from %(low)s to %(high)s.") % {"low": low, "high": high}
        )
    if kind == SurveyResponse.Kind.CSAT and context.startswith("support:"):
        conversation_id = context.split(":", 1)[1]
        conversation = SupportConversation.objects.filter(pk=conversation_id).first()
        if conversation is None or conversation.opened_by_id != user.pk:
            raise BusinessRuleViolation(_("Only the person who asked can rate this chat."))
        if SurveyResponse.objects.filter(kind=kind, context=context).exists():
            raise BusinessRuleViolation(_("This chat is already rated."))
    response = SurveyResponse.objects.create(
        user=user,
        kind=kind,
        score=score,
        comment=comment.strip()[:2000],
        context=context[:80],
        role=role[:20],
    )
    audit.record(response, "create", {"kind": [None, kind], "score": [None, score]})
    if kind == SurveyResponse.Kind.NPS:
        state = guidance(user)
        rest = NPS_SNOOZE_AFTER_ANSWER if score is not None else NPS_SNOOZE_AFTER_DISMISS
        state.nps_snoozed_until = now() + rest
        state.save(update_fields=["nps_snoozed_until", "updated_at"])
    publish(events.SurveyAnswered(subject_id=response.pk, kind=kind, score=score))
    return response


# --- support chat (FR-30-5) ---------------------------------------------------------------------


def _clean_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise BusinessRuleViolation(_("Write a message."))
    if len(text) > 5000:
        raise BusinessRuleViolation(_("Keep messages under 5,000 characters."))
    return text


@transaction.atomic
def open_conversation(
    user: Any, *, body: str, subject: str = "", page: str = ""
) -> SupportConversation:
    text = _clean_body(body)
    subject = (subject or "").strip()[:200] or text.splitlines()[0][:200]
    conversation = SupportConversation.objects.create(
        subject=subject, opened_by=user, page=page[:200], last_message_at=now()
    )
    audit.record_create(conversation)
    SupportMessage.objects.create(conversation=conversation, author=user, body=text)
    publish(events.SupportConversationOpened(subject_id=conversation.pk))
    return conversation


@transaction.atomic
def post_message(
    conversation: SupportConversation, user: Any, *, body: str, from_support: bool = False
) -> SupportMessage:
    text = _clean_body(body)
    conversation = SupportConversation.objects.select_for_update().get(pk=conversation.pk)
    message = SupportMessage.objects.create(
        conversation=conversation, author=user, body=text, from_support=from_support
    )
    audit.record(
        message, "create", {"conversation": [None, str(conversation.pk)]}, object_repr="message"
    )
    S = SupportConversation.Status
    conversation.status = S.ANSWERED if from_support else S.OPEN
    conversation.closed_at = None
    conversation.last_message_at = message.created_at
    conversation.customer_unread = from_support
    conversation.support_unread = not from_support
    if from_support and conversation.assignee_id is None:
        conversation.assignee = user
    conversation.save()
    publish(
        events.SupportConversationReplied(subject_id=conversation.pk, from_support=from_support)
    )
    if from_support:  # G6: the person hears by email and push, not only in the chat
        from .notifications import notify_reply

        notify_reply(conversation, message)
    return message


@transaction.atomic
def close_conversation(conversation: SupportConversation) -> SupportConversation:
    if conversation.status == SupportConversation.Status.CLOSED:
        return conversation
    with audit.track(conversation, action="close"):
        conversation.status = SupportConversation.Status.CLOSED
        conversation.closed_at = now()
        conversation.support_unread = False
        conversation.save()
    publish(events.SupportConversationClosed(subject_id=conversation.pk))
    return conversation


def mark_read(conversation: SupportConversation, *, by_support: bool) -> SupportConversation:
    field = "support_unread" if by_support else "customer_unread"
    if getattr(conversation, field):
        setattr(conversation, field, False)
        conversation.save(update_fields=[field, "updated_at"])
    return conversation


@transaction.atomic
def assign(conversation: SupportConversation, staff: Any) -> SupportConversation:
    with audit.track(conversation, action="assign"):
        conversation.assignee = staff
        conversation.save(update_fields=["assignee", "updated_at"])
    return conversation
