"""FR-31-3 Inbox assistance over the E13 seam (``comms.selectors.thread_digest``):
suggested replies with account context (upcoming lessons, balance, cancellation policy),
intent classification with optional routing, and summaries of long threads.

Internal notes are never sent, and conversations flagged by safeguarding detection (E29)
get no AI assistance at all."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, DomainError, NotFound
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now

from .. import engine, prompts
from ..redaction import Redactor
from . import quoted

TRANSCRIPT_LIMIT = 40


def _thread(user: Any, thread_id: Any) -> Any:
    from tutortrack.comms.selectors import threads

    try:
        thread = threads(user).filter(pk=thread_id).first()
    except (ValueError, TypeError):
        thread = None
    if thread is None:
        raise NotFound()
    if thread.flagged:
        raise BusinessRuleViolation(
            _("This conversation is flagged for safeguarding, so AI assistance is off.")
        )
    return thread


def _transcript(thread: Any, redactor: Redactor) -> tuple[str, int]:
    from tutortrack.comms.selectors import thread_transcript

    if thread.client_id:
        redactor.value(thread.client.display_name, "CLIENT")
    if thread.tutor_id:
        redactor.person(thread.tutor.full_name, kind="TUTOR")
    if thread.contact_name:
        redactor.person(thread.contact_name, kind="CONTACT")
    lines = thread_transcript(thread, include_internal=False, limit=TRANSCRIPT_LIMIT)
    out = []
    for line in lines:
        if line.author:
            redactor.person(line.author, kind="PERSON")
        out.append(f"[{line.at:%Y-%m-%d %H:%M}] {line.direction} ({line.author or '?'}):")
        out.append(quoted(line.body[:4000]))
    return "\n".join(out), len(lines)


def _account_context(user: Any, thread: Any, redactor: Redactor) -> list[str]:
    """Facts for a reply, each only if the person may see it."""
    if not thread.client_id:
        return []
    lines: list[str] = []
    if has_perm(user, "scheduling.lesson.view"):
        from tutortrack.scheduling.selectors import lessons_in_range

        start = now()
        upcoming = list(
            lessons_in_range(
                user, start, start + timedelta(days=30), {"client": [thread.client_id]}
            )
            .exclude(status="cancelled")
            .order_by("start")[:5]
        )
        for lesson in upcoming:
            for attendee in lesson.attendees.all():
                redactor.person(attendee.student.full_name, kind="STUDENT")
            local = lesson.start.astimezone(ZoneInfo(lesson.timezone))
            lines.append(f"Upcoming lesson: {lesson.title}, {local:%a %d %b %H:%M}")
        if upcoming:
            from tutortrack.delivery import policies

            rules = policies.resolve(upcoming[0]).rules
            lines.append(
                "Cancellation policy: free with at least "
                f"{rules['free_window_hours']} hours' notice; later cancellations are charged "
                f"{rules['late_cancellation']['charge_percent']}%."
            )
    if has_perm(user, "billing.invoice.view"):
        from tutortrack.billing.selectors import balance_due

        lines.append(f"Balance due on issued invoices: {balance_due(thread.client_id):.2f}")
    return lines


def suggest_reply(user: Any, thread_id: Any) -> dict[str, Any]:
    thread = _thread(user, thread_id)
    if not has_perm(user, "comms.inbox.reply"):
        raise NotFound()
    redactor = Redactor()
    transcript, count = _transcript(thread, redactor)
    if not count:
        raise BusinessRuleViolation(_("There are no messages to reply to yet."))
    context = _account_context(user, thread, redactor)
    content = "\n".join(
        [
            f"Conversation: {thread.subject or '-'} (channel {thread.channel})",
            "",
            "Account context:",
            *(context or ["- none available"]),
            "",
            "Messages, oldest first:",
            transcript,
        ]
    )
    result = engine.run(prompts.INBOX_REPLY, user=user, content=content, redactor=redactor)
    return {"request": str(result.log.pk), "reply": result.text}


def summarise(user: Any, thread_id: Any) -> dict[str, Any]:
    thread = _thread(user, thread_id)
    redactor = Redactor()
    transcript, count = _transcript(thread, redactor)
    if not count:
        raise BusinessRuleViolation(_("There is nothing to summarise yet."))
    content = f"Conversation: {thread.subject or '-'}\n\nMessages, oldest first:\n{transcript}"
    result = engine.run(prompts.INBOX_SUMMARY, user=user, content=content, redactor=redactor)
    data = result.data or {}
    return {
        "request": str(result.log.pk),
        "summary": str(data.get("summary") or ""),
        "action_items": [str(a) for a in data.get("action_items") or []],
    }


def classify(user: Any, thread: Any) -> dict[str, Any]:
    """Classify, store the insight and (when configured) propose or apply routing."""
    from tutortrack.tenancy.settings_service import get_setting

    from .. import services

    redactor = Redactor()
    transcript, count = _transcript(thread, redactor)
    if not count:
        raise BusinessRuleViolation(_("There are no messages to classify yet."))
    content = f"Conversation: {thread.subject or '-'}\n\nMessages, oldest first:\n{transcript}"
    result = engine.run(prompts.INBOX_CLASSIFY, user=user, content=content, redactor=redactor)
    data = result.data or {}
    intent = str(data.get("intent") or "other")
    if intent not in prompts.INTENTS:
        intent = "other"
    insight = services.save_insight(
        thread,
        intent=intent,
        confidence=int(data.get("confidence") or 0),
        message_count=count,
        request=result.log,
    )
    routing = dict(get_setting("ai.inbox_routing") or {})
    proposal = None
    target = routing.get(intent)
    if target and thread.assignee_id is None and user is not None:
        try:
            proposal = services.propose(
                user,
                action="assign_thread",
                params={"thread_id": str(thread.pk), "assignee_id": target},
                feature="inbox",
                request=result.log,
            )
        except DomainError:
            proposal = None
    return {
        "request": str(result.log.pk),
        "intent": insight.intent,
        "confidence": insight.confidence,
        "reason": str(data.get("reason") or ""),
        "proposal": proposal,
    }


def classify_for(user: Any, thread_id: Any) -> dict[str, Any]:
    return classify(user, _thread(user, thread_id))


def auto_classify(thread_id: Any) -> str:
    """``message.received`` (Celery): classify without a person and, when routing maps
    the intent, assign the unassigned conversation (internal routing only)."""
    from tutortrack.comms import inbox
    from tutortrack.comms.models import Thread
    from tutortrack.identity.models import Membership
    from tutortrack.tenancy.settings_service import get_setting

    from .. import selectors, services

    if not get_setting("ai.inbox_auto_classify") or not selectors.is_enabled("inbox"):
        return "off"
    thread = Thread.objects.filter(pk=thread_id).first()
    if thread is None or thread.flagged:
        return "skipped"
    redactor = Redactor()
    transcript, count = _transcript(thread, redactor)
    if not count:
        return "empty"
    content = f"Conversation: {thread.subject or '-'}\n\nMessages, oldest first:\n{transcript}"
    result = engine.run(
        prompts.INBOX_CLASSIFY, user=None, content=content, redactor=redactor, check=False
    )
    data = result.data or {}
    intent = str(data.get("intent") or "other")
    intent = intent if intent in prompts.INTENTS else "other"
    services.save_insight(
        thread,
        intent=intent,
        confidence=int(data.get("confidence") or 0),
        message_count=count,
        request=result.log,
    )
    target = dict(get_setting("ai.inbox_routing") or {}).get(intent)
    if target and thread.assignee_id is None:
        membership = (
            Membership.objects.filter(user_id=target, status=Membership.Status.ACTIVE)
            .select_related("user")
            .first()
        )
        if membership is not None:
            try:
                inbox.assign(thread, membership.user)
            except DomainError:
                return intent
            return f"{intent}:assigned"
    return intent
