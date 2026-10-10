"""The provider-agnostic integration interfaces (E22 §2, shared with E23/E27).

A provider is described by a ``ProviderSpec`` (what it can do, how it authenticates, at
which level it connects) and implemented by small clients:

* ``OAuthClient``: authorization URL, code exchange (PKCE), refresh, revoke.
* ``CredentialClient``: verify typed-in credentials (CalDAV app passwords, API keys).
* ``CalendarClient``: calendars, event push, incremental change sync, push channels.
* ``MeetingClient``: online meetings (create/update/delete).

Clients receive ``Credentials`` (decrypted, fresh) and never touch the database; services
own persistence, token refresh and error bookkeeping. Every real client has a fake twin
used when the platform keys are empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ProviderError(Exception):
    """The provider refused or failed a request. The message is safe to show the user."""

    retryable = True


class AuthError(ProviderError):
    """The grant was revoked or the credentials are wrong: the user must reconnect."""

    retryable = False


class RateLimited(ProviderError):
    def __init__(self, message: str, retry_after: float = 60):
        super().__init__(message)
        self.retry_after = retry_after


class NotFound(ProviderError):
    retryable = False


class SyncTokenExpired(ProviderError):
    """The incremental sync token is no longer valid: do a full sync."""


class ConfigurationError(ProviderError):
    """Nothing to retry: the provider isn't set up (e.g. no account connected)."""

    retryable = False


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    capabilities: frozenset[str]  # calendar | video | accounting
    auth: str  # oauth2 | credentials | platform
    levels: tuple[str, ...]  # user | organisation
    credential_fields: tuple[str, ...] = ()  # for auth == "credentials"
    video_key: str = ""  # the video provider this account powers (google -> google_meet)
    poll_minutes: int = 5  # calendar polling fallback


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()
    account_id: str = ""
    account_name: str = ""


@dataclass(frozen=True)
class AccountInfo:
    account_id: str
    account_name: str = ""


@dataclass(frozen=True)
class Credentials:
    """What a client needs to call the provider for one connection."""

    access_token: str = ""
    secret: str = ""  # app-specific password / API key
    username: str = ""
    server_url: str = ""
    account_id: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalendarInfo:
    id: str
    name: str
    primary: bool = False
    writable: bool = True


@dataclass(frozen=True)
class EventBody:
    """A lesson as written to an external calendar. ``lesson_id`` goes into provider
    metadata (Google ``extendedProperties``, Graph extended properties, an iCalendar
    ``X-`` property) so changes made outside can be traced back."""

    lesson_id: str
    title: str
    start: datetime
    end: datetime
    timezone: str
    location: str = ""
    description: str = ""
    join_url: str = ""


@dataclass(frozen=True)
class PushedEvent:
    external_id: str
    etag: str = ""


@dataclass(frozen=True)
class ExternalEvent:
    id: str
    start: datetime | None = None
    end: datetime | None = None
    cancelled: bool = False
    busy: bool = True  # "free"/transparent events don't block time
    all_day: bool = False
    lesson_id: str = ""  # set on events TutorTrack wrote
    etag: str = ""


@dataclass(frozen=True)
class ChangeSet:
    events: list[ExternalEvent]
    next_token: str
    full: bool = False  # a full listing: anything not returned is gone


@dataclass(frozen=True)
class Channel:
    id: str
    resource_id: str
    expires_at: datetime


@dataclass(frozen=True)
class MeetingSpec:
    lesson_id: str
    topic: str
    start: datetime
    end: datetime
    timezone: str
    host_name: str = ""
    participants: tuple[tuple[str, str], ...] = ()  # (student id, name)
    space_key: str = ""  # Lessonspace: one space per job or per lesson
    options: dict[str, Any] = field(default_factory=dict)  # waiting_room, passcode, recording


@dataclass(frozen=True)
class MeetingInfo:
    external_id: str
    join_url: str
    host_url: str = ""
    passcode: str = ""
    attendee_urls: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)


class OAuthClient(Protocol):
    def authorize_url(
        self, *, state: str, redirect_uri: str, code_challenge: str, scopes: tuple[str, ...]
    ) -> str: ...

    def exchange(self, *, code: str, redirect_uri: str, code_verifier: str) -> TokenSet: ...

    def refresh(self, refresh_token: str) -> TokenSet: ...

    def revoke(self, token: str) -> None: ...


class CredentialClient(Protocol):
    def verify(self, credentials: Credentials) -> AccountInfo: ...


class CalendarClient(Protocol):
    def list_calendars(self, creds: Credentials) -> list[CalendarInfo]: ...

    def create_calendar(self, creds: Credentials, name: str, timezone: str) -> str: ...

    def put_event(
        self, creds: Credentials, calendar_id: str, event: EventBody, external_id: str = ""
    ) -> PushedEvent: ...

    def delete_event(self, creds: Credentials, calendar_id: str, external_id: str) -> None: ...

    def changes(
        self,
        creds: Credentials,
        calendar_id: str,
        sync_token: str,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> ChangeSet: ...

    def watch(
        self,
        creds: Credentials,
        calendar_id: str,
        *,
        address: str,
        channel_id: str,
        token: str,
        expires_at: datetime,
    ) -> Channel | None: ...

    def stop(self, creds: Credentials, channel_id: str, resource_id: str) -> None: ...


class MeetingClient(Protocol):
    def create_meeting(self, creds: Credentials, spec: MeetingSpec) -> MeetingInfo: ...

    def update_meeting(
        self, creds: Credentials, external_id: str, spec: MeetingSpec
    ) -> MeetingInfo: ...

    def delete_meeting(self, creds: Credentials, external_id: str) -> None: ...
