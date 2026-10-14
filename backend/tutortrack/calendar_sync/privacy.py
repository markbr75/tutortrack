"""Online lesson recordings in erasure and retention (E22 data, E29 Part 2): links to
recordings of an erased student's lessons are removed, and every recording link is
removed after the ``recordings`` retention period."""

from __future__ import annotations

from datetime import datetime

from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    RetentionCategory,
    register,
    register_retention,
)

from .models import OnlineMeeting


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    students = person.of("people.student")
    if students:
        out.anonymised += (
            OnlineMeeting.objects.filter(lesson__attendees__student_id__in=students)
            .exclude(recording_urls=[])
            .update(recording_urls=[], attendee_urls={})
        )
    return out


def _purge_recordings(cutoff: datetime, dry_run: bool, limit: int) -> int:
    qs = OnlineMeeting.objects.filter(provisioned_end__lt=cutoff).exclude(recording_urls=[])
    if dry_run:
        return qs.count()
    ids = list(qs.values_list("pk", flat=True)[:limit])
    return OnlineMeeting.objects.filter(pk__in=ids).update(recording_urls=[])


register(Provider(key="calendar_sync", label="Online lessons", erase=erase, order=37))
register_retention(
    RetentionCategory(
        key="recordings",
        label=gettext_lazy("Online lesson recordings"),
        default_days=365,
        purge=_purge_recordings,
        order=25,
    )
)
