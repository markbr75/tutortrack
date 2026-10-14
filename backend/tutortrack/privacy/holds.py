"""Legal holds (FR-29-5): a held person or record is never erased or purged."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now

from . import subjects
from .events import LegalHoldPlaced, LegalHoldReleased
from .models import LegalHold


@transaction.atomic
def place(*, subject_type: str, subject_id: str, reason: str, user: Any = None) -> LegalHold:
    if not reason.strip():
        message = _("Say why the hold is needed.")
        raise BusinessRuleViolation(message, extra={"errors": {"reason": [message]}})
    if not subjects.is_valid(subject_type, str(subject_id)):
        raise NotFound(_("Person not found."))
    existing = LegalHold.objects.filter(
        subject_type=subject_type, subject_id=str(subject_id), released_at__isnull=True
    ).first()
    if existing is not None:
        return existing
    hold = LegalHold.objects.create(
        subject_type=subject_type,
        subject_id=str(subject_id),
        subject_label=subjects.label(subject_type, str(subject_id))[:200],
        reason=reason[:500],
        placed_by=user,
        placed_at=now(),
    )
    audit.record_create(hold)
    publish(
        LegalHoldPlaced(subject_id=hold.pk, person_type=subject_type, person_id=str(subject_id))
    )
    return hold


@transaction.atomic
def release(hold: LegalHold, *, reason: str, user: Any = None) -> LegalHold:
    hold = LegalHold.objects.select_for_update().get(pk=hold.pk)
    if hold.released_at is not None:
        return hold
    if not reason.strip():
        message = _("Say why the hold can be released.")
        raise BusinessRuleViolation(message, extra={"errors": {"reason": [message]}})
    with audit.track(hold, action="release"):
        hold.released_at = now()
        hold.released_by = user
        hold.release_reason = reason[:500]
        hold.save()
    publish(
        LegalHoldReleased(
            subject_id=hold.pk, person_type=hold.subject_type, person_id=hold.subject_id
        )
    )
    return hold
