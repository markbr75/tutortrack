"""In-memory providers for tests and for development without provider keys.

State lives in the Django cache (Redis in development, so the web process and the
workers share it; local memory in tests, where workers are threads) under the connected
account's id. The OAuth fake "consents" instantly: its authorization URL is our own
callback with a code ``fake-<provider>-<who>``.

Test helpers: ``FakeCalendar(account_id)`` adds/moves/deletes events as if the user did
it in Google; ``fail(key, times)`` makes the next calls of a provider fail (retries) and
``revoke(account_id)`` makes its grant invalid (reconnect needed).
"""

from __future__ import annotations

import hashlib
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache

from tutortrack.core.time import now

from .base import (
    AccountInfo,
    AuthError,
    CalendarInfo,
    ChangeSet,
    Channel,
    Credentials,
    EventBody,
    ExternalEvent,
    MeetingInfo,
    MeetingSpec,
    NotFound,
    ProviderError,
    PushedEvent,
    SyncTokenExpired,
    TokenSet,
)

TTL = 60 * 60 * 24 * 30
PREFIX = "integrations:fake"


# --- controls -------------------------------------------------------------------------------------


def fail(key: str, times: int = 1, *, auth: bool = False) -> None:
    """The next ``times`` calls to provider ``key`` (e.g. ``zoom``, ``google``) fail."""
    cache.set(f"{PREFIX}:fail:{key}", {"times": times, "auth": auth}, TTL)


def revoke(account_id: str) -> None:
    cache.set(f"{PREFIX}:revoked:{account_id}", True, TTL)


def _check(key: str, account_id: str = "") -> None:
    if account_id and cache.get(f"{PREFIX}:revoked:{account_id}"):
        raise AuthError("Access was revoked at the provider.")
    plan = cache.get(f"{PREFIX}:fail:{key}")
    if plan and plan["times"] > 0:
        cache.set(f"{PREFIX}:fail:{key}", {**plan, "times": plan["times"] - 1}, TTL)
        if plan["auth"]:
            raise AuthError("Access was revoked at the provider.")
        raise ProviderError(f"{key} is unavailable (simulated).")


# --- OAuth and credentials -----------------------------------------------------------------------


class FakeOAuth:
    def __init__(self, provider: str):
        self.provider = provider

    def authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, scopes: tuple[str, ...]
    ) -> str:
        code = f"fake-{self.provider}-{secrets.token_hex(4)}"
        return f"{redirect_uri}?{urllib.parse.urlencode({'code': code, 'state': state})}"

    def _tokens(self, who: str, refresh: str = "") -> TokenSet:
        account = f"{self.provider}:{who}"
        return TokenSet(
            access_token=f"fake-access-{secrets.token_hex(6)}",
            refresh_token=refresh or f"fake-refresh-{who}",
            expires_at=now() + timedelta(hours=1),
            scopes=("fake",),
            account_id=account,
            account_name=f"{who}@example.com",
        )

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        prefix = f"fake-{self.provider}-"
        if not code.startswith(prefix) or not code_verifier:
            raise AuthError("The authorization code is not valid.")
        _check(self.provider)
        return self._tokens(code[len(prefix) :])

    def refresh(self, refresh_token: str) -> TokenSet:
        who = refresh_token.removeprefix("fake-refresh-")
        _check(self.provider, f"{self.provider}:{who}")
        return self._tokens(who, refresh_token)

    def revoke(self, token: str) -> None:
        return None


class FakeCredentials:
    def __init__(self, provider: str):
        self.provider = provider

    def verify(self, credentials: Credentials) -> AccountInfo:
        if "wrong" in credentials.secret or not credentials.secret:
            raise AuthError("Those details weren't accepted.")
        who = credentials.username or hashlib.sha256(credentials.secret.encode()).hexdigest()[:8]
        return AccountInfo(f"{self.provider}:{who}", credentials.username or "API key")


# --- calendars -----------------------------------------------------------------------------------


class FakeCalendar:
    """One account's calendars and events (also the test handle)."""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.key = f"{PREFIX}:cal:{account_id}"

    def load(self) -> dict[str, Any]:
        data: dict[str, Any] | None = cache.get(self.key)
        if data is None:
            data = {
                "seq": 0,
                "n": 0,
                "calendars": {"primary": {"name": "Personal", "primary": True, "events": {}}},
                "channels": {},
            }
        return data

    def save(self, data: dict[str, Any]) -> None:
        cache.set(self.key, data, TTL)

    def _bump(self, data: dict[str, Any], calendar_id: str, event_id: str, **changes: Any) -> str:
        data["seq"] += 1
        events = data["calendars"].setdefault(
            calendar_id, {"name": calendar_id, "primary": False, "events": {}}
        )["events"]
        row = events.setdefault(event_id, {})
        row.update(changes, seq=data["seq"], etag=f'"{data["seq"]}"')
        return event_id

    def add_event(
        self,
        start: datetime,
        end: datetime,
        *,
        calendar_id: str = "primary",
        title: str = "Busy",
        busy: bool = True,
        lesson_id: str = "",
    ) -> str:
        data = self.load()
        data["n"] += 1
        event_id = f"evt{data['n']}"
        self._bump(
            data,
            calendar_id,
            event_id,
            start=start.isoformat(),
            end=end.isoformat(),
            title=title,
            busy=busy,
            lesson_id=lesson_id,
            cancelled=False,
        )
        self.save(data)
        return event_id

    def move_event(
        self, event_id: str, start: datetime, end: datetime, *, calendar_id: str = "primary"
    ) -> None:
        data = self.load()
        self._bump(data, calendar_id, event_id, start=start.isoformat(), end=end.isoformat())
        self.save(data)

    def delete_event(self, event_id: str, *, calendar_id: str = "primary") -> None:
        data = self.load()
        self._bump(data, calendar_id, event_id, cancelled=True)
        self.save(data)

    def events(self, calendar_id: str = "primary", *, live: bool = True) -> dict[str, Any]:
        events: dict[str, Any] = self.load()["calendars"].get(calendar_id, {}).get("events", {})
        return {k: v for k, v in events.items() if not (live and v.get("cancelled"))}

    def find_lesson(self, lesson_id: str) -> tuple[str, str, dict[str, Any]] | None:
        for cal_id, calendar in self.load()["calendars"].items():
            for event_id, row in calendar["events"].items():
                if row.get("lesson_id") == lesson_id and not row.get("cancelled"):
                    return cal_id, event_id, row
        return None

    def channels(self) -> dict[str, Any]:
        channels: dict[str, Any] = self.load()["channels"]
        return channels


def _event(event_id: str, row: dict[str, Any]) -> ExternalEvent:
    return ExternalEvent(
        id=event_id,
        start=datetime.fromisoformat(row["start"]) if row.get("start") else None,
        end=datetime.fromisoformat(row["end"]) if row.get("end") else None,
        cancelled=bool(row.get("cancelled")),
        busy=bool(row.get("busy", True)),
        lesson_id=str(row.get("lesson_id", "")),
        etag=str(row.get("etag", "")),
    )


class FakeCalendarClient:
    def __init__(self, provider: str, *, push: bool = True):
        self.provider = provider
        self.push = push

    def _store(self, creds: Credentials) -> FakeCalendar:
        _check(self.provider, creds.account_id)
        return FakeCalendar(creds.account_id)

    def list_calendars(self, creds: Credentials) -> list[CalendarInfo]:
        data = self._store(creds).load()
        return [
            CalendarInfo(id=k, name=v["name"], primary=bool(v.get("primary")))
            for k, v in data["calendars"].items()
        ]

    def create_calendar(self, creds: Credentials, name: str, timezone: str) -> str:
        store = self._store(creds)
        data = store.load()
        data["n"] += 1
        cal_id = f"cal{data['n']}"
        data["calendars"][cal_id] = {"name": name, "primary": False, "events": {}}
        store.save(data)
        return cal_id

    def put_event(
        self, creds: Credentials, calendar_id: str, event: EventBody, external_id: str = ""
    ) -> PushedEvent:
        store = self._store(creds)
        data = store.load()
        if external_id and external_id not in data["calendars"].get(calendar_id, {}).get(
            "events", {}
        ):
            raise NotFound("No such event.")
        if not external_id:
            data["n"] += 1
            external_id = f"evt{data['n']}"
        store._bump(
            data,
            calendar_id,
            external_id,
            start=event.start.isoformat(),
            end=event.end.isoformat(),
            title=event.title,
            busy=True,
            lesson_id=event.lesson_id,
            cancelled=False,
            location=event.join_url or event.location,
            description=event.description,
        )
        store.save(data)
        row = data["calendars"][calendar_id]["events"][external_id]
        return PushedEvent(external_id, row["etag"])

    def delete_event(self, creds: Credentials, calendar_id: str, external_id: str) -> None:
        store = self._store(creds)
        data = store.load()
        if external_id not in data["calendars"].get(calendar_id, {}).get("events", {}):
            raise NotFound("No such event.")
        store._bump(data, calendar_id, external_id, cancelled=True)
        store.save(data)

    def changes(
        self,
        creds: Credentials,
        calendar_id: str,
        sync_token: str,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> ChangeSet:
        data = self._store(creds).load()
        events = data["calendars"].get(calendar_id, {}).get("events", {})
        if not sync_token.isdigit() and sync_token:
            raise SyncTokenExpired("The sync token expired.")
        since = int(sync_token) if sync_token else None
        out = []
        for event_id, row in events.items():
            if since is not None:
                if row["seq"] > since:
                    out.append(_event(event_id, row))
                continue
            event = _event(event_id, row)
            if event.cancelled or event.start is None or event.end is None:
                continue
            if event.start < window_end and event.end > window_start:
                out.append(event)
        return ChangeSet(out, str(data["seq"]), full=since is None)

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
        if not self.push:
            return None
        store = self._store(creds)
        data = store.load()
        data["channels"][channel_id] = {
            "calendar_id": calendar_id,
            "address": address,
            "token": token,
            "expires_at": expires_at.isoformat(),
        }
        store.save(data)
        return Channel(channel_id, f"res-{channel_id}", expires_at)

    def stop(self, creds: Credentials, channel_id: str, resource_id: str) -> None:
        store = FakeCalendar(creds.account_id)
        data = store.load()
        data["channels"].pop(channel_id, None)
        store.save(data)


# --- meetings ------------------------------------------------------------------------------------


class FakeMeetings:
    def __init__(self, provider: str):
        self.provider = provider

    def _n(self) -> int:
        key = f"{PREFIX}:meetings:{self.provider}"
        try:
            return int(cache.incr(key))
        except ValueError:
            cache.set(key, 1, TTL)
            return 1

    def _info(self, external_id: str, spec: MeetingSpec) -> MeetingInfo:
        base = f"https://{self.provider}.fake-meetings.test/{external_id}"
        cache.set(
            f"{PREFIX}:meeting:{self.provider}:{external_id}",
            {"start": spec.start.isoformat(), "topic": spec.topic},
            TTL,
        )
        return MeetingInfo(
            external_id=external_id,
            join_url=base,
            host_url=f"{base}?host=1",
            passcode="123456" if spec.options.get("passcode") else "",
            attendee_urls={sid: f"{base}?student={sid}" for sid, _name in spec.participants},
        )

    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo:
        _check(self.provider, creds.account_id)
        return self._info(f"m{self._n()}", spec)

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo:
        _check(self.provider, creds.account_id)
        return self._info(external_id, spec)

    def delete_meeting(self, creds: Credentials, external_id: str) -> None:
        _check(self.provider, creds.account_id)
        cache.delete(f"{PREFIX}:meeting:{self.provider}:{external_id}")


def meeting_state(provider: str, external_id: str) -> dict[str, Any] | None:
    found: dict[str, Any] | None = cache.get(f"{PREFIX}:meeting:{provider}:{external_id}")
    return found
