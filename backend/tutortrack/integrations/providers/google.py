"""Google: OAuth, Calendar API v3 (events, sync tokens, push channels) and Meet REST v2."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import quote

from django.conf import settings

from . import http
from .base import (
    AccountInfo,
    CalendarInfo,
    ChangeSet,
    Channel,
    Credentials,
    EventBody,
    ExternalEvent,
    MeetingInfo,
    MeetingSpec,
    PushedEvent,
)
from .oauth2 import OAuth2Client

API = "https://www.googleapis.com/calendar/v3"
MEET_API = "https://meet.googleapis.com/v2"
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/meetings.space.created",
)
LESSON_PROPERTY = "tutortrackLessonId"


def _account(token: str) -> AccountInfo:
    body = http.request(
        "GET", "https://openidconnect.googleapis.com/v1/userinfo", token=token, provider="google"
    ).json()
    return AccountInfo(str(body.get("sub", "")), str(body.get("email", "")))


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    return OAuth2Client(
        provider="google",
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",  # noqa: S106 - a URL
        revoke_endpoint="https://oauth2.googleapis.com/revoke",
        client_id=config["GOOGLE_CLIENT_ID"],
        client_secret=config["GOOGLE_CLIENT_SECRET"],
        extra_params={"access_type": "offline", "prompt": "consent"},
        account=_account,
    )


def _when(value: dict[str, Any]) -> tuple[datetime | None, bool]:
    if "dateTime" in value:
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")), False
    if "date" in value:
        return datetime.combine(date.fromisoformat(value["date"]), time.min, tzinfo=UTC), True
    return None, False


def _parse(item: dict[str, Any]) -> ExternalEvent:
    start, all_day = _when(item.get("start", {}))
    end, _ = _when(item.get("end", {}))
    private = item.get("extendedProperties", {}).get("private", {})
    return ExternalEvent(
        id=item["id"],
        start=start,
        end=end,
        cancelled=item.get("status") == "cancelled",
        busy=item.get("transparency") != "transparent",
        all_day=all_day,
        lesson_id=str(private.get(LESSON_PROPERTY, "")),
        etag=str(item.get("etag", "")),
    )


class GoogleCalendar:
    def _cal(self, calendar_id: str) -> str:
        return f"{API}/calendars/{quote(calendar_id, safe='')}"

    def list_calendars(self, creds: Credentials) -> list[CalendarInfo]:
        body = http.request(
            "GET", f"{API}/users/me/calendarList", token=creds.access_token, provider="google"
        ).json()
        return [
            CalendarInfo(
                id=item["id"],
                name=item.get("summaryOverride") or item.get("summary", ""),
                primary=bool(item.get("primary")),
                writable=item.get("accessRole") in ("owner", "writer"),
            )
            for item in body.get("items", [])
        ]

    def create_calendar(self, creds: Credentials, name: str, timezone: str) -> str:
        body = http.request(
            "POST",
            f"{API}/calendars",
            token=creds.access_token,
            json_body={"summary": name, "timeZone": timezone},
            provider="google",
        ).json()
        return str(body["id"])

    def _body(self, event: EventBody) -> dict[str, Any]:
        return {
            "summary": event.title,
            "location": event.join_url or event.location,
            "description": event.description,
            "start": {"dateTime": event.start.isoformat(), "timeZone": event.timezone},
            "end": {"dateTime": event.end.isoformat(), "timeZone": event.timezone},
            "extendedProperties": {"private": {LESSON_PROPERTY: event.lesson_id}},
            "reminders": {"useDefault": True},
        }

    def put_event(
        self, creds: Credentials, calendar_id: str, event: EventBody, external_id: str = ""
    ) -> PushedEvent:
        url = f"{self._cal(calendar_id)}/events"
        if external_id:
            response = http.request(
                "PUT",
                f"{url}/{quote(external_id, safe='')}",
                token=creds.access_token,
                json_body={**self._body(event), "status": "confirmed"},
                provider="google",
            )
        else:
            response = http.request(
                "POST",
                url,
                token=creds.access_token,
                json_body=self._body(event),
                provider="google",
            )
        body = response.json()
        return PushedEvent(str(body["id"]), str(body.get("etag", "")))

    def delete_event(self, creds: Credentials, calendar_id: str, external_id: str) -> None:
        http.request(
            "DELETE",
            f"{self._cal(calendar_id)}/events/{quote(external_id, safe='')}",
            token=creds.access_token,
            provider="google",
        )

    def changes(
        self,
        creds: Credentials,
        calendar_id: str,
        sync_token: str,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> ChangeSet:
        params: dict[str, Any] = {"singleEvents": "true", "maxResults": 250}
        if sync_token:
            params["syncToken"] = sync_token
        else:
            params["timeMin"] = window_start.isoformat()
            params["timeMax"] = window_end.isoformat()
        events: list[ExternalEvent] = []
        while True:
            body = http.request(
                "GET",
                f"{self._cal(calendar_id)}/events",
                token=creds.access_token,
                params=params,
                provider="google",
            ).json()
            events += [_parse(item) for item in body.get("items", [])]
            if body.get("nextPageToken"):
                params = {**params, "pageToken": body["nextPageToken"]}
                continue
            return ChangeSet(events, str(body.get("nextSyncToken", "")), full=not sync_token)

    def watch(
        self,
        creds: Credentials,
        calendar_id: str,
        *,
        address: str,
        channel_id: str,
        token: str,
        expires_at: datetime,
    ) -> Channel | None:
        body = http.request(
            "POST",
            f"{self._cal(calendar_id)}/events/watch",
            token=creds.access_token,
            json_body={
                "id": channel_id,
                "type": "web_hook",
                "address": address,
                "token": token,
                "expiration": int(expires_at.timestamp() * 1000),
            },
            provider="google",
        ).json()
        expiry = datetime.fromtimestamp(int(body.get("expiration", 0)) / 1000, tz=UTC)
        return Channel(str(body["id"]), str(body.get("resourceId", "")), expiry)

    def stop(self, creds: Credentials, channel_id: str, resource_id: str) -> None:
        http.request(
            "POST",
            f"{API}/channels/stop",
            token=creds.access_token,
            json_body={"id": channel_id, "resourceId": resource_id},
            provider="google",
        )


class GoogleMeet:
    """Meet spaces via the Meet REST API (no calendar event needed); the join link is
    then written on the lesson and so onto the calendar event."""

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        body = http.request(
            "POST",
            f"{MEET_API}/spaces",
            token=creds.access_token,
            json_body={},
            provider="google",
        ).json()
        return MeetingInfo(
            external_id=str(body["name"]),
            join_url=str(body["meetingUri"]),
            host_url=str(body["meetingUri"]),
            data={"meeting_code": body.get("meetingCode", "")},
        )

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        body = http.request(
            "GET", f"{MEET_API}/{external_id}", token=creds.access_token, provider="google"
        ).json()  # a space has no times: nothing to change
        return MeetingInfo(external_id, str(body["meetingUri"]), str(body["meetingUri"]))

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        http.request(
            "POST",
            f"{MEET_API}/{external_id}:endActiveConference",
            token=creds.access_token,
            json_body={},
            retries=0,
            provider="google",
        )
