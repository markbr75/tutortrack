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

from .models import LessonRecording, MeetingParticipantEvent, OnlineMeeting


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    from . import video

    out = ErasureOutcome()
    students = person.of("people.student")
    if students:
        out.anonymised += (
            OnlineMeeting.objects.filter(lesson__attendees__student_id__in=students)
            .exclude(recording_urls=[])
            .update(recording_urls=[], attendee_urls={})
        )
        # E22-T10: recordings of their lessons are deleted (at the provider too), and
        # their join/leave events are unlinked and renamed.
        for recording in LessonRecording.objects.filter(
            lesson__attendees__student_id__in=students
        ).exclude(status=LessonRecording.Status.DELETED):
            video.delete_recording(recording, reason="erasure")
            out.deleted += 1
        out.anonymised += MeetingParticipantEvent.objects.filter(student_id__in=students).update(
            name="", student=None, participant_key="erased"
        )
    tutors = person.of("people.tutor")
    if tutors:
        out.anonymised += MeetingParticipantEvent.objects.filter(tutor_id__in=tutors).update(
            name="", participant_key="erased"
        )
    return out


def _purge_recordings(cutoff: datetime, dry_run: bool, limit: int) -> int:
    from . import video

    qs = OnlineMeeting.objects.filter(provisioned_end__lt=cutoff).exclude(recording_urls=[])
    recordings = LessonRecording.objects.filter(created_at__lt=cutoff).exclude(
        status=LessonRecording.Status.DELETED
    )
    if dry_run:
        return qs.count() + recordings.count()
    for recording in recordings[:limit]:
        video.delete_recording(recording, reason="retention")
    ids = list(qs.values_list("pk", flat=True)[:limit])
    return OnlineMeeting.objects.filter(pk__in=ids).update(recording_urls=[])


def _purge_video_events(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """Join/leave logs (E22-T10) are only needed to fill in registers."""
    qs = MeetingParticipantEvent.objects.filter(at__lt=cutoff)
    if dry_run:
        return qs.count()
    ids = list(qs.values_list("pk", flat=True)[:limit])
    return MeetingParticipantEvent.objects.filter(pk__in=ids).delete()[0]


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
register_retention(
    RetentionCategory(
        key="video_attendance",
        label=gettext_lazy("Online lesson join and leave logs"),
        default_days=180,
        purge=_purge_video_events,
        order=26,
    )
)
