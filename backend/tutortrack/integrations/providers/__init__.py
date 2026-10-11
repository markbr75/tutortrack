"""Provider registry (E22 §2). Each provider has a ``ProviderSpec`` and client factories;
a provider whose platform keys are empty (development, tests) gets its fake twin.

E23 (accounting) and E27 add providers by calling ``register()`` with their spec and
factories; nothing else in the framework is provider specific.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from .base import (
    AccountInfo,
    AuthError,
    CalendarClient,
    CalendarInfo,
    ChangeSet,
    Channel,
    ConfigurationError,
    CredentialClient,
    Credentials,
    EventBody,
    ExternalEvent,
    MeetingClient,
    MeetingInfo,
    MeetingSpec,
    NotFound,
    OAuthClient,
    ProviderError,
    ProviderSpec,
    PushedEvent,
    RateLimited,
    Rejected,
    SyncTokenExpired,
    TokenSet,
)

__all__ = [
    "AccountInfo",
    "AuthError",
    "CalendarInfo",
    "ChangeSet",
    "Channel",
    "ConfigurationError",
    "Credentials",
    "EventBody",
    "ExternalEvent",
    "MeetingInfo",
    "MeetingSpec",
    "NotFound",
    "ProviderError",
    "ProviderSpec",
    "PushedEvent",
    "RateLimited",
    "Rejected",
    "SyncTokenExpired",
    "TokenSet",
    "all_specs",
    "calendar_client",
    "client",
    "credential_client",
    "get_spec",
    "health_check",
    "is_fake",
    "meeting_client",
    "oauth_client",
    "register",
    "scopes",
]


@dataclass(frozen=True)
class Provider:
    spec: ProviderSpec
    live: Callable[[], bool]  # platform keys present?
    scopes: tuple[str, ...] = ()
    oauth: Callable[[], Any] | None = None
    credentials: Callable[[], Any] | None = None
    calendar: Callable[[], Any] | None = None
    meetings: Callable[[], Any] | None = None
    # Further client kinds an app adds (E23 ``accounting``), each with its fake twin.
    clients: dict[str, Callable[[], Any]] = field(default_factory=dict)
    fake_clients: dict[str, Callable[[], Any]] = field(default_factory=dict)
    # A light call proving the credentials work (used by ``services.check``).
    health: Callable[[Credentials], Any] | None = None


_providers: dict[str, Provider] = {}

# Video providers offered for lessons, and the connected account each one needs
# (``builtin`` rooms run on TutorTrack's own Daily.co/Whereby account).
VIDEO_PROVIDERS: dict[str, str | None] = {
    "builtin": None,
    "zoom": "zoom",
    "teams": "microsoft",
    "google_meet": "google",
    "lessonspace": "lessonspace",
}


def register(provider: Provider) -> Provider:
    _providers[provider.spec.key] = provider
    return provider


def _get(key: str) -> Provider:
    try:
        return _providers[key]
    except KeyError:
        raise ConfigurationError(f"Unknown provider {key!r}.") from None


def get_spec(key: str) -> ProviderSpec:
    return _get(key).spec


def all_specs() -> list[ProviderSpec]:
    return [p.spec for p in _providers.values()]


def is_fake(key: str) -> bool:
    if key == "builtin":
        return not _builtin_key()
    return not _get(key).live()


def scopes(key: str) -> tuple[str, ...]:
    return _get(key).scopes


def _client(key: str, kind: str) -> Any:
    provider = _get(key)
    if kind in provider.clients:
        return client(key, kind)
    factory = getattr(provider, kind)
    if factory is None:
        raise ConfigurationError(f"{provider.spec.label} can't do that.")
    if not provider.live():
        from . import fake

        return {
            "oauth": lambda: fake.FakeOAuth(key),
            "credentials": lambda: fake.FakeCredentials(key),
            "calendar": lambda: fake.FakeCalendarClient(key, push=key != "caldav"),
            "meetings": lambda: fake.FakeMeetings(provider.spec.video_key or key),
        }[kind]()
    return factory()


def client(key: str, kind: str) -> Any:
    """A client of an app-defined kind (e.g. ``accounting``); the fake twin when the
    provider's platform keys are empty."""
    provider = _get(key)
    if kind not in provider.clients:
        raise ConfigurationError(f"{provider.spec.label} can't do that.")
    if not provider.live():
        return provider.fake_clients[kind]()
    return provider.clients[kind]()


def health_check(key: str, creds: Credentials) -> bool:
    """Run the provider's health call; False if it has none."""
    provider = _get(key)
    if provider.health is None:
        return False
    provider.health(creds)
    return True


def oauth_client(key: str) -> OAuthClient:
    client: OAuthClient = _client(key, "oauth")
    return client


def credential_client(key: str) -> CredentialClient:
    client: CredentialClient = _client(key, "credentials")
    return client


def calendar_client(key: str) -> CalendarClient:
    client: CalendarClient = _client(key, "calendar")
    return client


def _builtin_key() -> str:
    config = settings.INTEGRATIONS
    return str(
        config["WHEREBY_API_KEY"] if builtin_rooms() == "whereby" else config["DAILY_API_KEY"]
    )


def builtin_rooms() -> str:
    return "whereby" if settings.INTEGRATIONS["BUILTIN_ROOMS"] == "whereby" else "daily"


def meeting_client(video_provider: str) -> MeetingClient:
    """The client for a *video* provider key (``zoom``, ``teams``, ``builtin``...)."""
    from . import fake

    if video_provider == "builtin":
        if not _builtin_key():
            return fake.FakeMeetings("builtin")
        from .video import DailyRooms, WherebyRooms

        return WherebyRooms() if builtin_rooms() == "whereby" else DailyRooms()
    account = VIDEO_PROVIDERS.get(video_provider)
    if account is None:
        raise ConfigurationError(f"Unknown video provider {video_provider!r}.")
    provider = _get(account)
    if not provider.live():
        return fake.FakeMeetings(video_provider)
    client: MeetingClient = provider.meetings()  # type: ignore[misc]
    return client


# --- built-in providers --------------------------------------------------------------------------


def _keys(*names: str) -> Callable[[], bool]:
    return lambda: all(settings.INTEGRATIONS[n] for n in names)


def _credential_live() -> bool:
    return bool(settings.INTEGRATIONS["CREDENTIAL_PROVIDERS_LIVE"])


def _google_oauth() -> Any:
    from .google import oauth_client as make

    return make()


def _google_calendar() -> Any:
    from .google import GoogleCalendar

    return GoogleCalendar()


def _google_meet() -> Any:
    from .google import GoogleMeet

    return GoogleMeet()


def _ms_oauth() -> Any:
    from .microsoft import oauth_client as make

    return make()


def _ms_calendar() -> Any:
    from .microsoft import GraphCalendar

    return GraphCalendar()


def _teams() -> Any:
    from .microsoft import TeamsMeetings

    return TeamsMeetings()


def _caldav() -> Any:
    from .caldav import CalDAVClient

    return CalDAVClient()


def _zoom_oauth() -> Any:
    from .video import zoom_oauth_client

    return zoom_oauth_client()


def _zoom() -> Any:
    from .video import ZoomMeetings

    return ZoomMeetings()


def _lessonspace() -> Any:
    from .video import LessonspaceMeetings

    return LessonspaceMeetings()


def _scopes(module: str, name: str) -> tuple[str, ...]:
    import importlib

    found: tuple[str, ...] = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    return found


register(
    Provider(
        ProviderSpec(
            "google",
            "Google Calendar and Meet",
            frozenset({"calendar", "video"}),
            "oauth2",
            ("user",),
            video_key="google_meet",
            poll_minutes=5,
        ),
        live=_keys("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        scopes=_scopes("google", "SCOPES"),
        oauth=_google_oauth,
        calendar=_google_calendar,
        meetings=_google_meet,
    )
)
register(
    Provider(
        ProviderSpec(
            "microsoft",
            "Microsoft 365 (Outlook and Teams)",
            frozenset({"calendar", "video"}),
            "oauth2",
            ("user",),
            video_key="teams",
            poll_minutes=5,
        ),
        live=_keys("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"),
        scopes=_scopes("microsoft", "SCOPES"),
        oauth=_ms_oauth,
        calendar=_ms_calendar,
        meetings=_teams,
    )
)
register(
    Provider(
        ProviderSpec(
            "caldav",
            "Apple iCloud (CalDAV)",
            frozenset({"calendar"}),
            "credentials",
            ("user",),
            credential_fields=("username", "password", "server_url"),
            poll_minutes=10,
        ),
        live=_credential_live,
        credentials=_caldav,
        calendar=_caldav,
    )
)
register(
    Provider(
        ProviderSpec(
            "zoom",
            "Zoom",
            frozenset({"video"}),
            "oauth2",
            ("user", "organisation"),
            video_key="zoom",
        ),
        live=_keys("ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"),
        scopes=_scopes("video", "ZOOM_SCOPES"),
        oauth=_zoom_oauth,
        meetings=_zoom,
    )
)
register(
    Provider(
        ProviderSpec(
            "lessonspace",
            "Lessonspace",
            frozenset({"video"}),
            "credentials",
            ("organisation",),
            credential_fields=("api_key",),
            video_key="lessonspace",
        ),
        live=_credential_live,
        credentials=_lessonspace,
        meetings=_lessonspace,
    )
)
