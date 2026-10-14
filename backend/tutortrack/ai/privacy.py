"""The AI assistant in DSARs and erasure (E31 data, E29 Part 2).

Prompts and answers are never stored (only a hash of the redacted input), so what holds
personal data is what people typed or confirmed: feedback comments and command-bar
proposals ("Move Sam's Thursday maths to 5pm"). Usage logs carry no content and stay for
credit accounting."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import AIFeedback, AIProposal, AIRequestLog


def export(person: Person) -> list[Section]:
    users = person.of("identity.user")
    requests = [
        {
            "id": str(r.pk),
            "feature": r.feature,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in AIRequestLog.objects.filter(user_id__in=users)
    ]
    feedback = [
        {"id": str(f.pk), "rating": f.rating, "comment": f.comment, "created_at": f.created_at}
        for f in AIFeedback.objects.filter(user_id__in=users)
    ]
    proposals = [
        {
            "id": str(p.pk),
            "action": p.action,
            "summary": p.summary,
            "status": p.status,
            "created_at": p.created_at,
        }
        for p in AIProposal.objects.filter(user_id__in=users)
    ]
    return [
        Section("ai.requests", _("AI assistant use"), requests),
        Section("ai.feedback", _("AI feedback"), feedback),
        Section("ai.proposals", _("AI suggested actions"), proposals),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    users = person.of("identity.user")
    out.anonymised += (
        AIFeedback.objects.filter(user_id__in=users).exclude(comment="").update(comment="")
    )
    # Proposals anyone made can name the person (staff about a student, say).
    for row in AIProposal.objects.values("pk", "summary", "params", "result", "error"):
        changes: dict[str, Any] = {
            "summary": ctx.scrub(row["summary"]),
            "params": ctx.scrub_json(row["params"]),
            "result": ctx.scrub_json(row["result"]),
            "error": ctx.scrub(row["error"]),
        }
        if any(changes[k] != row[k] for k in changes):
            AIProposal.objects.filter(pk=row["pk"]).update(**changes)
            out.anonymised += 1
    out.retained += AIRequestLog.objects.filter(user_id__in=users).count()
    return out


register(Provider(key="ai", label="AI assistant", export=export, erase=erase, order=40))
