"""Online meetings for online lessons (E22-T06..T09).

``reconcile(lesson_id)`` makes the provider match the lesson, whatever happened in
between (it is what ``OnlineMeetingProvisioningWorkflow`` retries): a planned online
lesson gets a meeting, a moved one an updated meeting, a cancelled (or no longer online)
one loses it. A link typed in by hand is respected (never replaced).

Which provider: the lesson's ``meeting_provider`` → the job's → the tutor's preference →
the service's (org setting) → the organisation default. Which account: the tutor's own
connection for that provider, else the organisation's; with neither, the built-in room
(Daily.co/Whereby on TutorTrack's account, no tutor account needed).
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import Any

import structlog
from django.db import transaction

from tutortrack.core.events import publish
from tutortrack.integrations import providers, selectors
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import (
    AuthError,
    Credentials,
    MeetingSpec,
    NotFound,
    ProviderError,
)
from tutortrack.scheduling.external import JoinLink
from tutortrack.scheduling.models import Lesson

from . import events
from .models import MeetingPreference, OnlineMeeting

logger = structlog.get_logger(__name__)
VIDEO_KEYS = set(providers.VIDEO_PROVIDERS) | {"none"}
Status = OnlineMeeting.Status


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _tutor_user_ids(lesson: Lesson) -> list[Any]:
    return [
        t.tutor.membership.user_id
        for t in lesson.tutors.select_related("tutor__membership")
        if t.tutor.membership is not None
    ]


def resolve_provider(lesson: Lesson) -> tuple[str, Any]:
    """(video provider, tutor preference or None)."""
    users = _tutor_user_ids(lesson)
    preference = MeetingPreference.objects.filter(user_id__in=users).first() if users else None
    if lesson.meeting_provider in VIDEO_KEYS:
        return lesson.meeting_provider, preference
    job = lesson.job if lesson.job_id else None
    if job is not None and job.meeting_provider in VIDEO_KEYS:
        return job.meeting_provider, preference
    if preference is not None and preference.provider in VIDEO_KEYS:
        return preference.provider, preference
    by_service = _setting("integrations.video_provider_by_service") or {}
    if str(lesson.service_id) in by_service:
        return str(by_service[str(lesson.service_id)]), preference
    return str(_setting("integrations.video_provider")), preference


def account_for(provider: str, lesson: Lesson) -> tuple[str, IntegrationConnection | None]:
    """The account to create the meeting with; falls back to the built-in room."""
    account = providers.VIDEO_PROVIDERS.get(provider)
    if account is None:
        return "builtin", None
    for user_id in _tutor_user_ids(lesson):
        found = selectors.user_connection(user_id, account)
        if found is not None:
            return provider, found
    org = selectors.org_connection(account)
    if org is not None:
        return provider, org
    return "builtin", None


def _manual(lesson: Lesson, meeting: OnlineMeeting | None) -> bool:
    if not lesson.meeting_url:
        return False
    return (
        meeting is None
        or meeting.status == Status.DELETED
        or (meeting.join_url != lesson.meeting_url)
    )


def wanted(lesson: Lesson) -> bool:
    return (
        lesson.online
        and lesson.status == Lesson.Status.PLANNED
        and bool(_setting("integrations.auto_create_meetings"))
    )


def spec_for(lesson: Lesson, provider: str, preference: Any) -> MeetingSpec:
    tutors = [t.tutor for t in lesson.tutors.select_related("tutor")]
    students = [
        (str(a.student_id), a.student.full_name) for a in lesson.attendees.select_related("student")
    ]
    per_job = _setting("integrations.lessonspace_space_per") == "job" and lesson.job_id
    return MeetingSpec(
        lesson_id=str(lesson.pk),
        topic=lesson.title,
        start=lesson.start,
        end=lesson.end,
        timezone=lesson.timezone,
        host_name=tutors[0].full_name if tutors else "",
        participants=tuple(students),
        space_key=f"job-{lesson.job_id}" if per_job else f"lesson-{lesson.pk}",
        options={
            "waiting_room": bool(_setting("integrations.zoom_waiting_room")),
            "passcode": bool(_setting("integrations.zoom_passcode")),
            "recording": str(_setting("integrations.zoom_recording")),
            "use_personal_room": bool(preference and preference.use_personal_room),
        },
    )


def _creds(connection: IntegrationConnection | None) -> Credentials:
    return integrations.credentials(connection) if connection is not None else Credentials()


def _set_lesson_link(lesson: Lesson, url: str, provider: str) -> None:
    from tutortrack.scheduling import services as scheduling

    changed = lesson.meeting_url != url or lesson.meeting_provider != provider
    if changed and lesson.status == Lesson.Status.PLANNED:
        scheduling.update_lesson(lesson, meeting_url=url, meeting_provider=provider, notify=False)


def _remove(meeting: OnlineMeeting, lesson: Lesson, *, clear_link: bool) -> None:
    if meeting.external_id and meeting.status != Status.DELETED:
        with contextlib.suppress(NotFound):
            providers.meeting_client(meeting.provider).delete_meeting(
                _creds(meeting.connection), meeting.external_id
            )
    if clear_link and lesson.meeting_url and lesson.meeting_url == meeting.join_url:
        _set_lesson_link(lesson, "", "")
    meeting.status = Status.DELETED
    meeting.save(update_fields=["status", "updated_at"])
    publish(
        events.OnlineMeetingDeleted(
            subject_id=lesson.pk, provider=meeting.provider, meeting_id=str(meeting.pk)
        )
    )


def reconcile(lesson_id: Any) -> str:
    """Returns created/updated/deleted/unchanged/skipped/gone. Provider errors propagate
    (after being recorded on the connection) so the workflow retries."""
    connection: IntegrationConnection | None = None
    try:
        with transaction.atomic():
            lesson = Lesson.objects.select_for_update().filter(pk=lesson_id).first()
            if lesson is None:
                return "gone"
            meeting = (
                OnlineMeeting.objects.filter(lesson=lesson).select_related("connection").first()
            )
            connection = meeting.connection if meeting is not None else None
            manual = _manual(lesson, meeting)
            provider, preference = resolve_provider(lesson)
            if not wanted(lesson) or manual or provider == "none":
                if meeting is not None and meeting.status != Status.DELETED:
                    _remove(meeting, lesson, clear_link=not manual)
                    return "deleted"
                return "skipped"
            provider, connection = account_for(provider, lesson)
            spec = spec_for(lesson, provider, preference)
            same_place = (
                meeting is not None
                and meeting.status == Status.ACTIVE
                and meeting.provider == provider
                and meeting.connection_id == (connection.pk if connection else None)
            )
            if (
                same_place
                and meeting is not None
                and meeting.provisioned_start == lesson.start
                and meeting.provisioned_end == lesson.end
            ):
                return "unchanged"
            if meeting is not None and meeting.status == Status.ACTIVE and not same_place:
                _remove(meeting, lesson, clear_link=False)
            client = providers.meeting_client(provider)
            creds = _creds(connection)
            if same_place and meeting is not None:
                info = client.update_meeting(creds, meeting.external_id, spec)
                outcome = "updated"
            else:
                info = client.create_meeting(creds, spec)
                outcome = "created"
            meeting = meeting or OnlineMeeting(lesson=lesson)
            meeting.provider = provider
            meeting.connection = connection
            meeting.status = Status.ACTIVE
            meeting.external_id = info.external_id
            meeting.join_url = info.join_url
            meeting.host_url = info.host_url or info.join_url
            meeting.passcode = info.passcode
            meeting.attendee_urls = info.attendee_urls
            meeting.provisioned_start, meeting.provisioned_end = lesson.start, lesson.end
            meeting.last_error = ""
            meeting.data = info.data
            meeting.save()
            _set_lesson_link(lesson, info.join_url, provider)
            event_class = (
                events.OnlineMeetingCreated if outcome == "created" else events.OnlineMeetingUpdated
            )
            publish(
                event_class(subject_id=lesson.pk, provider=provider, meeting_id=str(meeting.pk))
            )
            return outcome
    except ProviderError as exc:
        if connection is not None and isinstance(exc, AuthError):
            integrations.record_failure(connection, exc)
        raise


@transaction.atomic
def mark_failed(lesson_id: Any, error: str) -> bool:
    from tutortrack.integrations.notifications import notify_meeting_failed

    lesson = Lesson.objects.filter(pk=lesson_id).first()
    if lesson is None or not wanted(lesson):
        return False
    meeting, _created = OnlineMeeting.objects.get_or_create(
        lesson=lesson, defaults={"provider": resolve_provider(lesson)[0]}
    )
    if meeting.status == Status.ACTIVE:
        return False  # a later attempt succeeded meanwhile
    meeting.status = Status.FAILED
    meeting.last_error = error[:500]
    meeting.save(update_fields=["status", "last_error", "updated_at"])
    publish(
        events.OnlineMeetingFailed(
            subject_id=lesson.pk,
            provider=meeting.provider,
            meeting_id=str(meeting.pk),
            error=error[:300],
        )
    )
    notify_meeting_failed(lesson, error[:200])
    return True


# --- join links (FR-22-4, T09) -------------------------------------------------------------------


def join_resolver(lesson: Any, role: str, person_id: str) -> JoinLink | None:
    """Role-specific links: tutors get the host link, each student their own link when the
    provider has one (Lessonspace), everyone else the participant link."""
    meeting = OnlineMeeting.objects.filter(lesson_id=lesson.pk, status=Status.ACTIVE).first()
    if meeting is None or (lesson.meeting_url and lesson.meeting_url != meeting.join_url):
        return None  # no meeting of ours, or a link typed in by hand: use the lesson's
    try:
        minutes = int(_setting("integrations.join_window_minutes"))
    except Exception:
        minutes = 10
    if role == "host":
        url = meeting.host_url or meeting.join_url
    else:
        url = meeting.attendee_urls.get(person_id) or meeting.join_url
    return JoinLink(url, lesson.start - timedelta(minutes=minutes), meeting.provider, role)
