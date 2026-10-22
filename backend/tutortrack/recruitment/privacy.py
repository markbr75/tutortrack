"""Tutor applications and compliance records in DSARs, erasure and retention (E18 data,
E29 Part 2).

Applicants are data subjects in their own right (``recruitment.application``). Rejected
and withdrawn applications are erased after ``rejected_applications`` (6 months by
default). Compliance records (DBS and right-to-work checks) are kept: employers must be
able to show the checks were made; their certificate numbers are cleared."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy import subjects
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

from .models import ComplianceRecord, Interview, ReferenceRequest, Scorecard, TutorApplication


def _exists(subject_id: str) -> bool:
    return TutorApplication.objects.filter(pk=subject_id).exists()


def _label(subject_id: str) -> str:
    app = TutorApplication.objects.filter(pk=subject_id).first()
    return f"{app.first_name} {app.last_name}".strip() if app else ""


subjects.register("recruitment.application", _exists, _label)


def _applications(person: Person) -> Any:
    from django.db.models import Q

    return TutorApplication.objects.filter(
        Q(pk__in=person.of("recruitment.application")) | Q(tutor_id__in=person.of("people.tutor"))
    )


def expand(person: Person) -> None:
    for app in _applications(person):
        person.add("recruitment.application", app.pk)
        person.add("people.tutor", app.tutor_id)
        person.add_terms(
            names=[f"{app.first_name} {app.last_name}"], emails=[app.email], phones=[app.phone]
        )


def export(person: Person) -> list[Section]:
    applications = [
        {
            "id": str(a.pk),
            "first_name": a.first_name,
            "last_name": a.last_name,
            "email": a.email,
            "phone": a.phone,
            "postcode": a.postcode,
            "subjects": a.subjects,
            "qualifications": a.qualifications,
            "experience": a.experience,
            "right_to_work": a.right_to_work,
            "answers": a.answers,
            "status": a.status,
            "decision_reason": a.decision_reason,
            "submitted_at": a.created_at,
        }
        for a in _applications(person)
    ]
    references = [
        {
            "id": str(r.pk),
            "referee": r.referee_name,
            "relationship": r.relationship,
            "status": r.status,
            "received_at": r.received_at,
        }
        for r in ReferenceRequest.objects.filter(application__in=_applications(person))
    ]
    checks = [
        {
            "id": str(c.pk),
            "requirement": c.requirement.name,
            "status": c.status,
            "issue_date": c.issue_date,
            "expiry_date": c.expiry_date,
        }
        for c in ComplianceRecord.objects.filter(
            tutor_id__in=person.of("people.tutor")
        ).select_related("requirement")
    ]
    return [
        Section("recruitment.applications", _("Applications"), applications),
        Section("recruitment.references", _("References"), references),
        Section("recruitment.compliance", _("Compliance checks"), checks),
    ]


def _uploads(person: Person) -> list[Any]:
    out: dict[str, Any] = {}
    for app in _applications(person).select_related("cv", "video").prefetch_related("attachments"):
        for stored in (app.cv, app.video, *app.attachments.all()):
            if stored is not None:
                out[str(stored.pk)] = stored
    return list(out.values())


def files(person: Person) -> list[Any]:
    return _uploads(person)


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    applications = _applications(person)
    out.file_ids += [str(f.pk) for f in _uploads(person)]
    for app in applications:
        app.attachments.clear()
        TutorApplication.objects.filter(pk=app.pk).update(
            first_name=ctx.label("recruitment.application", app.pk, _("Erased applicant")),
            last_name="",
            email="",
            phone="",
            postcode="",
            qualifications="",
            experience="",
            video_url="",
            answers={},
            decision_reason="",
            cv=None,
            video=None,
        )
        out.anonymised += 1
    out.deleted += ReferenceRequest.objects.filter(application__in=applications).delete()[0]
    out.deleted += Interview.objects.filter(application__in=applications).delete()[0]
    out.anonymised += Scorecard.objects.filter(application__in=applications).update(notes="")
    tutors = person.of("people.tutor")
    if tutors:
        out.retained += ComplianceRecord.objects.filter(tutor_id__in=tutors).update(
            number="", notes=""
        )
        out.notes.append("compliance check records kept as evidence; numbers cleared")
    return out


def _rejected(cutoff: datetime, limit: int) -> list[tuple[str, str]]:
    from tutortrack.privacy.selectors import erased_ids, held_ids

    skip = erased_ids("recruitment.application") | held_ids("recruitment.application")
    qs = (
        TutorApplication.objects.filter(
            status__in=[TutorApplication.Status.REJECTED, TutorApplication.Status.WITHDRAWN],
            decided_at__lt=cutoff,
            tutor__isnull=True,
        )
        .exclude(pk__in=list(skip))
        .values_list("pk", flat=True)
    )
    return [("recruitment.application", str(pk)) for pk in qs[:limit]]


register(
    Provider(
        key="recruitment",
        label=gettext_lazy("Applications"),
        expand=expand,
        export=export,
        files=files,
        erase=erase,
        order=35,
    )
)
register_retention(
    RetentionCategory(
        key="rejected_applications",
        label=gettext_lazy("Rejected or withdrawn tutor applications"),
        default_days=183,
        find=_rejected,
        order=12,
    )
)


# --- E18-T11 background checks ------------------------------------------------------------------


def _check_export(person: Person) -> list[Section]:
    from .models import BackgroundCheck

    rows = [
        {
            "id": str(c.pk),
            "provider": c.provider,
            "package": c.package,
            "status": c.status,
            "result": c.result,
            "requested_at": c.created_at,
            "consent_at": c.consent_at,
            "completed_at": c.completed_at,
            "certificate_issue_date": c.certificate_issue_date,
        }
        for c in BackgroundCheck.objects.filter(tutor_id__in=person.of("people.tutor"))
    ]
    return [Section("recruitment.background_checks", _("Background checks"), rows)]


def _check_erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    """Checks are evidence that vetting happened (kept, like compliance records); their
    results, certificate numbers and links are cleared."""
    from tutortrack.core.time import now

    from .models import BackgroundCheck

    out = ErasureOutcome()
    tutors = person.of("people.tutor")
    if tutors:
        out.retained += BackgroundCheck.objects.filter(tutor_id__in=tutors).update(
            result_details="",
            report_url="",
            invite_url="",
            certificate_number="",
            candidate_ref="",
            details_purged_at=now(),
        )
        if out.retained:
            out.notes.append("background checks kept as evidence; results and numbers cleared")
    return out


def _purge_check_details(cutoff: datetime, dry_run: bool, limit: int) -> int:
    from .background_checks import purge_details

    return purge_details(cutoff, dry_run, limit)


register(
    Provider(
        key="background_checks",
        label=gettext_lazy("Background checks"),
        export=_check_export,
        erase=_check_erase,
        order=36,
    )
)
register_retention(
    RetentionCategory(
        key="background_check_details",
        label=gettext_lazy("Background check results and certificate details"),
        default_days=183,
        purge=_purge_check_details,
        order=13,
    )
)
