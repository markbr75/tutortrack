"""Class enrolments in DSARs and erasure (E20 data, E29 Part 2). Enrolments stay (they tie
to fees and registers); the booking contact details and free-text reasons are removed."""

from __future__ import annotations

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

from .models import Enrolment, EnrolmentTransfer, RolloverOffer


def _enrolments(person: Person) -> Q:
    return Q(student_id__in=person.of("people.student")) | Q(
        client_id__in=person.of("people.client")
    )


def export(person: Person) -> list[Section]:
    enrolments = [
        {
            "id": str(e.pk),
            "class": e.group_class.name,
            "status": e.status,
            "start_date": e.start_date,
            "end_date": e.end_date,
            "fee": str(e.fee) if e.fee is not None else "",
            "contact": e.contact,
            "withdrawal_reason": e.withdrawal_reason,
        }
        for e in Enrolment.objects.filter(_enrolments(person)).select_related("group_class")
    ]
    return [Section("courses.enrolments", _("Class enrolments"), enrolments)]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    enrolments = Enrolment.objects.filter(_enrolments(person))
    for enrolment in enrolments:
        Enrolment.objects.filter(pk=enrolment.pk).update(
            contact={}, withdrawal_reason=ctx.scrub(enrolment.withdrawal_reason), token_hash=""
        )
        out.anonymised += 1
    for transfer in EnrolmentTransfer.objects.filter(from_enrolment__in=enrolments):
        EnrolmentTransfer.objects.filter(pk=transfer.pk).update(reason=ctx.scrub(transfer.reason))
    out.anonymised += (
        RolloverOffer.objects.filter(enrolment__in=enrolments)
        .exclude(note="")
        .update(note="", token_hash="")
    )
    return out


register(
    Provider(
        key="courses",
        label=gettext_lazy("Classes and courses"),
        export=export,
        erase=erase,
        order=33,
    )
)
