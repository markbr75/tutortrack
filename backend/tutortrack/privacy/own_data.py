"""The privacy app's own personal data in DSARs and erasure: consent records (kept as
evidence, with the personal details minimised) and safeguarding cases (retained: they are
exempt from access requests and kept under safeguarding law, so the DSL decides)."""

from __future__ import annotations

from django.db.models import Q
from django.utils.translation import gettext as _

from .models import ConsentRecord, DataSubjectRequest, SafeguardingConcern
from .registry import ErasureContext, ErasureOutcome, Person, Provider, Section, register


def _consents(person: Person) -> Q:
    q = Q(pk__in=[])
    for subject_type in ("people.contact", "people.student", "people.client", "identity.user"):
        ids = person.of(subject_type)
        if ids:
            q |= Q(subject_type=subject_type, subject_id__in=ids)
    return q


def export(person: Person) -> list[Section]:
    consents = [
        {
            "id": str(r.pk),
            "consent": r.consent_type.name,
            "granted": r.granted,
            "version": r.version,
            "method": r.method,
            "given_by": r.given_by_name,
            "on_behalf_of_child": r.on_behalf_of_child,
            "recorded_at": r.recorded_at,
        }
        for r in ConsentRecord.objects.filter(_consents(person)).select_related("consent_type")
    ]
    requests = [
        {
            "id": str(r.pk),
            "reference": r.reference,
            "kind": r.kind,
            "status": r.status,
            "received_at": r.received_at,
        }
        for r in DataSubjectRequest.objects.filter(
            subject_type=person.subject_type, subject_id=person.subject_id
        )
    ]
    return [
        Section("privacy.consents", _("Consents"), consents),
        Section("privacy.requests", _("Data requests"), requests),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    out.anonymised += ConsentRecord.objects.filter(_consents(person)).update(
        given_by_name="", ip=None, user_agent=""
    )
    students = person.of("people.student")
    if students:
        out.retained += SafeguardingConcern.objects.filter(student_id__in=students).count()
    if out.retained:
        out.notes.append("safeguarding records retained (legal obligation)")
    return out


register(
    Provider(key="privacy", label="Consent and requests", export=export, erase=erase, order=90)
)
