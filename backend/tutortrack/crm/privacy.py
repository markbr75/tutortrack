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

from .models import Document, Note, Signature, TaggedItem, Task

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
    signatures = [
        {
            "id": str(s.pk),
            "title": s.title,
            "signer_name": s.signer_name,
            "signer_email": s.signer_email,
            "signed_at": s.signed_at,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "content_sha256": s.content_sha256,
        }
        for s in Signature.objects.filter(_signed_by(person))
    ]
    return [
        Section("crm.notes", _("Notes"), notes),
        Section("crm.tasks", _("Tasks"), tasks),
        Section("crm.documents", _("Documents"), documents),
        Section("crm.signatures", _("Signatures"), signatures),
    ]


def _signed_by(person: Person) -> Q:
    """Signatures the person made (by email or as the tutor) or on documents about them."""
    q = Q(document__in=Document.objects.filter(_about(person)))
    if person.emails:
        q |= Q(signer_email__in=sorted(person.emails))
    if person.of("people.tutor"):
        q |= Q(tutor_id__in=person.of("people.tutor"))
    return q


def files(person: Person) -> list[Any]:
    about = _about(person)
    out = [d.file for d in Document.objects.filter(about).select_related("file")]
    out += [
        s.signed_file
        for s in Signature.objects.filter(_signed_by(person)).select_related("signed_file")
        if s.signed_file is not None
    ]
    for note in Note.objects.filter(about).prefetch_related("attachments"):
        out.extend(note.attachments.all())
    return out


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    about = _about(person)
    # Signatures stay as evidence (hash and time) but lose who signed and the signed copy.
    for signature in Signature.objects.filter(_signed_by(person)):
        if signature.signed_file_id:
            out.file_ids.append(str(signature.signed_file_id))
        out.anonymised += Signature.objects.filter(pk=signature.pk).update(
            signer=None,
            signer_name=_("Erased"),
            signer_email="",
            ip=None,
            user_agent="",
            statement="",
            signed_file=None,
        )
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
