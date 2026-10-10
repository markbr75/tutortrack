"""CalDAV (Apple iCloud and others) with an app-specific password (FR-22-3).

A thin RFC 4791 client: PROPFIND for calendars, PUT/DELETE of iCalendar objects and a
time-range REPORT for polling (CalDAV has no push; the workflow polls every 10 minutes).
The server URL is user-supplied, so every request goes through the SSRF guard.
"""

from __future__ import annotations

import base64
import hashlib
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from . import http
from .base import (
    AccountInfo,
    AuthError,
    CalendarInfo,
    ChangeSet,
    Channel,
    Credentials,
    EventBody,
    ExternalEvent,
    ProviderError,
    PushedEvent,
)

ICLOUD = "https://caldav.icloud.com/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/"}
LESSON_PROPERTY = "X-TUTORTRACK-LESSON"


def _auth(creds: Credentials) -> str:
    raw = f"{creds.username}:{creds.secret}".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


def _dav(creds: Credentials, method: str, url: str, body: str = "", depth: str = "0") -> bytes:
    response = http.request(
        method,
        url,
        auth_header=_auth(creds),
        body=body.encode() if body else None,
        headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
        user_url=True,
        provider="caldav",
    )
    return response.body


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_stamp(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(event: EventBody, uid: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TutorTrack//Calendar sync//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(datetime.now(UTC))}",
        f"DTSTART:{_stamp(event.start)}",
        f"DTEND:{_stamp(event.end)}",
        f"SUMMARY:{_escape(event.title)}",
        f"LOCATION:{_escape(event.join_url or event.location)}",
        f"DESCRIPTION:{_escape(event.description)}",
        f"{LESSON_PROPERTY}:{event.lesson_id}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def parse_ics(href: str, data: str, etag: str = "") -> list[ExternalEvent]:
    unfolded = re.sub(r"\r?\n[ \t]", "", data)
    out = []
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        props: dict[str, str] = {}
        for line in block.split("END:VEVENT")[0].splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                props.setdefault(key.split(";")[0].upper(), value)
        start = _parse_stamp(props.get("DTSTART", ""))
        out.append(
            ExternalEvent(
                id=href,
                start=start,
                end=_parse_stamp(props.get("DTEND", "")) or start,
                cancelled=props.get("STATUS", "").upper() == "CANCELLED",
                busy=props.get("TRANSP", "OPAQUE").upper() != "TRANSPARENT",
                all_day=len(props.get("DTSTART", "").strip()) == 8,
                lesson_id=props.get(LESSON_PROPERTY, ""),
                etag=etag,
            )
        )
    return out[:1]  # recurring overrides beyond the master are ignored (polling window)


class CalDAVClient:
    def _base(self, creds: Credentials) -> str:
        return creds.server_url or ICLOUD

    def _home(self, creds: Credentials) -> str:
        base = self._base(creds)
        body = (
            '<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
        )
        tree = ET.fromstring(_dav(creds, "PROPFIND", base, body))  # noqa: S314
        principal = tree.find(".//d:current-user-principal/d:href", NS)
        if principal is None or not principal.text:
            raise AuthError("The CalDAV server didn't accept those details.")
        body = (
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
            "<c:calendar-home-set/></d:prop></d:propfind>"
        )
        tree = ET.fromstring(_dav(creds, "PROPFIND", urljoin(base, principal.text), body))  # noqa: S314
        home = tree.find(".//c:calendar-home-set/d:href", NS)
        if home is None or not home.text:
            raise ProviderError("No calendars found on the CalDAV server.")
        return urljoin(base, home.text)

    def verify(self, credentials: Credentials) -> AccountInfo:
        self._home(credentials)
        return AccountInfo(credentials.username, credentials.username)

    def list_calendars(self, creds: Credentials) -> list[CalendarInfo]:
        home = self._home(creds)
        body = (
            '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
            "<d:displayname/><d:resourcetype/></d:prop></d:propfind>"
        )
        tree = ET.fromstring(_dav(creds, "PROPFIND", home, body, depth="1"))  # noqa: S314
        out = []
        for response in tree.findall("d:response", NS):
            if response.find(".//d:resourcetype/c:calendar", NS) is None:
                continue
            href = response.findtext("d:href", default="", namespaces=NS)
            name = response.findtext(".//d:displayname", default="", namespaces=NS)
            out.append(CalendarInfo(id=urljoin(home, href), name=name or href))
        if out:
            out[0] = CalendarInfo(out[0].id, out[0].name, primary=True)
        return out

    def create_calendar(self, creds: Credentials, name: str, timezone: str) -> str:
        url = urljoin(self._home(creds), f"tutortrack-{uuid.uuid4().hex[:8]}/")
        body = (
            '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:set><d:prop>'
            f"<d:displayname>{name}</d:displayname></d:prop></d:set></c:mkcalendar>"
        )
        _dav(creds, "MKCALENDAR", url, body)
        return url

    def put_event(
        self, creds: Credentials, calendar_id: str, event: EventBody, external_id: str = ""
    ) -> PushedEvent:
        href = external_id or urljoin(calendar_id, f"tutortrack-{event.lesson_id}.ics")
        uid = f"{event.lesson_id}@tutortrack"
        data = ics(event, uid)
        response = http.request(
            "PUT",
            href,
            auth_header=_auth(creds),
            body=data.encode(),
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            user_url=True,
            provider="caldav",
        )
        etag = response.headers.get("ETag") or hashlib.sha256(data.encode()).hexdigest()[:16]
        return PushedEvent(href, str(etag))

    def delete_event(self, creds: Credentials, calendar_id: str, external_id: str) -> None:
        http.request(
            "DELETE", external_id, auth_header=_auth(creds), user_url=True, provider="caldav"
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
        """A full time-range listing each poll (no sync-collection on many servers)."""
        body = (
            '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter>"
            '<c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
            f'<c:time-range start="{_stamp(window_start)}" end="{_stamp(window_end)}"/>'
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        tree = ET.fromstring(_dav(creds, "REPORT", calendar_id, body, depth="1"))  # noqa: S314
        events: list[ExternalEvent] = []
        for response in tree.findall("d:response", NS):
            href = urljoin(calendar_id, response.findtext("d:href", default="", namespaces=NS))
            data = response.findtext(".//c:calendar-data", default="", namespaces=NS)
            etag = response.findtext(".//d:getetag", default="", namespaces=NS)
            events += parse_ics(href, data, etag)
        return ChangeSet(events, _stamp(datetime.now(UTC)), full=True)

    def watch(self, *args: object, **kwargs: object) -> Channel | None:
        return None  # CalDAV has no push: polled

    def stop(self, creds: Credentials, channel_id: str, resource_id: str) -> None:
        return None
