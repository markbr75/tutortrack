"""Competitor connectors (FR-28-3, FR-28-5) on the E22 integration framework.

TutorCruncher and Teachworks are registered as organisation-level ``credentials``
providers with a ``migration`` client kind; the API key is verified and stored encrypted
on the framework's ``IntegrationConnection``. Without live credential providers (dev,
tests) each gets a fake twin that serves a realistic sample account.

A source turns the competitor's records into rows keyed by *our* import fields, so pulled
data goes through exactly the same validation, dry run, import and rollback as a file.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any, Protocol

from tutortrack.integrations.providers import AccountInfo, Credentials

CAPABILITY = "migration"


class MigrationSource(Protocol):
    provider: str

    def supports(self, entity: str) -> bool: ...

    def verify(self, credentials: Credentials) -> AccountInfo: ...

    def fetch(
        self, credentials: Credentials, entity: str, *, cutover: date
    ) -> Iterator[dict[str, Any]]: ...

    def totals(self, credentials: Credentials, *, cutover: date) -> dict[str, Any]: ...


def source_for(provider: str) -> MigrationSource:
    from tutortrack.integrations import providers as registry

    found: MigrationSource = registry.client(provider, CAPABILITY)
    return found


def credentials(connection: Any) -> Credentials:
    from tutortrack.integrations import services as integrations

    return integrations.credentials(connection)


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def joined(items: Iterable[Any]) -> str:
    return "; ".join(text(i) for i in items if text(i))
