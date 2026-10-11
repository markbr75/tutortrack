"""Registers the migration sources and Google Sheets with the integration framework."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from tutortrack.integrations import providers as registry
from tutortrack.integrations.providers import Credentials, Provider, ProviderSpec

from .base import CAPABILITY

MANAGE = "migration.project.manage"


def _credential_live() -> bool:
    return bool(settings.INTEGRATIONS.get("CREDENTIAL_PROVIDERS_LIVE"))


def _tutorcruncher() -> Any:
    from .tutorcruncher import TutorCruncherSource

    return TutorCruncherSource()


def _teachworks() -> Any:
    from .teachworks import TeachworksSource

    return TeachworksSource()


def _fake(name: str) -> Any:
    def make() -> Any:
        from . import fake

        return getattr(fake, f"fake_{name}")()

    return make


def _health(provider: str) -> Any:
    def check(creds: Credentials) -> None:
        registry.client(provider, CAPABILITY).verify(creds)

    return check


for _key, _label, _live_factory in (
    ("tutorcruncher", "TutorCruncher", _tutorcruncher),
    ("teachworks", "Teachworks", _teachworks),
):
    registry.register(
        Provider(
            ProviderSpec(
                _key,
                _label,
                frozenset({CAPABILITY}),
                "credentials",
                ("organisation",),
                credential_fields=("api_key",),
                manage_permission=MANAGE,
            ),
            live=_credential_live,
            credentials=_live_factory,  # verify() checks the key with a light list call
            clients={CAPABILITY: _live_factory},
            fake_clients={CAPABILITY: _fake(_key)},
            health=_health(_key),
        )
    )


def _sheets_oauth() -> Any:
    from tutortrack.integrations.providers.google import oauth_client

    client = oauth_client()
    from dataclasses import replace

    return replace(client, provider="google_sheets")


def _sheets() -> Any:
    from .sheets import SheetsClient

    return SheetsClient()


def _fake_sheets() -> Any:
    from .sheets import FakeSheetsClient

    return FakeSheetsClient()


registry.register(
    Provider(
        ProviderSpec(
            "google_sheets",
            "Google Sheets (read-only, for imports)",
            frozenset({"sheets"}),
            "oauth2",
            ("user",),
        ),
        live=lambda: bool(
            settings.INTEGRATIONS.get("GOOGLE_CLIENT_ID")
            and settings.INTEGRATIONS.get("GOOGLE_CLIENT_SECRET")
        ),
        scopes=("openid", "email", "https://www.googleapis.com/auth/spreadsheets.readonly"),
        oauth=_sheets_oauth,
        clients={"sheets": _sheets},
        fake_clients={"sheets": _fake_sheets},
    )
)
