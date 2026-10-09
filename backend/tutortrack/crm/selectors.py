"""CRM reads: activity timeline (FR-05-10) and global search (FR-05-11)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q
from django.db.models.functions import Greatest

from tutortrack.core.models import AuditEntry
from tutortrack.core.permissions import has_perm, scope_queryset

from .models import Document, Note, Task


@dataclass(frozen=True)
class TimelineItem:
    kind: str  # note | task | document | change
    id: str
    at: datetime
    title: str
    body: str
    actor_id: str | None


def visible_notes(user: Any) -> Any:
    qs = Note.objects.all()
    if not has_perm(user, "crm.note.view_staff_only"):
        qs = qs.exclude(visibility=Note.Visibility.STAFF)
    return qs


def timeline(
    user: Any, target_type: str, target_id: str, kinds: set[str] | None = None, limit: int = 200
) -> list[TimelineItem]:
    """Notes, tasks, documents and record changes for one record, newest first. Messages,
    lessons, invoices and payments join as their epics land (E13, E08, E10, E11)."""
    items: list[TimelineItem] = []
    want = kinds or {"note", "task", "document", "change"}
    if "note" in want and has_perm(user, "crm.note.view"):
        for n in visible_notes(user).filter(target_type=target_type, target_id=target_id)[:limit]:
            items.append(
                TimelineItem(
                    "note",
                    str(n.pk),
                    n.created_at,
                    "",
                    n.body,
                    str(n.created_by_id) if n.created_by_id else None,
                )
            )
    if "task" in want and has_perm(user, "crm.task.view"):
        for t in Task.objects.filter(target_type=target_type, target_id=target_id)[:limit]:
            items.append(
                TimelineItem(
                    "task",
                    str(t.pk),
                    t.created_at,
                    t.title,
                    t.status,
                    str(t.created_by_id) if t.created_by_id else None,
                )
            )
    if "document" in want and has_perm(user, "crm.document.view"):
        for d in Document.objects.filter(target_type=target_type, target_id=target_id)[:limit]:
            items.append(
                TimelineItem(
                    "document",
                    str(d.pk),
                    d.created_at,
                    d.title,
                    d.category,
                    str(d.created_by_id) if d.created_by_id else None,
                )
            )
    if "change" in want:
        for a in AuditEntry.objects.filter(object_type=target_type, object_id=target_id).exclude(
            action="read"
        )[:limit]:
            items.append(
                TimelineItem(
                    "change",
                    str(a.pk),
                    a.created_at,
                    a.action,
                    ", ".join(sorted(a.changes))[:300],
                    str(a.actor_id) if a.actor_id else None,
                )
            )
    items.sort(key=lambda i: i.at, reverse=True)
    return items[:limit]


@dataclass(frozen=True)
class SearchHit:
    type: str
    id: str
    title: str
    subtitle: str
    score: float
    client_id: str | None = None


def search(user: Any, q: str, limit: int = 20) -> list[SearchHit]:
    """⌘K search across people (jobs and invoices join with E07/E10). Trigram similarity
    plus substring match; every entity respects the viewer's permission and data scope."""
    from tutortrack.people.models import Client, Contact, Student, TutorProfile

    q = q.strip()
    if len(q) < 2:
        return []
    hits: list[SearchHit] = []

    def run(model: Any, perm: str, fields: list[str], make: Any) -> None:
        qs = scope_queryset(user, model.objects.all(), perm)
        if hasattr(model, "archived_at"):
            qs = qs.filter(archived_at__isnull=True)
        condition = Q()
        for f in fields:
            condition |= Q(**{f"{f}__icontains": q}) | Q(**{f"{f}__trigram_similar": q})
        scored = qs.annotate(
            score=Greatest(*[TrigramSimilarity(f, q) for f in fields])
            if len(fields) > 1
            else TrigramSimilarity(fields[0], q)
        )
        for obj in scored.filter(condition).order_by("-score")[:limit]:
            hits.append(make(obj))

    run(
        Client,
        "people.client.view",
        ["display_name"],
        lambda o: SearchHit(
            "client", str(o.pk), o.display_name, o.get_type_display(), float(o.score)
        ),
    )
    run(
        Contact,
        "people.contact.view",
        ["first_name", "last_name", "email", "phone"],
        lambda o: SearchHit(
            "contact", str(o.pk), o.full_name, o.email, float(o.score), str(o.client_id)
        ),
    )
    run(
        Student,
        "people.student.view",
        ["first_name", "last_name", "preferred_name"],
        lambda o: SearchHit(
            "student", str(o.pk), o.full_name, o.year_group, float(o.score), str(o.client_id)
        ),
    )
    run(
        TutorProfile,
        "people.tutor.view",
        ["first_name", "last_name", "email"],
        lambda o: SearchHit("tutor", str(o.pk), o.full_name, o.headline, float(o.score)),
    )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]
