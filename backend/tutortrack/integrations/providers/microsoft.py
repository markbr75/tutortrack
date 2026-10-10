"""Microsoft 365: OAuth (v2 endpoint), Graph calendars (delta queries, subscriptions) and
Teams online meetings."""

from __future__ import annotations

from datetime import UTC, datetime
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

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = (
    "offline_access",
    "User.Read",
    "Calendars.ReadWrite",
    "OnlineMeetings.ReadWrite",
)
# A single-value extended property carrying our lesson id on events we write.
LESSON_PROPERTY = "String {6f2b8a52-6d0c-4c55-9b5c-0e9a6f1c2d31} Name TutorTrackLessonId"


def _account(token: str) -> AccountInfo:
    body = http.request("GET", f"{GRAPH}/me", token=token, provider="microsoft").json()
    return AccountInfo(
        str(body.get("id", "")), str(body.get("mail") or body.get("userPrincipalName", ""))
    )


def oauth_client() -> OAuth2Client:
    config = settings.INTEGRATIONS
    base = "https://login.microsoftonline.com/common/oauth2/v2.0"
    return OAuth2Client(
        provider="microsoft",
        authorize_endpoint=f"{base}/authorize",
        token_endpoint=f"{base}/token",
        client_id=config["MICROSOFT_CLIENT_ID"],
        client_secret=config["MICROSOFT_CLIENT_SECRET"],
        extra_params={"prompt": "select_account"},
        account=_account,
    )


def _dt(value: dict[str, Any] | None) -> datetime | None:
    if not value or not value.get("dateTime"):
        return None
    # Graph returns UTC when asked with Prefer: outlook.timezone="UTC"
    raw = value["dateTime"].split(".")[0]
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)


def _parse(item: dict[str, Any]) -> ExternalEvent:
    if "@removed" in item:
        return ExternalEvent(id=item["id"], cancelled=True)
    props = {p.get("id"): p.get("value") for p in item.get("singleValueExtendedProperties", [])}
    return ExternalEvent(
        id=item["id"],
        start=_dt(item.get("start")),
        end=_dt(item.get("end")),
        cancelled=bool(item.get("isCancelled")),
        busy=item.get("showAs") not in ("free", "workingElsewhere"),
        all_day=bool(item.get("isAllDay")),
        lesson_id=str(props.get(LESSON_PROPERTY) or ""),
        etag=str(item.get("@odata.etag", "")),
    )


UTC_PREFER = {"Prefer": 'outlook.timezone="UTC", odata.maxpagesize=200'}


class GraphCalendar:
    def _cal(self, calendar_id: str) -> str:
        return f"{GRAPH}/me/calendars/{quote(calendar_id, safe='')}"

    def list_calendars(self, creds: Credentials) -> list[CalendarInfo]:
        body = http.request(
            "GET", f"{GRAPH}/me/calendars", token=creds.access_token, provider="microsoft"
        ).json()
        return [
            CalendarInfo(
                id=item["id"],
                name=item.get("name", ""),
                primary=bool(item.get("isDefaultCalendar")),
                writable=bool(item.get("canEdit", True)),
            )
            for item in body.get("value", [])
        ]

    def create_calendar(self, creds: Credentials, name: str, timezone: str) -> str:
        body = http.request(
            "POST",
            f"{GRAPH}/me/calendars",
            token=creds.access_token,
            json_body={"name": name},
            provider="microsoft",
        ).json()
        return str(body["id"])

    def _body(self, event: EventBody) -> dict[str, Any]:
        return {
            "subject": event.title,
            "body": {"contentType": "text", "content": event.description},
            "start": {"dateTime": event.start.astimezone(UTC).isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": event.end.astimezone(UTC).isoformat(), "timeZone": "UTC"},
            "location": {"displayName": event.join_url or event.location},
            "singleValueExtendedProperties": [{"id": LESSON_PROPERTY, "value": event.lesson_id}],
        }

    def put_event(
        self, creds: Credentials, calendar_id: str, event: EventBody, external_id: str = ""
    ) -> PushedEvent:
        if external_id:
            response = http.request(
                "PATCH",
                f"{GRAPH}/me/events/{quote(external_id, safe='')}",
                token=creds.access_token,
                json_body=self._body(event),
                provider="microsoft",
            )
        else:
            response = http.request(
                "POST",
                f"{self._cal(calendar_id)}/events",
                token=creds.access_token,
                json_body=self._body(event),
                provider="microsoft",
            )
        body = response.json()
        return PushedEvent(str(body["id"]), str(body.get("@odata.etag", "")))

    def delete_event(self, creds: Credentials, calendar_id: str, external_id: str) -> None:
        http.request(
            "DELETE",
            f"{GRAPH}/me/events/{quote(external_id, safe='')}",
            token=creds.access_token,
            provider="microsoft",
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
        """Delta query on the calendar view; ``sync_token`` is the stored ``deltaLink``."""
        url = sync_token or (
            f"{self._cal(calendar_id)}/calendarView/delta"
            f"?startDateTime={window_start.astimezone(UTC).isoformat()}"
            f"&endDateTime={window_end.astimezone(UTC).isoformat()}"
        )
        if not url.startswith(GRAPH):
            raise ValueError("Unexpected delta link")
        events: list[ExternalEvent] = []
        expand = f"$expand=singleValueExtendedProperties($filter=id eq '{LESSON_PROPERTY}')"
        url = f"{url}{'&' if '?' in url else '?'}{quote(expand, safe='=$&()')}"
        while True:
            body = http.request(
                "GET", url, token=creds.access_token, headers=UTC_PREFER, provider="microsoft"
            ).json()
            events += [_parse(item) for item in body.get("value", [])]
            if body.get("@odata.nextLink"):
                url = body["@odata.nextLink"]
                continue
            return ChangeSet(events, str(body.get("@odata.deltaLink", "")), full=not sync_token)

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
            f"{GRAPH}/subscriptions",
            token=creds.access_token,
            json_body={
                "changeType": "created,updated,deleted",
                "notificationUrl": address,
                "resource": f"/me/calendars/{calendar_id}/events",
                "expirationDateTime": expires_at.astimezone(UTC).isoformat(),
                "clientState": token,
            },
            provider="microsoft",
        ).json()
        expiry = datetime.fromisoformat(str(body["expirationDateTime"]).replace("Z", "+00:00"))
        return Channel(str(body["id"]), str(body["id"]), expiry)

    def stop(self, creds: Credentials, channel_id: str, resource_id: str) -> None:
        http.request(
            "DELETE",
            f"{GRAPH}/subscriptions/{quote(channel_id, safe='')}",
            token=creds.access_token,
            provider="microsoft",
        )


class TeamsMeetings:
    def _body(self, spec: MeetingSpec) -> dict[str, Any]:
        return {
            "subject": spec.topic,
            "startDateTime": spec.start.astimezone(UTC).isoformat(),
            "endDateTime": spec.end.astimezone(UTC).isoformat(),
            "lobbyBypassSettings": {
                "scope": "organizer" if spec.options.get("waiting_room") else "everyone"
            },
        }

    def _info(self, body: dict[str, Any]) -> MeetingInfo:
        return MeetingInfo(
            external_id=str(body["id"]),
            join_url=str(body["joinWebUrl"]),
            host_url=str(body["joinWebUrl"]),
            passcode=str((body.get("joinMeetingIdSettings") or {}).get("passcode") or ""),
        )

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        return self._info(
            http.request(
                "POST",
                f"{GRAPH}/me/onlineMeetings",
                token=creds.access_token,
                json_body=self._body(spec),
                provider="microsoft",
            ).json()
        )

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        return self._info(
            http.request(
                "PATCH",
                f"{GRAPH}/me/onlineMeetings/{quote(external_id, safe='')}",
                token=creds.access_token,
                json_body=self._body(spec),
                provider="microsoft",
            ).json()
        )

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        http.request(
            "DELETE",
            f"{GRAPH}/me/onlineMeetings/{quote(external_id, safe='')}",
            token=creds.access_token,
            provider="microsoft",
        )
