"""Tenant branding for emails, documents and public pages (E24 FR-24-1).

Apps that render tenant-facing output (comms emails, billing and payments PDFs) ask this
module instead of depending on the sites app, which registers the provider at start-up.
Until then (and for organisations without a brand kit) the platform defaults apply::

    from tutortrack.core import branding

    brand = branding.for_email()          # {"name", "primary_colour", "logo_url", ...}
    brand = branding.for_documents()      # + "logo_data_uri" for WeasyPrint
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from .context import current_organisation_id

DEFAULT_PRIMARY = "#2563eb"
DEFAULT_TEXT = "#111827"


class Provider(Protocol):
    def for_email(self, organisation_id: uuid.UUID, branch_id: Any = None) -> dict[str, Any]: ...

    def for_documents(
        self, organisation_id: uuid.UUID, branch_id: Any = None
    ) -> dict[str, Any]: ...


class _Defaults:
    def for_email(self, organisation_id: uuid.UUID, branch_id: Any = None) -> dict[str, Any]:
        return defaults()

    def for_documents(self, organisation_id: uuid.UUID, branch_id: Any = None) -> dict[str, Any]:
        return defaults()


def defaults() -> dict[str, Any]:
    return {
        "primary_colour": DEFAULT_PRIMARY,
        "on_primary": "#ffffff",
        "logo_url": "",
        "logo_data_uri": "",
        "header": "",
        "footer": "",
        "show_powered_by": True,
        "font": "",
    }


_provider: Provider = _Defaults()


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def for_email(organisation_id: uuid.UUID | None = None, branch_id: Any = None) -> dict[str, Any]:
    org = organisation_id or current_organisation_id()
    if org is None:
        return defaults()
    return {**defaults(), **_provider.for_email(org, branch_id)}


def for_documents(
    organisation_id: uuid.UUID | None = None, branch_id: Any = None
) -> dict[str, Any]:
    org = organisation_id or current_organisation_id()
    if org is None:
        return defaults()
    return {**defaults(), **_provider.for_documents(org, branch_id)}
