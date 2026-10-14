"""Shared shortlists in DSARs and erasure (E19-T08, E29 Part 2): the family's note when
choosing a tutor and the message sent to them."""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import ShortlistShare


def _shares(person: Person) -> list[ShortlistShare]:
    return list(
        ShortlistShare.objects.filter(job__client_id__in=person.of("people.client")).select_related(
            "chosen_tutor"
        )
    )


def export(person: Person) -> list[Section]:
    rows = [
        {
            "id": str(s.pk),
            "message": s.message,
            "status": s.status,
            "chosen_tutor": s.chosen_tutor.full_name if s.chosen_tutor else "",
            "chosen_at": s.chosen_at,
            "note": s.client_note,
        }
        for s in _shares(person)
    ]
    return [Section("matching.shortlists", _("Tutor shortlists shared with you"), rows)]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    for share in _shares(person):
        ShortlistShare.objects.filter(pk=share.pk).update(
            message=ctx.scrub(share.message), client_note=""
        )
        out.anonymised += 1
    return out


register(Provider(key="matching", label="Tutor shortlists", export=export, erase=erase, order=36))
