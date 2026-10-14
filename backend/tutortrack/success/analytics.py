"""First-party product analytics (E30 FR-30-6, ADR 0030).

The admin app sends feature-usage events (page views, feature use, tour and checklist
steps) to ``POST /api/v1/analytics/events``. Nothing is recorded unless *all* of these
hold:

* the person chose "analytics" in the cookie banner / help panel (``tt_consent`` cookie,
  E29 FR-29-3) - the browser also sends nothing without it;
* the organisation allows it (``privacy.product_analytics``);
* the person is staff (portal families and students are never tracked: AADC "no profiling"
  for children) and is not a support engineer viewing as them.

Events are pseudonymous: the actor is a keyed hash of (organisation, user), routes are
patterns (ids replaced), and properties are short scalars whose keys and values are
filtered so names, emails, phone numbers, ids and free text never get through.

Sinks are the provider seam: ``PRODUCT_ANALYTICS_SINKS`` (dotted paths) receive every
accepted batch. The default stores ``ProductEvent`` rows for the platform console; an
exporter for an external tool (PostHog, Segment...) is another sink.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import unquote

from django.conf import settings
from django.utils.crypto import salted_hmac
from django.utils.module_loading import import_string

from tutortrack.core.time import now

CONSENT_COOKIE = "tt_consent"
CONSENT_VERSION = 1
DEFAULT_SINKS = ["tutortrack.success.analytics.DatabaseSink"]
MAX_BATCH = 50
MAX_PROPERTIES = 10
MAX_STRING = 64

NAME = re.compile(r"^[a-z][a-z_]{0,29}(\.[a-z][a-z_]{0,29}){1,2}$")
KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
LONG_NUMBER = re.compile(r"\d[\d\s\-()+.]{5,}\d")
TOKEN = re.compile(r"[A-Za-z0-9_\-]{24,}")
SEGMENT_ID = re.compile(r"^(\d+|[0-9a-f\-]{16,}|[A-Za-z0-9_\-]{24,})$", re.I)
# Key words that would name a person or carry their words, whatever the value looks like.
BLOCKED_KEY_WORDS = frozenset(
    {
        "name",
        "first",
        "last",
        "surname",
        "email",
        "phone",
        "mobile",
        "address",
        "postcode",
        "dob",
        "birth",
        "text",
        "comment",
        "message",
        "note",
        "notes",
        "body",
        "search",
        "query",
        "password",
        "token",
        "secret",
        "ip",
        "user",
        "username",
    }
)


@dataclass(frozen=True)
class CapturedEvent:
    organisation_id: str
    actor: str
    name: str
    route: str
    properties: dict[str, Any]
    occurred_at: datetime


class Sink(Protocol):
    def emit(self, events: list[CapturedEvent]) -> None: ...


class DatabaseSink:
    """Stores the events for the platform console (feature usage, funnels, health)."""

    def emit(self, events: list[CapturedEvent]) -> None:
        from .models import ProductEvent

        ProductEvent.objects.bulk_create(
            ProductEvent(
                organisation_id=e.organisation_id,
                actor=e.actor,
                name=e.name,
                route=e.route,
                properties=e.properties,
                occurred_at=e.occurred_at,
            )
            for e in events
        )


def sinks() -> list[Sink]:
    paths = getattr(settings, "PRODUCT_ANALYTICS_SINKS", DEFAULT_SINKS)
    return [import_string(path)() for path in paths]


def pseudonym(organisation_id: Any, user_id: Any) -> str:
    """Stable per person and organisation, not reversible without the server's key."""
    value = f"{organisation_id}:{user_id}"
    return salted_hmac("tutortrack.success.analytics", value).hexdigest()[:32]


def consented(cookies: dict[str, str]) -> bool:
    raw = cookies.get(CONSENT_COOKIE)
    if not raw:
        return False
    try:
        choice = json.loads(unquote(raw))
    except (ValueError, TypeError):
        return False
    return (
        isinstance(choice, dict)
        and choice.get("version") == CONSENT_VERSION
        and choice.get("analytics") is True
    )


def clean_route(route: Any) -> str:
    """A route pattern: path only, record ids replaced by ``$id``."""
    if not isinstance(route, str):
        return ""
    path = route.split("?", 1)[0].split("#", 1)[0][:200]
    if not path.startswith("/"):
        return ""
    parts = []
    for segment in path.split("/")[1:]:
        if not segment:
            continue
        if segment.startswith("$"):
            parts.append(segment[:20])
        elif SEGMENT_ID.match(segment) or "@" in segment or not re.match(r"^[\w\-]+$", segment):
            parts.append("$id")
        else:
            parts.append(segment[:30].lower())
    return ("/" + "/".join(parts))[:120]


def _clean_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value if abs(value) < 10**9 else None
    if isinstance(value, float):
        return round(value, 3) if abs(value) < 10**9 else None
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > MAX_STRING or "@" in text:
            return None
        if UUID.search(text) or LONG_NUMBER.search(text) or TOKEN.search(text):
            return None
        if " " in text.strip() and len(text.split()) > 3:
            return None  # looks like free text
        return text
    return None


def clean_properties(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if len(out) >= MAX_PROPERTIES:
            break
        if (
            not isinstance(key, str)
            or not KEY.match(key)
            or BLOCKED_KEY_WORDS & set(key.split("_"))
        ):
            continue
        cleaned = _clean_value(value)
        if cleaned is not None or value is None:
            out[key] = cleaned
    return out


def _occurred_at(value: Any, received: datetime) -> datetime:
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None or parsed.tzinfo is None:
        return received
    return min(max(parsed, received - timedelta(days=1)), received)


def build(
    organisation_id: Any, user_id: Any, raw_events: Iterable[dict[str, Any]]
) -> list[CapturedEvent]:
    received = now()
    actor = pseudonym(organisation_id, user_id)
    out = []
    for raw in list(raw_events)[:MAX_BATCH]:
        name = raw.get("name")
        if not isinstance(name, str) or not NAME.match(name):
            continue
        out.append(
            CapturedEvent(
                organisation_id=str(organisation_id),
                actor=actor,
                name=name,
                route=clean_route(raw.get("route")),
                properties=clean_properties(raw.get("properties")),
                occurred_at=_occurred_at(raw.get("occurred_at"), received),
            )
        )
    return out


def emit(events: list[CapturedEvent]) -> None:
    if events:
        for sink in sinks():
            sink.emit(events)
