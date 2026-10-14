"""Import history in erasure (E28 data, E29 Part 2): the raw rows an import created a
person from keep a copy of their data, so erasure clears those rows' values."""

from __future__ import annotations

from django.db.models import Q

from tutortrack.privacy.registry import ErasureContext, ErasureOutcome, Person, Provider, register

from .models import ImportRow

TYPES = ("people.client", "people.contact", "people.student", "people.tutor")


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    q = Q(pk__in=[])
    for subject_type in TYPES:
        ids = person.of(subject_type)
        if ids:
            q |= Q(target_type__in=[subject_type, f"{subject_type}profile"], target_id__in=ids)
    out.anonymised += ImportRow.objects.filter(q).update(raw={}, values={}, previous={})
    return out


register(Provider(key="migration", label="Import history", erase=erase, order=38))
