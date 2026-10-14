"""Video meeting providers (FR-22-4): Zoom, Lessonspace and the built-in rooms (Daily.co
or Whereby, on TutorTrack's own account, so tutors need no account)."""

from __future__ import annotations

import base64
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from django.conf import settings

from . import http
from .base import (
    AccountInfo,
    ConfigurationError,
    Credentials,
    MeetingInfo,
    MeetingSpec,
    RecordingInfo,
)
from .oauth2 import OAuth2Client

# --- Zoom -----------------------------------------------------------------------------------------

ZOOM_API = "https://api.zoom.us/v2"
ZOOM_SCOPES = (
    "meeting:write:meeting",
    "meeting:update:meeting",
    "meeting:delete:meeting",
    "user:read:user",
    # E22-T10: cloud recordings (reconnect Zoom to grant them).
    "cloud_recording:read:list_recording_files",
    "cloud_recording:delete:recording_file",
)


def _zoom_account(token: str) -> AccountInfo:
    body = http.request("GET", f"{ZOOM_API}/users/me", token=token, provider="zoom").json()
    return AccountInfo(str(body.get("id", "")), str(body.get("email", "")))


def zoom_oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="zoom",
        authorize_endpoint="https://zoom.us/oauth/authorize",
        token_endpoint="https://zoom.us/oauth/token",  # noqa: S106 - a URL
        revoke_endpoint="https://zoom.us/oauth/revoke",
        client_id=config["ZOOM_CLIENT_ID"],
        client_secret=config["ZOOM_CLIENT_SECRET"],
        basic_auth=True,
        account=_zoom_account,
    )


class ZoomMeetings:
    """One meeting per lesson, or the tutor's personal room (``use_personal_room``)."""

    def _body(self, spec: MeetingSpec) -> dict[str, Any]:
        options = spec.options
        return {
            "topic": spec.topic[:200],
            "type": 2,  # scheduled
            "start_time": spec.start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": max(1, math.ceil((spec.end - spec.start).total_seconds() / 60)),
            "timezone": spec.timezone,
            "default_password": bool(options.get("passcode", True)),
            "settings": {
                "waiting_room": bool(options.get("waiting_room", True)),
                "join_before_host": False,
                "auto_recording": options.get("recording", "none"),
            },
        }

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        if spec.options.get("use_personal_room"):
            me = http.request(
                "GET", f"{ZOOM_API}/users/me", token=creds.access_token, provider="zoom"
            ).json()
            url = str(me.get("personal_meeting_url", ""))
            if not url:
                raise ConfigurationError("The Zoom account has no personal meeting room.")
            return MeetingInfo(f"pmi:{me.get('pmi', '')}", url, url, data={"personal": True})
        body = http.request(
            "POST",
            f"{ZOOM_API}/users/me/meetings",
            token=creds.access_token,
            json_body=self._body(spec),
            provider="zoom",
        ).json()
        return MeetingInfo(
            external_id=str(body["id"]),
            join_url=str(body["join_url"]),
            host_url=str(body.get("start_url", body["join_url"])),
            passcode=str(body.get("password", "")),
        )

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        if external_id.startswith("pmi:"):
            return self.create_meeting(creds, spec)
        http.request(
            "PATCH",
            f"{ZOOM_API}/meetings/{quote(external_id, safe='')}",
            token=creds.access_token,
            json_body=self._body(spec),
            provider="zoom",
        )
        body = http.request(
            "GET",
            f"{ZOOM_API}/meetings/{quote(external_id, safe='')}",
            token=creds.access_token,
            provider="zoom",
        ).json()
        return MeetingInfo(
            external_id=external_id,
            join_url=str(body["join_url"]),
            host_url=str(body.get("start_url", body["join_url"])),
            passcode=str(body.get("password", "")),
        )

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        if external_id.startswith("pmi:"):
            return  # the personal room stays
        http.request(
            "DELETE",
            f"{ZOOM_API}/meetings/{quote(external_id, safe='')}",
            token=creds.access_token,
            provider="zoom",
        )

    # E22-T10: cloud recordings of the meeting (``recording.completed`` also pushes them).
    def list_recordings(self, creds: Credentials, external_id: str) -> list[RecordingInfo]:
        if external_id.startswith("pmi:"):
            return []
        body = http.request(
            "GET",
            f"{ZOOM_API}/meetings/{quote(external_id, safe='')}/recordings",
            token=creds.access_token,
            provider="zoom",
        ).json()
        return [
            zoom_recording(f, body)
            for f in body.get("recording_files", [])
            if f.get("file_type") in ("MP4", "M4A")
        ]

    def delete_recording(self, creds: Credentials, external_id: str, recording_id: str) -> None:
        http.request(
            "DELETE",
            f"{ZOOM_API}/meetings/{quote(external_id, safe='')}/recordings/"
            f"{quote(recording_id, safe='')}",
            token=creds.access_token,
            provider="zoom",
        )


def zoom_recording(file: dict[str, Any], meeting: dict[str, Any]) -> RecordingInfo:
    """A Zoom ``recording_files`` entry (from the API or the ``recording.completed``
    webhook) as a ``RecordingInfo``."""
    started = file.get("recording_start")
    ended = file.get("recording_end")
    duration = 0
    start_at = None
    if started:
        start_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if ended:
            end_at = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
            duration = int((end_at - start_at).total_seconds())
    return RecordingInfo(
        external_id=str(file.get("id", "")),
        started_at=start_at,
        duration_seconds=duration,
        size_bytes=int(file.get("file_size") or 0),
        file_type=str(file.get("file_type", "")),
        play_url=str(file.get("play_url", "")),
        download_url=str(file.get("download_url", "")),
        password=str(meeting.get("password", "")),
    )


# --- Lessonspace ----------------------------------------------------------------------------------

LESSONSPACE_API = "https://api.thelessonspace.com/v2"


class LessonspaceMeetings:
    """Spaces are launched per user: the tutor as leader, each student with their own URL.
    The space id is the job (one space per job, the default) or the lesson."""

    def verify(self, credentials: Credentials) -> AccountInfo:
        body = http.request(
            "GET",
            f"{LESSONSPACE_API}/my-organisation/",
            auth_header=f"Organisation {credentials.secret}",
            provider="lessonspace",
        ).json()
        return AccountInfo(str(body.get("id", "")), str(body.get("name", "")))

    def _launch(
        self,
        creds: Credentials,
        space: str,
        name: str,
        leader: bool,
        *,
        user_id: str = "",
        webhook_url: str = "",
    ) -> dict[str, Any]:
        user: dict[str, Any] = {"name": name or "Tutor", "leader": leader}
        if user_id:
            user["id"] = user_id  # E22-T10: matches join/leave webhooks to the person
        payload: dict[str, Any] = {"id": space, "user": user}
        if webhook_url:
            payload["webhooks"] = {
                "session": {
                    "start": f"{webhook_url}?event=session.start",
                    "end": f"{webhook_url}?event=session.end",
                },
                "user": {
                    "join": f"{webhook_url}?event=user.join",
                    "leave": f"{webhook_url}?event=user.leave",
                },
            }
        body: dict[str, Any] = http.request(
            "POST",
            f"{LESSONSPACE_API}/spaces/launch/",
            auth_header=f"Organisation {creds.secret}",
            json_body=payload,
            provider="lessonspace",
        ).json()
        return body

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        space = spec.space_key or f"lesson-{spec.lesson_id}"
        hook = str(spec.options.get("webhook_url") or "")
        host = self._launch(
            creds, space, spec.host_name, leader=True, user_id="tutor", webhook_url=hook
        )
        attendees = {
            student_id: str(
                self._launch(
                    creds,
                    space,
                    name,
                    leader=False,
                    user_id=f"student:{student_id}",
                    webhook_url=hook,
                )["client_url"]
            )
            for student_id, name in spec.participants
        }
        guest = self._launch(creds, space, "Guest", leader=False, webhook_url=hook)
        return MeetingInfo(
            external_id=space,
            join_url=str(guest["client_url"]),
            host_url=str(host["client_url"]),
            attendee_urls=attendees,
            data={"room_id": host.get("room_id", "")},
        )

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        return self.create_meeting(creds, spec)  # launching again refreshes the user links

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        return None  # spaces are reusable and free when idle: nothing to delete


# --- Built-in rooms -------------------------------------------------------------------------------


class DailyRooms:
    API = "https://api.daily.co/v1"

    def _auth(self) -> str:
        return f"Bearer {settings.INTEGRATIONS['DAILY_API_KEY']}"

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        expires = spec.end + timedelta(hours=2)
        body = http.request(
            "POST",
            f"{self.API}/rooms",
            auth_header=self._auth(),
            json_body={
                "name": f"tt-{spec.lesson_id.replace('-', '')[:24]}",
                "privacy": "public",
                "properties": {
                    "exp": int(expires.timestamp()),
                    "enable_knocking": bool(spec.options.get("waiting_room", False)),
                },
            },
            provider="daily",
        ).json()
        return MeetingInfo(str(body["name"]), str(body["url"]), str(body["url"]))

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        expires = spec.end + timedelta(hours=2)
        body = http.request(
            "POST",
            f"{self.API}/rooms/{quote(external_id, safe='')}",
            auth_header=self._auth(),
            json_body={"properties": {"exp": int(expires.timestamp())}},
            provider="daily",
        ).json()
        return MeetingInfo(external_id, str(body["url"]), str(body["url"]))

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        http.request(
            "DELETE",
            f"{self.API}/rooms/{quote(external_id, safe='')}",
            auth_header=self._auth(),
            provider="daily",
        )

    # E22-T10: cloud recordings of the room (fetched after the lesson by the workflow).
    def list_recordings(self, creds: Credentials, external_id: str) -> list[RecordingInfo]:
        body = http.request(
            "GET",
            f"{self.API}/recordings",
            auth_header=self._auth(),
            params={"room_name": external_id},
            provider="daily",
        ).json()
        return [
            RecordingInfo(
                external_id=str(r["id"]),
                started_at=datetime.fromtimestamp(int(r["start_ts"]), tz=UTC)
                if r.get("start_ts")
                else None,
                duration_seconds=int(r.get("duration") or 0),
                file_type="MP4",
            )
            for r in body.get("data", [])
            if r.get("status") == "finished"
        ]

    def recording_link(self, creds: Credentials, recording_id: str) -> str:
        """A fresh, short-lived download link (Daily's links expire)."""
        body = http.request(
            "GET",
            f"{self.API}/recordings/{quote(recording_id, safe='')}/access-link",
            auth_header=self._auth(),
            provider="daily",
        ).json()
        return str(body.get("download_link", ""))

    def delete_recording(self, creds: Credentials, external_id: str, recording_id: str) -> None:
        http.request(
            "DELETE",
            f"{self.API}/recordings/{quote(recording_id, safe='')}",
            auth_header=self._auth(),
            provider="daily",
        )


class WherebyRooms:
    API = "https://api.whereby.dev/v1"

    def _auth(self) -> str:
        return f"Bearer {settings.INTEGRATIONS['WHEREBY_API_KEY']}"

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        body = http.request(
            "POST",
            f"{self.API}/meetings",
            auth_header=self._auth(),
            json_body={
                "endDate": (spec.end + timedelta(hours=2)).astimezone(UTC).isoformat(),
                "fields": ["hostRoomUrl"],
                "roomMode": "normal",
            },
            provider="whereby",
        ).json()
        return MeetingInfo(
            str(body["meetingId"]), str(body["roomUrl"]), str(body.get("hostRoomUrl", ""))
        )

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        self.delete_meeting(creds, external_id)  # Whereby meetings can't be changed
        return self.create_meeting(creds, spec)

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        http.request(
            "DELETE",
            f"{self.API}/meetings/{quote(external_id, safe='')}",
            auth_header=self._auth(),
            provider="whereby",
        )


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
