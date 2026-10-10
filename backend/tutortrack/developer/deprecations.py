"""API versioning policy (FR-27-1): the major version is in the URI (``/api/v1/``); within v1
changes are additive only. When an endpoint is going away it is listed here, and every
response from it carries ``Deprecation`` (RFC 9745), ``Sunset`` (RFC 8594) and a ``Link`` to
the changelog entry, so integrators see it long before removal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import format_datetime

from .scopes import view_path


@dataclass(frozen=True)
class Deprecation:
    deprecated_on: date
    sunset_on: date
    link: str

    def headers(self) -> dict[str, str]:
        deprecated = datetime.combine(self.deprecated_on, time(), tzinfo=UTC)
        sunset = datetime.combine(self.sunset_on, time(), tzinfo=UTC)
        return {
            "Deprecation": f"@{int(deprecated.timestamp())}",
            "Sunset": format_datetime(sunset, usegmt=True),
            "Link": f'<{self.link}>; rel="deprecation"; type="text/html"',
        }


# View class path (see ``scopes.view_path``) → deprecation. Empty while v1 is current.
DEPRECATIONS: dict[str, Deprecation] = {}


def for_view(view_class: type | None) -> Deprecation | None:
    if view_class is None:
        return None
    return DEPRECATIONS.get(view_path(view_class))
