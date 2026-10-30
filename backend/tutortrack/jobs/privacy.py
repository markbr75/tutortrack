"""Jobs in DSARs and erasure (E29 Part 2). Jobs stay (they underpin lessons, charges and
pay); their names, goals, notes and status reasons lose the person's name."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import Job, JobStatusHistory

TEXT_FIELDS = ("name", "goals", "notes_internal", "notes_for_tutor", "notes_for_client")


def jobs_of(person: Person) -> Any:
    return Job.objects.filter(
        Q(client_id__in=person.of("people.client"))
        | Q(bill_to_id__in=person.of("people.client"))
        | Q(students__student_id__in=person.of("people.student"))
        | Q(tutors__tutor_id__in=person.of("people.tutor"))
    ).distinct()


def export(person: Person) -> list[Section]:
    rows = [
        {"id": str(job.pk), "reference": job.reference, "name": job.name, "status": job.status}
        for job in jobs_of(person).order_by("-created_at")[:2000]
    ]
    return [Section("jobs.jobs", _("Jobs"), rows)]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for row in jobs_of(person).values("pk", *TEXT_FIELDS):
        changes = {f: ctx.scrub(row[f]) for f in TEXT_FIELDS if ctx.scrub(row[f]) != row[f]}
        if changes:
            Job.objects.filter(pk=row["pk"]).update(**changes)
            out.anonymised += 1
    for row in JobStatusHistory.objects.filter(job__in=jobs_of(person)).values("pk", "reason"):
        if ctx.scrub(row["reason"]) != row["reason"]:
            JobStatusHistory.objects.filter(pk=row["pk"]).update(reason=ctx.scrub(row["reason"]))
    return out


register(Provider(key="jobs", label=gettext_lazy("Jobs"), export=export, erase=erase, order=29))
