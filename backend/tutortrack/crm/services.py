"""CRM writes (E05 FR-05-5..9, 12)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

import nh3
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.models import StoredFile
from tutortrack.core.time import now

from . import events, targets
from .models import BulkJob, CustomFieldDefinition, Document, Note, SavedView, Tag, TaggedItem, Task

# Notes are rich text: keep simple formatting and links, drop everything else (FR-05-7).
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "span",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "span": {"data-mention"}}
MENTION = re.compile(r'data-mention="([0-9a-fA-F-]{36})"')


def sanitise(html: str) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"https", "http", "mailto"},
        link_rel="noopener noreferrer",
    )


def _target(target_type: str, target_id: str) -> None:
    target = targets.get(target_type)
    if target is None or not target.model._default_manager.filter(pk=target_id).exists():
        raise NotFound(_("Record not found."))


# --- custom fields ------------------------------------------------------------------------------


@transaction.atomic
def save_custom_field(
    definition: CustomFieldDefinition | None, **data: Any
) -> CustomFieldDefinition:
    if data.get("type") in {"select", "multi_select"} and not data.get(
        "options", definition.options if definition else []
    ):
        raise BusinessRuleViolation(_("Choice fields need options."))
    if definition is None:
        if targets.get(data.get("entity_type", "")) is None:
            raise BusinessRuleViolation(_("Unknown record type."))
        definition = CustomFieldDefinition.objects.create(**data)
        audit.record_create(definition)
        return definition
    data.pop("entity_type", None)
    data.pop("key", None)  # keys are stable once created (stored values reference them)
    with audit.track(definition):
        for k, v in data.items():
            setattr(definition, k, v)
        definition.save()
    return definition


# --- tags ---------------------------------------------------------------------------------------


@transaction.atomic
def apply_tag(
    tag: Tag, target_type: str, target_ids: Iterable[str], *, remove: bool = False
) -> int:
    if tag.entity_types and target_type not in tag.entity_types:
        raise BusinessRuleViolation(_("This tag isn't used for this kind of record."))
    ids = [str(i) for i in target_ids]
    target = targets.get(target_type)
    if target is None:
        raise BusinessRuleViolation(_("Unknown record type."))
    existing_ids = {
        str(pk)
        for pk in target.model._default_manager.filter(pk__in=ids).values_list("pk", flat=True)
    }
    count = 0
    for target_id in ids:
        if target_id not in existing_ids:
            continue
        if remove:
            count += TaggedItem.objects.filter(
                tag=tag, target_type=target_type, target_id=target_id
            ).delete()[0]
        else:
            _item, created = TaggedItem.objects.get_or_create(
                tag=tag, target_type=target_type, target_id=target_id
            )
            count += int(created)
    if count:
        audit.record(
            tag,
            "untag" if remove else "tag",
            {"target_type": [None, target_type], "count": [None, count]},
        )
    return count


def tags_for(target_type: str, target_ids: Iterable[str]) -> dict[str, list[Tag]]:
    out: dict[str, list[Tag]] = {}
    for item in TaggedItem.objects.filter(
        target_type=target_type, target_id__in=list(target_ids)
    ).select_related("tag"):
        out.setdefault(item.target_id, []).append(item.tag)
    return out


# --- notes --------------------------------------------------------------------------------------


@transaction.atomic
def create_note(
    *,
    target_type: str,
    target_id: str,
    body: str,
    visibility: str = Note.Visibility.STAFF,
    pinned: bool = False,
    attachments: Iterable[Any] = (),
) -> Note:
    _target(target_type, target_id)
    clean = sanitise(body)
    if not clean.strip():
        raise BusinessRuleViolation(
            _("The note is empty."), extra={"errors": {"body": [_("Write something.")]}}
        )
    from tutortrack.identity.models import Membership

    mentioned = sorted(set(MENTION.findall(clean)))
    members = {
        str(u)
        for u in Membership.objects.filter(user_id__in=mentioned, status="active").values_list(
            "user_id", flat=True
        )
    }
    note = Note.objects.create(
        target_type=target_type,
        target_id=str(target_id),
        body=clean,
        visibility=visibility,
        pinned=pinned,
        mentions=[m for m in mentioned if m in members],
    )
    files = [_clean_file(f) for f in attachments]
    if files:
        note.attachments.set(files)
    audit.record_create(note)
    publish(
        events.NoteCreated(
            subject_id=note.pk,
            target_type=target_type,
            target_id=str(target_id),
            visibility=visibility,
            mentions=note.mentions,
        )
    )
    return note


@transaction.atomic
def update_note(note: Note, **changes: Any) -> Note:
    if "body" in changes:
        changes["body"] = sanitise(changes["body"])
    with audit.track(note):
        for k, v in changes.items():
            setattr(note, k, v)
        note.save()
    return note


# --- tasks --------------------------------------------------------------------------------------


@transaction.atomic
def create_task(*, title: str, target_type: str = "", target_id: str = "", **fields: Any) -> Task:
    if target_type:
        _target(target_type, target_id)
    task = Task.objects.create(
        title=title, target_type=target_type, target_id=str(target_id or ""), **fields
    )
    audit.record_create(task)
    publish(
        events.TaskCreated(
            subject_id=task.pk,
            assignee_id=str(task.assignee_id) if task.assignee_id else None,
            due_at=task.due_at.isoformat() if task.due_at else None,
        )
    )
    return task


@transaction.atomic
def update_task(task: Task, **changes: Any) -> Task:
    old_assignee = task.assignee_id
    status = changes.pop("status", None)
    with audit.track(task):
        for k, v in changes.items():
            setattr(task, k, v)
        if status is not None and status != task.status:
            task.status = status
            task.completed_at = now() if status == Task.Status.DONE else None
        task.save()
    if task.assignee_id and task.assignee_id != old_assignee:
        publish(events.TaskAssigned(subject_id=task.pk, assignee_id=str(task.assignee_id)))
    if status == Task.Status.DONE:
        publish(events.TaskCompleted(subject_id=task.pk))
    return task


# --- documents ----------------------------------------------------------------------------------


def _clean_file(file: Any) -> StoredFile:
    stored = file if isinstance(file, StoredFile) else StoredFile.objects.filter(pk=file).first()
    if stored is None or stored.status != StoredFile.Status.UPLOADED:
        raise BusinessRuleViolation(_("Upload the file first."))
    if stored.scan_status not in {
        StoredFile.ScanStatus.CLEAN,
        StoredFile.ScanStatus.SKIPPED,
        StoredFile.ScanStatus.PENDING,
    }:
        raise BusinessRuleViolation(_("This file failed the virus scan."))
    return stored


@transaction.atomic
def attach_document(
    *,
    target_type: str,
    target_id: str,
    file: Any,
    title: str = "",
    category: str = Document.Category.OTHER,
    **fields: Any,
) -> Document:
    _target(target_type, target_id)
    stored = _clean_file(file)
    document = Document.objects.create(
        target_type=target_type,
        target_id=str(target_id),
        file=stored,
        title=title or stored.filename,
        category=category,
        **fields,
    )
    audit.record_create(document)
    publish(
        events.DocumentUploaded(
            subject_id=document.pk,
            target_type=target_type,
            target_id=str(target_id),
            category=category,
        )
    )
    return document


# --- saved views --------------------------------------------------------------------------------


def save_view(view: SavedView | None, *, owner: Any, **data: Any) -> SavedView:
    if view is None:
        return SavedView.objects.create(owner=owner, **data)
    if view.owner_id != owner.pk:
        raise BusinessRuleViolation(_("Only the owner can change this view."))
    for k, v in data.items():
        setattr(view, k, v)
    view.save()
    return view


# --- bulk actions -------------------------------------------------------------------------------

BULK_ACTIONS = {
    "people.client": {"tag", "untag", "set_status", "assign_manager", "archive"},
    "people.student": {"tag", "untag", "set_status", "archive"},
    "people.contact": {"tag", "untag"},
    "people.tutor": {"tag", "untag", "set_status"},
}


@transaction.atomic
def start_bulk_job(
    *, entity_type: str, action: str, target_ids: list[str], params: dict[str, Any], user: Any
) -> BulkJob:
    if action not in BULK_ACTIONS.get(entity_type, set()):
        raise BusinessRuleViolation(_("This action isn't available for these records."))
    visible = targets.visible_ids(user, entity_type, [str(i) for i in target_ids])
    job = BulkJob.objects.create(
        entity_type=entity_type,
        action=action,
        params=params,
        target_ids=[i for i in map(str, target_ids) if i in visible],
        total=len(visible),
        requested_by=user,
    )
    from .tasks import run_bulk_job

    transaction.on_commit(
        lambda: run_bulk_job.delay(job_id=str(job.pk), organisation_id=str(job.organisation_id))
    )
    return job
