"""Enquiries, form submissions and waitlists in DSARs, erasure and retention (E17 data,
E29 Part 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

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

from .models import Enquiry, FormSubmission, Proposal, WaitlistEntry


def _enquiries(person: Person) -> Q:
    return (
        Q(client_id__in=person.of("people.client"))
        | Q(contact_id__in=person.of("people.contact"))
        | Q(students__in=person.of("people.student"))
    )


def _submissions(person: Person) -> Q:
    q = Q(created_records__client__in=person.of("people.client")) | Q(
        pk__in=Enquiry.objects.filter(_enquiries(person)).values("submission_id")
    )
    for email in sorted(person.emails):
        q |= Q(data__email__iexact=email)
    return q


def export(person: Person) -> list[Section]:
    enquiries = [
        {
            "id": str(e.pk),
            "title": e.title,
            "status": e.status,
            "source": e.source,
            "subjects": e.subjects,
            "notes": e.notes,
            "created_at": e.created_at,
        }
        for e in Enquiry.objects.filter(_enquiries(person)).distinct()
    ]
    submissions = [
        {"id": str(s.pk), "form": s.form.name, "data": s.data, "submitted_at": s.created_at}
        for s in FormSubmission.objects.filter(_submissions(person))
        .select_related("form")
        .distinct()
    ]
    waitlist = [
        {
            "id": str(w.pk),
            "subject": w.subject,
            "level": w.level,
            "status": w.status,
            "notes": w.notes,
        }
        for w in WaitlistEntry.objects.filter(student_id__in=person.of("people.student"))
    ]
    proposals = [
        {
            "id": str(p.pk),
            "number": p.number,
            "title": p.title,
            "status": p.status,
            "accepted_name": p.accepted_name,
            "responded_at": p.responded_at,
            "decline_reason": p.decline_reason,
        }
        for p in Proposal.objects.filter(enquiry__in=Enquiry.objects.filter(_enquiries(person)))
    ]
    return [
        Section("leads.enquiries", _("Enquiries"), enquiries),
        Section("leads.proposals", _("Proposals"), proposals),
        Section("leads.form_submissions", _("Forms you submitted"), submissions),
        Section("leads.waitlist", _("Waiting lists"), waitlist),
    ]


def _uploads(person: Person) -> list[Any]:
    """G5a: files uploaded on public forms (enquiry attachments, registration uploads)."""
    from django.contrib.contenttypes.models import ContentType

    from tutortrack.core.models import StoredFile

    found: dict[str, Any] = {}
    for enquiry in Enquiry.objects.filter(_enquiries(person)).distinct():
        for stored in enquiry.attachments.all():
            found[str(stored.pk)] = stored
    submission_ids = [
        str(pk)
        for pk in FormSubmission.objects.filter(_submissions(person)).values_list("pk", flat=True)
    ]
    if submission_ids:
        for stored in StoredFile.objects.filter(
            owner_content_type=ContentType.objects.get_for_model(FormSubmission),
            owner_object_id__in=submission_ids,
        ):
            found[str(stored.pk)] = stored
    return list(found.values())


def files(person: Person) -> list[Any]:
    return _uploads(person)


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    out.file_ids += [str(f.pk) for f in _uploads(person)]
    for enquiry in Enquiry.objects.filter(_enquiries(person)).distinct():
        enquiry.attachments.clear()
        Enquiry.objects.filter(pk=enquiry.pk).update(
            title=ctx.scrub(enquiry.title),
            notes="",
            trial_feedback="",
            lost_note="",
            source_detail="",
            utm={},
        )
        out.anonymised += 1
    out.anonymised += FormSubmission.objects.filter(_submissions(person)).update(
        data={}, ip=None, user_agent="", utm={}
    )
    for proposal in Proposal.objects.filter(
        enquiry__in=Enquiry.objects.filter(_enquiries(person))
    ):  # E17-T09: the signature and free text; amounts stay (they were a quote)
        Proposal.objects.filter(pk=proposal.pk).update(
            title=ctx.scrub(proposal.title),
            introduction=ctx.scrub(proposal.introduction),
            schedule=ctx.scrub(proposal.schedule),
            accepted_name="",
            accepted_ip=None,
            decline_reason="",
        )
        out.anonymised += 1
    out.anonymised += WaitlistEntry.objects.filter(
        student_id__in=person.of("people.student")
    ).update(notes="", offer_details="")
    return out


def _purge_submissions(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """Form submissions that never became an enquiry or record (spam, abandoned)."""
    qs = FormSubmission.objects.filter(created_at__lt=cutoff, created_records={}).exclude(data={})
    if dry_run:
        return qs.count()
    ids = list(qs.values_list("pk", flat=True)[:limit])
    return FormSubmission.objects.filter(pk__in=ids).update(data={}, ip=None, user_agent="", utm={})


register(
    Provider(key="leads", label="Enquiries", export=export, files=files, erase=erase, order=34)
)
register_retention(
    RetentionCategory(
        key="unconverted_form_submissions",
        label=gettext_lazy("Form submissions that didn't become an enquiry"),
        default_days=365,
        purge=_purge_submissions,
        order=40,
    )
)
