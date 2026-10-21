"""Online lesson attendance, recordings and the embedded classroom (E22-T10).

Attendance (FR-22-4 "Attendance from video"):
  Zoom (``meeting.participant_joined/left``) and Lessonspace (``user.join/leave``) webhooks
  become ``MeetingParticipantEvent`` rows, matched to the lesson's tutor and students.
  ``attendance_suggestions`` turns them into a suggested register (present, late with
  minutes, absent) and the actual duration, which the tutor's register is pre-filled
  with. Nothing is recorded without the tutor confirming the register.

Recordings (FR-22-4 "Recordings"):
  ``store_recordings`` keeps references (never copies) to the provider's files, from the
  Zoom ``recording.completed`` webhook or ``RecordingFetchWorkflow`` (Daily, Lessonspace,
  and Zoom as a fallback). A recording of a lesson where any student lacks the E29
  ``lesson-recording`` consent is ``restricted``. ``recording_link`` checks access and
  audits the read. The E29 ``recordings`` retention category deletes them at the
  provider and here.

Classroom (FR-22-5):
  ``classroom`` returns what the in-app page needs: an embeddable room URL for the
  viewer's role (built-in Daily/Whereby rooms and Lessonspace embed; Zoom, Teams and
  Meet open in their own app), the safeguarding banner, the recording state and whether
  the viewer still needs to give recording consent, plus the lesson's shared resources.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.integrations import providers
from tutortrack.integrations.providers import ProviderError, RecordingInfo
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .meetings import _creds
from .models import LessonRecording, MeetingParticipantEvent, OnlineMeeting

logger = structlog.get_logger(__name__)
LATE_GRACE = timedelta(minutes=5)
EMBEDDABLE = {"builtin", "lessonspace"}
CONSENT_KEY = "lesson-recording"


def _setting(key: str, default: Any) -> Any:
    try:
        return get_setting(key)
    except KeyError:
        return default


# --- attendance ----------------------------------------------------------------------------------


def _match(lesson: Lesson, *, user_ref: str, name: str, email: str) -> tuple[str, Any, Any]:
    """(role, student, tutor) for a participant: Lessonspace user ids we set at launch
    (``tutor``, ``student:<id>``), else the tutor's email, else a student's name."""
    attendees = list(lesson.attendees.select_related("student"))
    tutors = [link.tutor for link in lesson.tutors.select_related("tutor")]
    if user_ref.startswith("student:"):
        sid = user_ref.split(":", 1)[1]
        student = next((a.student for a in attendees if str(a.student_id) == sid), None)
        if student is not None:
            return "student", student, None
    if user_ref == "tutor" and tutors:
        return "tutor", None, tutors[0]
    lowered = email.strip().lower()
    if lowered:
        tutor = next((t for t in tutors if t.email.lower() == lowered), None)
        if tutor is not None:
            return "tutor", None, tutor
    wanted = " ".join(name.lower().split())
    for attendee in attendees:
        s = attendee.student
        names = {s.full_name.lower(), s.first_name.lower(), (s.preferred_name or "").lower()}
        if wanted and wanted in {n for n in names if n}:
            return "student", s, None
    for tutor in tutors:
        if wanted and wanted == tutor.full_name.lower():
            return "tutor", None, tutor
    return "guest", None, None


def lesson_for_meeting(meeting: OnlineMeeting | None, at: datetime) -> Lesson | None:
    """The lesson a room event belongs to. Lessonspace spaces can be per job, so pick the
    job's lesson nearest the event time (within an hour either side)."""
    if meeting is None:
        return None
    lesson = meeting.lesson
    if not lesson.job_id:
        return lesson
    window = timedelta(hours=1)
    nearby = (
        Lesson.objects.filter(
            job_id=lesson.job_id,
            start__lte=at + window,
            end__gte=at - window,
            online_meeting__external_id=meeting.external_id,
        )
        .order_by("start")
        .first()
    )
    return nearby or lesson


@transaction.atomic
def record_participant_event(
    meeting: OnlineMeeting,
    *,
    provider: str,
    event_id: str,
    kind: str,
    at: datetime,
    participant_key: str,
    name: str = "",
    email: str = "",
    user_ref: str = "",
) -> MeetingParticipantEvent | None:
    """Store a join/leave once (webhooks retry); None when it was already stored."""
    lesson = lesson_for_meeting(meeting, at)
    if lesson is None:
        return None
    if MeetingParticipantEvent.objects.filter(provider=provider, event_id=event_id).exists():
        return None
    role, student, tutor = _match(lesson, user_ref=user_ref, name=name, email=email)
    try:
        with transaction.atomic():
            row = MeetingParticipantEvent.objects.create(
                lesson=lesson,
                meeting=meeting,
                provider=provider,
                event_id=event_id[:200],
                kind=kind,
                at=at,
                participant_key=(participant_key or name or "unknown")[:120],
                name=name[:200],
                role=role,
                student=student,
                tutor=tutor,
            )
    except IntegrityError:
        return None
    event_class = (
        events.ParticipantJoined
        if kind == MeetingParticipantEvent.Kind.JOINED
        else events.ParticipantLeft
    )
    publish(
        event_class(
            subject_id=lesson.pk,
            provider=provider,
            meeting_id=str(meeting.pk),
            role=role,
            student_id=str(student.pk) if student else None,
        )
    )
    return row


def _sessions(
    rows: list[MeetingParticipantEvent], end: datetime
) -> list[tuple[datetime, datetime]]:
    """Pair joins with the next leave (a missing leave runs to ``end``)."""
    sessions: list[tuple[datetime, datetime]] = []
    opened: datetime | None = None
    for row in rows:
        if row.kind == MeetingParticipantEvent.Kind.JOINED:
            if opened is None:
                opened = row.at
        elif opened is not None:
            sessions.append((opened, max(row.at, opened)))
            opened = None
    if opened is not None:
        sessions.append((opened, max(end, opened)))
    return sessions


def _minutes(sessions: list[tuple[datetime, datetime]]) -> int:
    return int(sum((b - a).total_seconds() for a, b in sessions) // 60)


def attendance_suggestions(lesson: Lesson) -> dict[str, Any]:
    """The register suggested by the video provider's join/leave events."""
    rows = list(MeetingParticipantEvent.objects.filter(lesson=lesson).order_by("at"))
    if not rows:
        return {"available": False, "students": [], "actual_minutes": None, "guests": 0}
    end_of_data = max(r.at for r in rows)
    end = max(end_of_data, min(lesson.end, now()))
    by_key: dict[str, list[MeetingParticipantEvent]] = {}
    for row in rows:
        by_key.setdefault(row.participant_key, []).append(row)
    student_sessions: dict[str, list[tuple[datetime, datetime]]] = {}
    tutor_sessions: list[tuple[datetime, datetime]] = []
    guests = 0
    for participant_rows in by_key.values():
        sessions = _sessions(participant_rows, end)
        first = participant_rows[0]
        if first.student_id:
            student_sessions.setdefault(str(first.student_id), []).extend(sessions)
        elif first.tutor_id:
            tutor_sessions.extend(sessions)
        else:
            guests += 1
    students = []
    for attendee in lesson.attendees.select_related("student"):
        sessions = sorted(student_sessions.get(str(attendee.student_id), []))
        if not sessions:
            outcome, late = "no_show", None
        else:
            joined = sessions[0][0]
            late_by = joined - lesson.start
            if late_by > LATE_GRACE:
                outcome, late = "late", int(late_by.total_seconds() // 60)
            else:
                outcome, late = "present", None
        students.append(
            {
                "attendee_id": str(attendee.pk),
                "student_id": str(attendee.student_id),
                "name": attendee.student.full_name,
                "suggested_outcome": outcome,
                "late_minutes": late,
                "minutes_attended": _minutes(sessions),
                "first_joined_at": sessions[0][0] if sessions else None,
                "last_left_at": sessions[-1][1] if sessions else None,
            }
        )
    everyone = sorted(tutor_sessions + [s for v in student_sessions.values() for s in v])
    actual = None
    if tutor_sessions and student_sessions:
        both_start = max(
            min(a for a, _ in tutor_sessions),
            min(a for v in student_sessions.values() for a, _ in v),
        )
        both_end = min(
            max(b for _, b in tutor_sessions),
            max(b for v in student_sessions.values() for _, b in v),
        )
        actual = max(0, int((both_end - both_start).total_seconds() // 60))
    elif everyone:
        actual = _minutes(everyone)
    return {
        "available": True,
        "students": students,
        "actual_minutes": actual,
        "tutor_minutes": _minutes(tutor_sessions),
        "guests": guests,
    }


def _parse_time(value: Any) -> datetime:
    if isinstance(value, (int, float)) and value > 0:
        from datetime import UTC

        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=UTC)
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    return now()


def handle_zoom_event(event: dict[str, Any]) -> bool:
    """A verified Zoom webhook: participant joined/left, meeting ended, recording ready.
    Routed by the meeting id (``integrations.routes``); unknown meetings are ignored."""
    from tutortrack.core.context import tenant_context
    from tutortrack.integrations import routes

    kind = str(event.get("event", ""))
    obj = (event.get("payload") or {}).get("object") or {}
    meeting_ref = str(obj.get("id", ""))
    organisation_id = routes.organisation_for("zoom", meeting_ref) if meeting_ref else None
    if organisation_id is None:
        return False
    with tenant_context(organisation_id):
        meeting = (
            OnlineMeeting.objects.select_related("lesson")
            .filter(provider="zoom", external_id=meeting_ref)
            .first()
        )
        if meeting is None:
            return False
        if kind in ("meeting.participant_joined", "meeting.participant_left"):
            if not _setting("integrations.video_attendance", True):
                return True
            person = obj.get("participant") or {}
            joined = kind.endswith("joined")
            at = _parse_time(person.get("join_time") if joined else person.get("leave_time"))
            key = str(
                person.get("participant_uuid")
                or person.get("user_id")
                or person.get("user_name")
                or ""
            )
            record_participant_event(
                meeting,
                provider="zoom",
                event_id=f"{obj.get('uuid', meeting_ref)}:{key}:{kind}:{at.isoformat()}",
                kind=MeetingParticipantEvent.Kind.JOINED
                if joined
                else MeetingParticipantEvent.Kind.LEFT,
                at=at,
                participant_key=key,
                name=str(person.get("user_name") or ""),
                email=str(person.get("email") or ""),
            )
        elif kind == "recording.completed":
            from tutortrack.integrations.providers.video import zoom_recording

            files = [
                zoom_recording(f, obj)
                for f in obj.get("recording_files", [])
                if f.get("file_type") in ("MP4", "M4A")
            ]
            if store_recordings(meeting, files):
                _signal_recordings(meeting.lesson)
    return True


def handle_lessonspace_event(
    organisation_id: str, lesson_id: str, event_name: str, body: dict[str, Any]
) -> bool:
    """A Lessonspace callback on the signed per-lesson URL (``?event=user.join`` ...)."""
    from tutortrack.core.context import tenant_context

    if event_name not in ("user.join", "user.leave", "session.start", "session.end"):
        return False
    with tenant_context(organisation_id):
        meeting = OnlineMeeting.objects.select_related("lesson").filter(lesson_id=lesson_id).first()
        if meeting is None:
            return False
        if not event_name.startswith("user.") or not _setting(
            "integrations.video_attendance", True
        ):
            return True
        user = body.get("user") or {}
        session = body.get("session") or {}
        at = _parse_time(body.get("timestamp") or body.get("time"))
        user_ref = str(user.get("id") or "")
        key = user_ref or str(user.get("name") or "")
        record_participant_event(
            meeting,
            provider="lessonspace",
            event_id=f"{session.get('id', '')}:{key}:{event_name}:{at.isoformat()}",
            kind=MeetingParticipantEvent.Kind.JOINED
            if event_name == "user.join"
            else MeetingParticipantEvent.Kind.LEFT,
            at=at,
            participant_key=key,
            name=str(user.get("name") or ""),
            user_ref=user_ref,
        )
    return True


def _signal_recordings(lesson: Lesson) -> None:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now

    from .video_processes import recordings_workflow_id

    wid = recordings_workflow_id(lesson.organisation_id, lesson.pk)

    def send() -> None:
        if WorkflowLink.objects.filter(workflow_id=wid, status="running").exists():
            signal_now(wid, "stored")

    transaction.on_commit(send)


# --- recordings ----------------------------------------------------------------------------------


def _missing_consent(lesson: Lesson) -> list[str]:
    """Students on the lesson without recording consent (their own, or a guardian's)."""
    from tutortrack.privacy.services import is_granted

    missing = []
    for attendee in lesson.attendees.select_related("student__client"):
        student_ok = is_granted("people.student", str(attendee.student_id), CONSENT_KEY)
        if not student_ok:
            missing.append(str(attendee.student_id))
    return missing


@transaction.atomic
def store_recordings(meeting: OnlineMeeting, recordings: list[RecordingInfo]) -> int:
    """Keep references to new recordings (idempotent by provider id)."""
    stored = 0
    for info in recordings:
        if not info.external_id:
            continue
        if LessonRecording.objects.filter(
            provider=meeting.provider, external_id=info.external_id
        ).exists():
            continue
        lesson = lesson_for_meeting(meeting, info.started_at or meeting.lesson.start)
        if lesson is None:
            continue
        missing = (
            _missing_consent(lesson)
            if _setting("integrations.recording_requires_consent", True)
            else []
        )
        recording = LessonRecording(
            lesson=lesson,
            meeting=meeting,
            provider=meeting.provider,
            external_id=info.external_id[:200],
            status=LessonRecording.Status.RESTRICTED
            if missing
            else LessonRecording.Status.AVAILABLE,
            started_at=info.started_at,
            duration_seconds=max(0, info.duration_seconds),
            size_bytes=max(0, info.size_bytes),
            file_type=info.file_type[:10],
            play_url=info.play_url,
            download_url=info.download_url,
            password=info.password,
            missing_consent=missing,
        )
        recording.save()
        audit.record_create(recording)
        publish(
            events.RecordingAvailable(
                subject_id=lesson.pk,
                provider=meeting.provider,
                meeting_id=str(meeting.pk),
                recording_id=str(recording.pk),
                restricted=bool(missing),
            )
        )
        stored += 1
    if stored:
        OnlineMeeting.objects.filter(pk=meeting.pk).update(
            recording_urls=[
                str(r)
                for r in LessonRecording.objects.filter(meeting=meeting)
                .exclude(status=LessonRecording.Status.DELETED)
                .values_list("pk", flat=True)
            ]
        )
    return stored


def fetch_recordings(lesson_id: Any) -> int:
    """Ask the provider for the lesson's recordings (``RecordingFetchWorkflow``)."""
    meeting = (
        OnlineMeeting.objects.select_related("connection", "lesson")
        .filter(lesson_id=lesson_id)
        .exclude(status=OnlineMeeting.Status.DELETED)
        .first()
    )
    if meeting is None or not meeting.external_id:
        return 0
    client = providers.meeting_client(meeting.provider)
    lister = getattr(client, "list_recordings", None)
    if lister is None:
        return 0
    found = lister(_creds(meeting.connection), meeting.external_id)
    lesson = meeting.lesson
    window_start, window_end = lesson.start - timedelta(hours=1), lesson.end + timedelta(hours=3)
    relevant = [
        r
        for r in found
        if r.started_at is None or (window_start <= r.started_at and r.started_at <= window_end)
    ]
    return store_recordings(meeting, relevant)


def recordings_supported(lesson: Lesson) -> bool:
    meeting = OnlineMeeting.objects.filter(lesson=lesson).first()
    if meeting is None or meeting.status == OnlineMeeting.Status.DELETED:
        return False
    if meeting.provider == "zoom" and str(_setting("integrations.zoom_recording", "none")) not in (
        "cloud",
    ):
        return False
    client = providers.meeting_client(meeting.provider)
    return hasattr(client, "list_recordings")


def _can_view(user: Any, recording: LessonRecording) -> bool:
    if has_perm(user, "video.recording.manage"):
        return True
    if recording.status != LessonRecording.Status.AVAILABLE:
        return False
    if has_perm(user, "video.recording.view"):
        from tutortrack.core.permissions import scope_queryset

        visible = scope_queryset(user, LessonRecording.objects.all(), "video.recording.view")
        if visible.filter(pk=recording.pk).exists():
            return True
    if recording.shared_with_family:
        from tutortrack.portal.household import household_for

        household = household_for(user)
        if household is not None:
            return recording.lesson.attendees.filter(student_id__in=household.student_ids).exists()
    return False


def recording_link(recording: LessonRecording, *, user: Any) -> dict[str, Any]:
    """The playback link, after an access check; every read is audited."""
    if recording.status == LessonRecording.Status.DELETED:
        raise NotFound(_("This recording was deleted."))
    if not _can_view(user, recording):
        raise PermissionDenied()
    url = recording.play_url or recording.download_url
    if recording.meeting_id:
        meeting = OnlineMeeting.objects.select_related("connection").get(pk=recording.meeting_id)
        fresh = getattr(providers.meeting_client(recording.provider), "recording_link", None)
        if fresh is not None:
            try:
                url = fresh(_creds(meeting.connection), recording.external_id) or url
            except ProviderError:
                logger.info("calendar_sync.recording_link_failed", recording=str(recording.pk))
    audit.record_read(recording, reason="recording_playback")
    return {"url": url, "password": recording.password, "expires_in": 3600}


@transaction.atomic
def update_recording(
    recording: LessonRecording,
    *,
    user: Any,
    release: bool | None = None,
    share_with_family: bool | None = None,
) -> LessonRecording:
    """Staff release a restricted recording (consent obtained since) or share it with
    the lesson's families."""
    if not has_perm(user, "video.recording.manage"):
        raise PermissionDenied()
    recording = LessonRecording.objects.select_for_update().get(pk=recording.pk)
    if recording.status == LessonRecording.Status.DELETED:
        raise BusinessRuleViolation(_("This recording was deleted."))
    with audit.track(recording, action="update"):
        if release:
            missing = _missing_consent(recording.lesson)
            if missing and _setting("integrations.recording_requires_consent", True):
                raise BusinessRuleViolation(_("Some students still haven't agreed to recording."))
            recording.status = LessonRecording.Status.AVAILABLE
            recording.missing_consent = []
        if share_with_family is not None:
            if share_with_family and recording.status != LessonRecording.Status.AVAILABLE:
                raise BusinessRuleViolation(_("Release the recording first."))
            recording.shared_with_family = share_with_family
        recording.save()
    return recording


def _delete_at_provider(recording: LessonRecording) -> None:
    if recording.meeting_id is None:
        return
    meeting = OnlineMeeting.objects.select_related("connection").get(pk=recording.meeting_id)
    deleter = getattr(providers.meeting_client(recording.provider), "delete_recording", None)
    if deleter is None:
        return
    try:
        deleter(_creds(meeting.connection), meeting.external_id, recording.external_id)
    except ProviderError:
        logger.info("calendar_sync.recording_delete_failed", recording=str(recording.pk))


@transaction.atomic
def delete_recording(recording: LessonRecording, *, reason: str, user: Any = None) -> None:
    if user is not None and not has_perm(user, "video.recording.manage"):
        raise PermissionDenied()
    recording = LessonRecording.objects.select_for_update().get(pk=recording.pk)
    if recording.status == LessonRecording.Status.DELETED:
        return
    _delete_at_provider(recording)
    with audit.track(recording, action="delete"):
        recording.status = LessonRecording.Status.DELETED
        recording.play_url = ""
        recording.download_url = ""
        recording.password = ""
        recording.deleted_at = now()
        recording.deleted_reason = reason[:200]
        recording.save()


# --- classroom (FR-22-5) -------------------------------------------------------------------------


def _viewer(lesson: Lesson, user: Any) -> tuple[str, list[str]]:
    """(role, student ids the viewer speaks for): tutor, family, staff or none."""
    if lesson.tutors.filter(tutor__membership__user=user).exists():
        return "tutor", []
    from tutortrack.portal.household import household_for

    household = household_for(user)
    if household is not None:
        ids = [
            str(sid)
            for sid in lesson.attendees.filter(student_id__in=household.student_ids).values_list(
                "student_id", flat=True
            )
        ]
        if ids:
            return "family", ids
    if has_perm(user, "scheduling.lesson.view"):
        return "staff", []
    return "", []


def classroom(lesson: Lesson, *, user: Any) -> dict[str, Any]:
    from tutortrack.scheduling.external import join_link

    role, student_ids = _viewer(lesson, user)
    if not role:
        raise NotFound(_("Lesson not found."))
    if not lesson.online:
        raise BusinessRuleViolation(_("This lesson isn't online."))
    meeting = OnlineMeeting.objects.filter(lesson=lesson).first()
    provider = meeting.provider if meeting else (lesson.meeting_provider or "")
    link = join_link(
        lesson, "host" if role == "tutor" else "participant", student_ids[0] if student_ids else ""
    )
    recording = bool(
        meeting
        and (
            (provider == "zoom" and str(_setting("integrations.zoom_recording", "none")) != "none")
            or (provider in EMBEDDABLE and _setting("integrations.classroom_recording", False))
        )
    )
    consent_needed: list[str] = []
    if recording and role == "family":
        from tutortrack.privacy.services import is_granted

        consent_needed = [
            s for s in student_ids if not is_granted("people.student", s, CONSENT_KEY)
        ]
    resources = _resources(lesson, student_ids if role == "family" else None)
    return {
        "lesson_id": str(lesson.pk),
        "title": lesson.title,
        "start": lesson.start,
        "end": lesson.end,
        "role": role,
        "provider": provider,
        "embeddable": provider in EMBEDDABLE and bool(link),
        "join_url": link.url if link else "",
        "opens_at": link.opens_at if link else None,
        "open": bool(link and link.opens_at is not None and link.opens_at <= now()),
        "safeguarding_banner": str(
            _setting("integrations.classroom_banner", "")
            or _(
                "This lesson follows our safeguarding policy. If you are worried about "
                "anything, tell a trusted adult or contact us."
            )
        ),
        "recording": recording,
        "consent_needed": consent_needed,
        "resources": resources,
    }


def _resources(lesson: Lesson, student_ids: list[str] | None) -> list[dict[str, Any]]:
    """Resources shared with the lesson (E21), its job or the viewer's students, newest
    first. Gap G5c (FR-21-8): with what the room needs to open them; the classroom page
    polls while the room is open, so a resource shared during the lesson appears in it."""
    from tutortrack.learning.services import lesson_shares

    seen: set[str] = set()
    out = []
    for share in lesson_shares(lesson, student_ids)[:40]:
        resource = share.resource
        if str(resource.pk) in seen:
            continue
        seen.add(str(resource.pk))
        out.append(
            {
                "id": str(resource.pk),
                "title": resource.title,
                "kind": resource.kind,
                "media_type": resource.media_type,
                "message": share.message,
                "shared_at": share.created_at,
            }
        )
    return out[:20]


def open_classroom_resource(lesson: Lesson, resource_id: Any, *, user: Any) -> dict[str, Any]:
    """Gap G5c (FR-21-8): anyone in the classroom opens a resource shared into it."""
    from tutortrack.learning.services import open_lesson_resource

    role, student_ids = _viewer(lesson, user)
    if not role:
        raise NotFound(_("Lesson not found."))
    return open_lesson_resource(
        lesson, resource_id, user, student_ids=student_ids if role == "family" else None
    )


@transaction.atomic
def give_recording_consent(lesson: Lesson, *, user: Any, student_ids: list[str]) -> list[str]:
    """A guardian (or student) agrees to recording from the classroom prompt (E29 consent
    record, method ``portal``)."""
    from tutortrack.privacy.services import ensure_default_types, record_consent

    role, mine = _viewer(lesson, user)
    if role != "family":
        raise PermissionDenied()
    wanted = [s for s in student_ids if s in mine] or mine
    ensure_default_types()
    for sid in wanted:
        record_consent(
            subject_type="people.student",
            subject_id=sid,
            key=CONSENT_KEY,
            granted=True,
            method="portal",
            given_by=user,
            on_behalf_of_child=True,
        )
    return wanted
