"""Writes for the AI assistant: feature settings, feedback, the AI-assisted flag,
proposals (create, confirm, discard) and inbox insights. All audited."""

from __future__ import annotations

import difflib
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, DomainError, NotFound
from tutortrack.core.time import now

from . import actions
from .events import AIFeatureUpdated, AIProposalExecuted, ThreadIntentClassified
from .models import (
    AIAssist,
    AIFeatureSetting,
    AIFeedback,
    AIProposal,
    AIRequestLog,
    Feature,
    ThreadInsight,
)

PROPOSAL_TTL = timedelta(hours=1)


@transaction.atomic
def update_feature(feature: str, **changes: Any) -> AIFeatureSetting:
    if feature not in Feature.values:
        raise NotFound(_("Unknown AI feature."))
    unknown = set(changes) - {"enabled", "tone", "language"}
    if unknown:
        raise BusinessRuleViolation(f"Unknown AI setting fields: {', '.join(sorted(unknown))}")
    row, created = AIFeatureSetting.objects.select_for_update().get_or_create(feature=feature)
    if created:
        audit.record_create(row)
    with audit.track(row):
        for key, value in changes.items():
            setattr(row, key, value)
        row.save()
    publish(AIFeatureUpdated(subject_id=row.pk, feature=feature, enabled=row.enabled))
    return row


def _request(user: Any, request_id: Any) -> AIRequestLog:
    try:
        log = AIRequestLog.objects.filter(pk=request_id, user_id=user.pk).first()
    except (ValueError, TypeError):
        log = None
    if log is None:
        raise NotFound(_("AI response not found."))
    return log


def edit_stats(draft: str, final: str) -> dict[str, int]:
    """How much a person changed a draft (no text is kept)."""
    matcher = difflib.SequenceMatcher(a=draft, b=final, autojunk=False)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return {
        "similarity_percent": round(matcher.ratio() * 100),
        "chars_added": added,
        "chars_removed": removed,
    }


@transaction.atomic
def record_feedback(
    user: Any,
    request_id: Any,
    *,
    rating: str = "",
    comment: str = "",
    draft_text: str | None = None,
    final_text: str | None = None,
) -> AIFeedback:
    log = _request(user, request_id)
    values: dict[str, Any] = {}
    if rating:
        if rating not in AIFeedback.Rating.values:
            raise BusinessRuleViolation(_("Rate the response up or down."))
        values["rating"] = rating
    if comment:
        values["comment"] = comment.strip()[:500]
    if draft_text is not None and final_text is not None:
        values.update(edit_stats(draft_text[:20_000], final_text[:20_000]))
    feedback, created = AIFeedback.objects.get_or_create(request=log, user=user, defaults=values)
    if created:
        audit.record_create(feedback)
    elif values:
        with audit.track(feedback):
            for key, value in values.items():
                setattr(feedback, key, value)
            feedback.save()
    return feedback


@transaction.atomic
def mark_applied(user: Any, request_id: Any, *, subject_type: str, subject_id: str) -> AIAssist:
    """A person used the draft on a record: it is now AI-assisted (FR-31-1)."""
    log = _request(user, request_id)
    assist, created = AIAssist.objects.get_or_create(
        request=log,
        subject_type=subject_type[:40],
        subject_id=str(subject_id)[:64],
        defaults={"user": user, "feature": log.feature},
    )
    if created:
        audit.record_create(assist)
    return assist


# --- proposals ------------------------------------------------------------------------------------


def propose(
    user: Any, *, action: str, params: dict[str, Any], feature: str, request: Any = None
) -> AIProposal:
    """Validate and store a proposal (checks the person could do it); nothing runs."""
    summary = actions.get(action).describe(user, params)
    proposal = AIProposal.objects.create(
        user=user,
        request=request,
        feature=feature,
        action=action,
        params=params,
        summary=summary[:300],
    )
    audit.record_create(proposal)
    return proposal


def attach_request(proposals: list[AIProposal], log: AIRequestLog) -> None:
    AIProposal.objects.filter(pk__in=[p.pk for p in proposals]).update(request=log)
    for proposal in proposals:
        proposal.request = log


def _open(user: Any, proposal_id: Any) -> AIProposal:
    try:
        proposal = (
            AIProposal.objects.select_for_update().filter(pk=proposal_id, user_id=user.pk).first()
        )
    except (ValueError, TypeError):
        proposal = None
    if proposal is None:
        raise NotFound(_("Proposal not found."))
    if proposal.status != AIProposal.Status.PROPOSED:
        raise Conflict(_("This proposal was already dealt with."))
    if proposal.created_at < now() - PROPOSAL_TTL:
        raise Conflict(_("This proposal is out of date; ask again."))
    return proposal


def confirm(user: Any, proposal_id: Any) -> AIProposal:
    """Run a proposal through the owning app's services, with the person's permissions.
    A failure is recorded on the proposal and re-raised (the action rolls back)."""
    with transaction.atomic():
        proposal = _open(user, proposal_id)
        action = actions.get(proposal.action)
        try:
            with transaction.atomic():
                result = action.execute(user, dict(proposal.params))
        except DomainError as exc:
            failed_with = exc
        else:
            with audit.track(proposal, action="execute"):
                proposal.status = AIProposal.Status.EXECUTED
                proposal.result = result
                proposal.decided_at = now()
                proposal.save()
            publish(
                AIProposalExecuted(
                    subject_id=proposal.pk, action=proposal.action, feature=proposal.feature
                )
            )
            return proposal
        with audit.track(proposal, action="execute"):
            proposal.status = AIProposal.Status.FAILED
            proposal.error = str(failed_with.detail)[:300]
            proposal.decided_at = now()
            proposal.save()
    raise failed_with


@transaction.atomic
def discard(user: Any, proposal_id: Any) -> AIProposal:
    proposal = _open(user, proposal_id)
    with audit.track(proposal, action="discard"):
        proposal.status = AIProposal.Status.DISCARDED
        proposal.decided_at = now()
        proposal.save()
    return proposal


# --- inbox insights -------------------------------------------------------------------------------


@transaction.atomic
def save_insight(
    thread: Any, *, intent: str, confidence: int, message_count: int, request: Any
) -> ThreadInsight:
    insight, _created = ThreadInsight.objects.update_or_create(
        thread=thread,
        defaults={
            "intent": intent,
            "confidence": max(0, min(100, int(confidence))),
            "message_count": message_count,
            "request": request,
            "classified_at": now(),
        },
    )
    audit.record(insight, "classify", {"intent": [None, intent]})
    publish(
        ThreadIntentClassified(subject_id=thread.pk, intent=intent, confidence=insight.confidence),
        branch_id=thread.branch_id,
    )
    return insight
