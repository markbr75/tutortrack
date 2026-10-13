"""Split billing (E10-T15, FR-10-12): a job's or a student's charges shared between several
paying clients by percentage (separated parents 50/50, school 70% / parent 30%).

Charges are split with ``Money.allocate`` (largest remainder, so the parts always add up
to the whole) into one charge per payer; each payer's own tax exemption applies. A job's
split wins over a student's; without one, the attendee's client (or the job's ``bill_to``)
pays as before.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.people.models import Client

from . import events
from .models import BillingSplit

HUNDRED = Decimal(100)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def splits_of(*, job: Any = None, student: Any = None) -> list[BillingSplit]:
    if job is not None:
        rows = list(BillingSplit.objects.filter(job=job).select_related("client"))
        if rows:
            return rows
    if student is not None:
        return list(
            BillingSplit.objects.filter(student=student, job__isnull=True).select_related("client")
        )
    return []


def payers_for(
    *, job: Any = None, student: Any = None, client: Client
) -> list[tuple[Client, Decimal]]:
    """Who pays and what share; ``[(client, 100)]`` when there is no split."""
    rows = splits_of(job=job, student=student)
    if not rows:
        return [(client, HUNDRED)]
    return [(row.client, row.percent) for row in rows]


@transaction.atomic
def set_splits(
    *,
    shares: list[tuple[Client, Decimal]],
    job: Any = None,
    student: Any = None,
    user: Any = None,
) -> list[BillingSplit]:
    """Replace the split for a job or a student; an empty list removes it. Charges already
    created keep their payers (new and changed lessons follow the new split)."""
    if (job is None) == (student is None):
        raise _invalid("job", _("Split a job or a student."))
    if shares:
        if len(shares) < 2:
            raise _invalid("shares", _("Add at least two paying clients."))
        clients = [c.pk for c, _p in shares]
        if len(set(clients)) != len(clients):
            raise _invalid("shares", _("Each client can appear only once."))
        if sum((p for _c, p in shares), Decimal(0)) != HUNDRED:
            raise _invalid("shares", _("The shares must add up to 100%."))
        if any(p <= 0 for _c, p in shares):
            raise _invalid("shares", _("Each share must be more than zero."))
        currency = job.currency if job is not None else student.client.currency
        if any(c.currency != currency for c, _p in shares):
            raise _invalid("shares", _("Every paying client must use the same currency."))
    target = {"job": job} if job is not None else {"student": student, "job": None}
    before = [(str(r.client_id), str(r.percent)) for r in BillingSplit.objects.filter(**target)]
    BillingSplit.objects.filter(**target).delete()  # configuration, not a financial record
    rows = [
        BillingSplit.objects.create(client=client, percent=percent, position=i, **target)
        for i, (client, percent) in enumerate(shares)
    ]
    subject = job if job is not None else student
    audit.record(
        subject,
        "billing_split",
        {"split": [before, [(str(c.pk), str(p)) for c, p in shares]]},
    )
    publish(
        events.BillingSplitChanged(
            subject_id=subject.pk,
            target="job" if job is not None else "student",
            shares=[{"client_id": str(c.pk), "percent": str(p)} for c, p in shares],
        )
    )
    return rows
