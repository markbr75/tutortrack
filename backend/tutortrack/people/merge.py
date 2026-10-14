"""People's own references in a merge (FR-05-13): a client's contacts and students move to
the surviving family; contact and student links (primary/billing contact, the adult
learner's contact, portal logins, preferred tutors) follow the survivor."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from tutortrack.core import audit

from .merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    count,
    generic_rows,
    moves,
    register,
    repoint,
    repoint_generic,
)
from .models import Client, Contact, Student

SUBJECTS = ("people.client", "people.contact", "people.student")
# Durable processes (E32) about the record: the running workflow keeps its id, but the
# record page of the survivor lists it.
PROCESSES = GenericRef(
    "core.WorkflowLink", "subject_type", "subject_id", {s: (s, s.split(".")[1]) for s in SUBJECTS}
)


def _count(ctx: MergeContext) -> list[Move]:
    processes = generic_rows(PROCESSES, ctx.subject_type, ctx.source_id).count()
    if ctx.subject_type == "people.client":
        return moves(
            ("people.contacts", _l("Contacts"), count(Contact, "client", ctx)),
            ("people.students", _l("Students"), count(Student, "client", ctx)),
            ("people.processes", _l("Processes"), processes),
        )
    return moves(("people.processes", _l("Processes"), processes))


def _merge_client(ctx: MergeContext) -> list[Move]:
    source, target = ctx.source, ctx.target
    has_primary = Contact.objects.filter(client=target, is_primary=True).exists()
    contacts = list(Contact.objects.filter(client=source))
    for contact in contacts:
        with audit.track(contact, action="moved_by_merge"):
            contact.client = target
            if has_primary:
                contact.is_primary = False
            contact.save()
    students = list(Student.objects.filter(client=source))
    for student in students:
        with audit.track(student, action="moved_by_merge"):
            student.client = target
            student.save()
    fields = []
    if target.primary_contact_id is None and source.primary_contact_id is not None:
        target.primary_contact_id = source.primary_contact_id
        fields.append("primary_contact")
    if target.billing_contact_id is None and source.billing_contact_id is not None:
        target.billing_contact_id = source.billing_contact_id
        fields.append("billing_contact")
    if fields:
        target.save(update_fields=[*fields, "updated_at"])
    tombstones = repoint(Client, "merged_into", ctx)
    return moves(
        ("people.contacts", _l("Contacts"), len(contacts)),
        ("people.students", _l("Students"), len(students)),
        ("people.merged_records", _l("Earlier merges"), tombstones),
    )


def _move_login(ctx: MergeContext, model: type[Contact] | type[Student]) -> int:
    source, target = ctx.source, ctx.target
    if source.user_id is None:
        return 0
    if target.user_id is None:
        user_id = source.user_id
        model.objects.filter(pk=source.pk).update(user=None)
        model.objects.filter(pk=target.pk).update(user_id=user_id)
        target.user_id = user_id
        return 1
    # Both had a login: keep the survivor's; the other login no longer reaches anything.
    model.objects.filter(pk=source.pk).update(user=None)
    ctx.note(_("Both records had a portal login. The surviving record's login is kept."))
    return 0


def _merge_contact(ctx: MergeContext) -> list[Move]:
    source, target = ctx.source, ctx.target
    links = repoint(Client, "primary_contact", ctx) + repoint(Client, "billing_contact", ctx)
    links += repoint(Student, "contact", ctx)
    flags = {}
    if source.is_primary and not target.is_primary:
        flags["is_primary"] = True
    if source.is_bill_payer and not target.is_bill_payer:
        flags["is_bill_payer"] = True
    if flags:
        Contact.objects.filter(pk=target.pk).update(**flags)
    Contact.objects.filter(pk=source.pk).update(is_primary=False, is_bill_payer=False)
    login = _move_login(ctx, Contact)
    tombstones = repoint(Contact, "merged_into", ctx)
    return moves(
        ("people.contact_links", _l("Family and adult-learner links"), links),
        ("people.portal_login", _l("Portal login"), login),
        ("people.merged_records", _l("Earlier merges"), tombstones),
    )


def _merge_student(ctx: MergeContext) -> list[Move]:
    source, target = ctx.source, ctx.target
    tutors = 0
    for name in ("preferred_tutors", "excluded_tutors"):
        theirs = set(getattr(source, name).values_list("pk", flat=True))
        ours = set(getattr(target, name).values_list("pk", flat=True))
        if theirs - ours:
            getattr(target, name).add(*(theirs - ours))
            tutors += len(theirs - ours)
        getattr(source, name).clear()
    if target.contact_id is None and source.contact_id is not None:
        Student.objects.filter(pk=target.pk).update(contact_id=source.contact_id)
    Student.objects.filter(pk=source.pk).update(contact=None)
    login = _move_login(ctx, Student)
    tombstones = repoint(Student, "merged_into", ctx)
    return moves(
        ("people.tutor_preferences", _l("Preferred and excluded tutors"), tutors),
        ("people.portal_login", _l("Portal login"), login),
        ("people.merged_records", _l("Earlier merges"), tombstones),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    done = {
        "people.client": _merge_client,
        "people.contact": _merge_contact,
        "people.student": _merge_student,
    }[ctx.subject_type](ctx)
    processes = repoint_generic(PROCESSES, ctx)
    return [*done, *moves(("people.processes", _l("Processes"), processes))]


def _notes(ctx: MergeContext) -> list[str]:
    both = getattr(ctx.source, "user_id", None) and getattr(ctx.target, "user_id", None)
    if ctx.subject_type in {"people.contact", "people.student"} and both:
        return [_("Both records have a portal login. Only the surviving record's is kept.")]
    return []


register(
    MergeProvider(
        key="people",
        label="People",
        subject_types=frozenset(SUBJECTS),
        count=_count,
        merge=_merge,
        notes=_notes,
        generic=(PROCESSES,),
        order=10,
    )
)
