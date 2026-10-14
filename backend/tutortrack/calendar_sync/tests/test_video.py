"""E22-T10: video attendance ingestion (Zoom and Lessonspace webhooks), recordings (consent,
access, retention) and the embedded classroom."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings

from tutortrack.calendar_sync import meetings, video
from tutortrack.calendar_sync.models import (
    LessonRecording,
    MeetingParticipantEvent,
    OnlineMeeting,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import routes
from tutortrack.integrations import services as integrations
from tutortrack.integrations.providers import fake
from tutortrack.integrations.providers.base import Credentials, RecordingInfo
from tutortrack.people import services as people_services
from tutortrack.people.tests.factories import ContactFactory, TutorProfileFactory
from tutortrack.tenancy.settings_service import update_settings

from .conftest import connect, make_lesson, settle

pytestmark = pytest.mark.django_db
SECRET = "zoom-webhook-secret"
ZOOM = {"ZOOM_WEBHOOK_SECRET": SECRET}


def zoom_secret() -> Any:
    return override_settings(INTEGRATIONS={**settings.INTEGRATIONS, **ZOOM})


def zoom_lesson(org, people) -> Any:
    with tenant_context(org):
        update_settings(
            "integrations",
            {"integrations.video_provider": "zoom", "integrations.zoom_recording": "cloud"},
        )
    connect(org, people["user"], provider="zoom")
    settle(org)
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        meetings.reconcile(lesson.pk)
        lesson.refresh_from_db()
    return lesson


def found_meeting(org, lesson) -> OnlineMeeting:
    with tenant_context(org):
        return OnlineMeeting.objects.select_related("lesson").get(lesson=lesson)


def zoom_post(client, event: dict[str, Any], *, secret: str = SECRET, skew: int = 0) -> Any:
    from tutortrack.integrations.routes import hmac_hex

    body = json.dumps(event).encode()
    timestamp = str(int(time.time()) - skew)
    signature = "v0=" + hmac_hex(secret, f"v0:{timestamp}:".encode() + body)
    return client.post(
        "/webhooks/zoom",
        body,
        content_type="application/json",
        HTTP_X_ZM_REQUEST_TIMESTAMP=timestamp,
        HTTP_X_ZM_SIGNATURE=signature,
    )


def participant(meeting: OnlineMeeting, kind: str, name: str, at, email: str = "") -> dict:
    field = "join_time" if kind.endswith("joined") else "leave_time"
    return {
        "event": f"meeting.participant_{kind}",
        "payload": {
            "account_id": "acc",
            "object": {
                "id": meeting.external_id,
                "uuid": "u-1",
                "participant": {
                    "user_name": name,
                    "email": email,
                    "participant_uuid": name,
                    field: at.isoformat().replace("+00:00", "Z"),
                },
            },
        },
    }


def test_zoom_webhook_validates_signatures_and_the_endpoint(org, people, client):
    with zoom_secret():
        challenge = zoom_post(
            client, {"event": "endpoint.url_validation", "payload": {"plainToken": "abc"}}
        )
        assert challenge.status_code == 200
        assert challenge.json()["plainToken"] == "abc"
        assert len(challenge.json()["encryptedToken"]) == 64
        assert zoom_post(client, {"event": "x"}, secret="wrong").status_code == 401
        assert zoom_post(client, {"event": "x"}, skew=3600).status_code == 401


def test_zoom_join_and_leave_suggest_the_register(org, people, client):
    """FR-22-4: ingest join/leave events to pre-fill attendance and actual duration."""
    lesson = zoom_lesson(org, people)
    found = found_meeting(org, lesson)
    assert routes.organisation_for("zoom", found.external_id) == str(org.pk)
    start = lesson.start
    student = people["student"].full_name
    events = [
        participant(
            found,
            "joined",
            people["tutor"].full_name,
            start - timedelta(minutes=2),
            email=people["tutor"].email,
        ),
        participant(found, "joined", student, start + timedelta(minutes=8)),
        participant(found, "left", student, start + timedelta(minutes=58)),
        participant(
            found,
            "left",
            people["tutor"].full_name,
            start + timedelta(minutes=60),
            email=people["tutor"].email,
        ),
        participant(found, "joined", "Mystery guest", start + timedelta(minutes=9)),
    ]
    with zoom_secret():
        for event in events:
            assert zoom_post(client, event).status_code == 200
        assert zoom_post(client, events[1]).status_code == 200  # a retried delivery
    with tenant_context(org):
        assert MeetingParticipantEvent.objects.count() == 5
        suggestion = video.attendance_suggestions(lesson)
    [row] = suggestion["students"]
    assert (row["suggested_outcome"], row["late_minutes"]) == ("late", 8)
    assert row["minutes_attended"] == 50
    assert (suggestion["actual_minutes"], suggestion["guests"]) == (50, 1)
    api = client_for(org, people["user"])
    response = api.get(f"/api/v1/lessons/{lesson.pk}/video-attendance")
    assert response.status_code == 200
    assert response.json()["students"][0]["suggested_outcome"] == "late"


def test_lessonspace_callback_url_is_signed_per_lesson(org, people, client):
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin").user
        integrations.connect_with_credentials(
            admin, provider="lessonspace", level="organisation", api_key="k"
        )
        update_settings("integrations", {"integrations.video_provider": "lessonspace"})
    settle(org)
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        meetings.reconcile(lesson.pk)
        url = meetings.video_callback_url(lesson)
    path = url.split("/webhooks/", 1)[1]
    sid = str(people["student"].pk)
    body = {
        "user": {"id": f"student:{sid}", "name": "Arjun"},
        "session": {"id": "s1"},
        "timestamp": lesson.start.isoformat(),
    }
    ok = client.post(
        f"/webhooks/{path}?event=user.join", json.dumps(body), content_type="application/json"
    )
    assert ok.status_code == 200
    forged = client.post(
        "/webhooks/lessonspace/aaaa.bbbb.cccc?event=user.join",
        json.dumps(body),
        content_type="application/json",
    )
    assert forged.status_code == 403
    with tenant_context(org):
        event = MeetingParticipantEvent.objects.get()
        suggestion = video.attendance_suggestions(lesson)
    assert (event.role, event.student_id) == ("student", people["student"].pk)
    assert suggestion["students"][0]["suggested_outcome"] == "present"


def test_recording_completed_webhook_stores_a_restricted_reference(org, people, client):
    """Recordings need every student's E29 lesson-recording consent."""
    lesson = zoom_lesson(org, people)
    found = found_meeting(org, lesson)
    event = {
        "event": "recording.completed",
        "payload": {
            "object": {
                "id": found.external_id,
                "password": "pw",
                "recording_files": [
                    {
                        "id": "rec-1",
                        "file_type": "MP4",
                        "file_size": 2048,
                        "play_url": "https://zoom.us/rec/play/1",
                        "download_url": "https://zoom.us/rec/download/1",
                        "recording_start": lesson.start.isoformat(),
                        "recording_end": (lesson.start + timedelta(minutes=55)).isoformat(),
                    },
                    {"id": "chat", "file_type": "CHAT"},
                ],
            }
        },
    }
    with zoom_secret():
        assert zoom_post(client, event).status_code == 200
        assert zoom_post(client, event).status_code == 200  # idempotent
    with tenant_context(org):
        [recording] = LessonRecording.objects.all()
    assert (recording.status, recording.duration_seconds) == ("restricted", 3300)
    assert recording.missing_consent == [str(people["student"].pk)]
    tutor_api = client_for(org, people["user"])
    assert tutor_api.get("/api/v1/recordings").json()["results"] == []  # hidden until released
    assert tutor_api.get(f"/api/v1/recordings/{recording.pk}/play").status_code == 403


def test_releasing_sharing_playing_and_deleting_recordings(org, people):
    from tutortrack.privacy.services import ensure_default_types, record_consent

    lesson = zoom_lesson(org, people)
    found = found_meeting(org, lesson)
    fake.add_recording("zoom", found.external_id, "rec-9", started_at=lesson.start)
    with tenant_context(org):
        assert video.fetch_recordings(lesson.pk) == 1
        recording = LessonRecording.objects.get()
        admin = MembershipFactory(organisation=org, role="admin").user
        from tutortrack.core.exceptions import BusinessRuleViolation

        with pytest.raises(BusinessRuleViolation):
            video.update_recording(recording, user=admin, release=True)  # no consent yet
        ensure_default_types()
        record_consent(
            subject_type="people.student",
            subject_id=str(people["student"].pk),
            key="lesson-recording",
            granted=True,
            method="staff",
        )
        video.update_recording(recording, user=admin, release=True, share_with_family=True)
    tutor_api = client_for(org, people["user"])
    listed = tutor_api.get("/api/v1/recordings").json()["results"]
    assert [r["id"] for r in listed] == [str(recording.pk)]
    played = tutor_api.get(f"/api/v1/recordings/{recording.pk}/play")
    assert played.status_code == 200
    assert played.json()["url"].endswith("/play")
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="read", object_id=str(recording.pk)).exists()
    family = family_user(org, people)
    assert client_for(org, family).get("/api/v1/me/recordings").json()[0]["id"] == str(recording.pk)
    assert client_for(org, family).get(f"/api/v1/recordings/{recording.pk}/play").status_code == 200
    other_tutor = MembershipFactory(organisation=org, role="tutor").user
    assert (
        client_for(org, other_tutor).get(f"/api/v1/recordings/{recording.pk}/play").status_code
        == 403
    )
    admin_api = client_for(org, admin)
    assert admin_api.delete(f"/api/v1/recordings/{recording.pk}").status_code == 204
    with tenant_context(org):
        recording.refresh_from_db()
    assert (recording.status, recording.play_url) == ("deleted", "")
    assert fake.FakeMeetings("zoom").list_recordings(Credentials(), found.external_id) == []


def family_user(org, people) -> Any:
    membership = MembershipFactory(organisation=org, role="client")
    contact = ContactFactory(organisation=org, client=people["client"], email=membership.user.email)
    with tenant_context(org):
        people_services.link_portal_user("people.contact", str(contact.pk), membership.user)
    return membership.user


def test_retention_deletes_recordings_and_join_logs(org, people):
    from tutortrack.calendar_sync.privacy import _purge_recordings, _purge_video_events

    lesson = zoom_lesson(org, people)
    found = found_meeting(org, lesson)
    with tenant_context(org):
        video.store_recordings(found, [RecordingInfo("rec-old", play_url="https://zoom.us/p")])
        video.record_participant_event(
            found,
            provider="zoom",
            event_id="e1",
            kind="joined",
            at=now() - timedelta(days=400),
            participant_key="p",
            name="Arjun Patel",
        )
        later = now() + timedelta(days=1)
        assert _purge_recordings(later, True, 100) >= 1
        _purge_recordings(later, False, 100)
        assert LessonRecording.objects.get().status == "deleted"
        assert _purge_video_events(now() - timedelta(days=180), False, 100) == 1


def test_classroom_for_tutor_and_family_with_consent_prompt(org, people):
    with tenant_context(org):
        update_settings("integrations", {"integrations.classroom_recording": True})
    lesson = make_lesson(org, people, online=True)
    with tenant_context(org):
        meetings.reconcile(lesson.pk)
    tutor_view = client_for(org, people["user"]).get(f"/api/v1/lessons/{lesson.pk}/classroom")
    assert tutor_view.status_code == 200
    body = tutor_view.json()
    assert (body["role"], body["provider"], body["embeddable"]) == ("tutor", "builtin", True)
    assert body["safeguarding_banner"]
    family = family_user(org, people)
    family_api = client_for(org, family)
    view = family_api.get(f"/api/v1/lessons/{lesson.pk}/classroom").json()
    assert view["role"] == "family"
    assert view["recording"] is True
    assert view["consent_needed"] == [str(people["student"].pk)]
    agreed = family_api.post(f"/api/v1/lessons/{lesson.pk}/classroom/consent", {}, format="json")
    assert agreed.status_code == 200
    assert family_api.get(f"/api/v1/lessons/{lesson.pk}/classroom").json()["consent_needed"] == []
    stranger = client_for(org, MembershipFactory(organisation=org, role="client").user)
    assert stranger.get(f"/api/v1/lessons/{lesson.pk}/classroom").status_code == 404


class TestRecordingIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/recordings"

    def make_object(self, organisation: Any) -> LessonRecording:
        from tutortrack.catalogue.tests.factories import ServiceFactory
        from tutortrack.people.tests.factories import ClientFactory, StudentFactory
        from tutortrack.scheduling import services as scheduling

        with tenant_context(organisation):
            tutor = TutorProfileFactory(organisation=organisation, status="active")
            student = StudentFactory(
                organisation=organisation, client=ClientFactory(organisation=organisation)
            )
            start = (now() + timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
            lesson = scheduling.create_lesson(
                start=start,
                end=start + timedelta(hours=1),
                service=ServiceFactory(organisation=organisation),
                attendees=[{"student": student}],
                tutors=[{"tutor": tutor}],
                timezone="Europe/London",
                override_conflicts=True,
            ).lesson
            return LessonRecording.objects.create(
                lesson=lesson, provider="zoom", external_id=f"r-{lesson.pk}"
            )


def test_zoom_and_daily_recording_requests(monkeypatch):
    from tutortrack.integrations.providers import Credentials, http
    from tutortrack.integrations.providers.video import DailyRooms, ZoomMeetings

    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> http.Response:
        calls.append({"method": method, "url": url, **kwargs})
        body: dict[str, Any] = {}
        if url.endswith("/recordings") and "zoom" in url:
            body = {
                "password": "pw",
                "recording_files": [
                    {
                        "id": "f1",
                        "file_type": "MP4",
                        "file_size": 10,
                        "recording_start": "2026-10-14T16:00:00Z",
                        "recording_end": "2026-10-14T16:50:00Z",
                        "play_url": "https://zoom.us/p",
                    }
                ],
            }
        elif "daily.co/v1/recordings" in url:
            body = {
                "data": [
                    {"id": "d1", "start_ts": 1760457600, "duration": 3000, "status": "finished"}
                ]
            }
        return http.Response(200, None, json.dumps(body).encode())  # type: ignore[arg-type]

    monkeypatch.setattr(http, "request", fake_request)
    [zoom] = ZoomMeetings().list_recordings(Credentials(access_token="t"), "123")
    assert (zoom.external_id, zoom.duration_seconds, zoom.password) == ("f1", 3000, "pw")
    [daily] = DailyRooms().list_recordings(Credentials(), "tt-room")
    assert (daily.external_id, daily.duration_seconds) == ("d1", 3000)
    assert calls[1]["params"] == {"room_name": "tt-room"}
