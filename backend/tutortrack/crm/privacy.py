"""Notes, tasks, documents and tags about a person in DSARs and erasure (E29 Part 2).

Erasure deletes them (they are about the person, not financial records) and releases the
attached files for deletion."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import Document, Note, TaggedItem, Task

TARGET_TYPES = {
    "people.client": ["people.client"],
    "people.contact": ["people.contact"],
    "people.student": ["people.student"],
    "people.tutor": ["people.tutor", "people.tutorprofile"],
}


def _about(person: Person) -> Q:
    q = Q(pk__in=[])
    for subject_type, target_types in TARGET_TYPES.items():
        ids = person.of(subject_type)
        if ids:
            q |= Q(target_type__in=target_types, target_id__in=ids)
    return q


def export(person: Person) -> list[Section]:
    about = _about(person)
    notes = [
        {
            "id": str(n.pk),
            "about": n.target_type,
            "body": n.body,
            "visibility": n.visibility,
            "created_at": n.created_at,
        }
        for n in Note.objects.filter(about)
    ]
    tasks = [
        {
            "id": str(t.pk),
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "due_at": t.due_at,
        }
        for t in Task.objects.filter(about)
    ]
    documents = [
        {
            "id": str(d.pk),
            "title": d.title,
            "category": d.category,
            "file": str(d.file_id),
            "created_at": d.created_at,
        }
        for d in Document.objects.filter(about)
    ]
    return [
        Section("crm.notes", _("Notes"), notes),
        Section("crm.tasks", _("Tasks"), tasks),
        Section("crm.documents", _("Documents"), documents),
    ]


def files(person: Person) -> list[Any]:
    about = _about(person)
    out = [d.file for d in Document.objects.filter(about).select_related("file")]
    for note in Note.objects.filter(about).prefetch_related("attachments"):
        out.extend(note.attachments.all())
    return out


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    about = _about(person)
    for note in Note.objects.filter(about).prefetch_related("attachments"):
        out.file_ids += [str(f.pk) for f in note.attachments.all()]
        note.attachments.clear()
    for document in Document.objects.filter(about):
        out.file_ids.append(str(document.file_id))
    out.deleted += Note.objects.filter(about).delete()[0]
    out.deleted += Document.objects.filter(about).delete()[0]
    out.deleted += Task.objects.filter(about).delete()[0]
    out.deleted += TaggedItem.objects.filter(about).delete()[0]
    # Notes about other records (e.g. the household) that mention the person by name.
    for note in Note.objects.filter(
        target_type__in=["people.client"],
        target_id__in=sorted(person.context.get("people.client", set())),
    ):
        scrubbed = ctx.scrub(note.body)
        if scrubbed != note.body:
            Note.objects.filter(pk=note.pk).update(body=scrubbed)
            out.anonymised += 1
    return out


register(Provider(key="crm", label="Notes and documents", export=export, files=files, erase=erase))
