"""Webhook routing and signed callback tokens shared by the Phase 3 integrations (E12 Wise,
E18 background checks, E22 video attendance).

* ``remember(provider, external_id)`` records which organisation owns an external id, so
  a platform-level webhook (Zoom, Wise, Checkr) can be routed; ``organisation_for`` reads
  it back (the only lookup made outside a tenant).
* ``callback_token``/``read_callback_token``: an HMAC token naming the organisation and a
  record, for providers that call a URL we give them per record (Lessonspace webhooks).
  Verifiable before any database lookup.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any

from django.conf import settings

from tutortrack.core.context import require_organisation_id

from .models import WebhookRoute


def remember(provider: str, external_id: str, organisation_id: Any = None) -> None:
    if not external_id:
        return
    org = organisation_id or require_organisation_id()
    WebhookRoute.objects.update_or_create(
        provider=provider, external_id=str(external_id)[:255], defaults={"organisation_id": org}
    )


def organisation_for(provider: str, external_id: str) -> str | None:
    route = WebhookRoute.objects.filter(provider=provider, external_id=str(external_id)).first()
    return str(route.organisation_id) if route else None


def _mac(purpose: str, org: str, ref: str) -> str:
    message = f"{purpose}:{org}:{ref}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:32]


def callback_token(purpose: str, organisation_id: Any, ref: Any) -> str:
    org, record = uuid.UUID(str(organisation_id)).hex, uuid.UUID(str(ref)).hex
    return f"{org}.{record}.{_mac(purpose, org, record)}"


def read_callback_token(purpose: str, token: str) -> tuple[str, str] | None:
    try:
        org, record, mac = token.split(".")
        expected = _mac(purpose, uuid.UUID(org).hex, uuid.UUID(record).hex)
    except ValueError:
        return None
    if not hmac.compare_digest(mac, expected):
        return None
    return str(uuid.UUID(org)), str(uuid.UUID(record))


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_hmac(secret: str, message: bytes, signature: str, *, prefix: str = "") -> bool:
    """Constant-time check of a hex HMAC-SHA256 signature (optionally prefixed, Zoom's
    ``v0=``). An empty secret never verifies."""
    if not secret or not signature:
        return False
    return hmac.compare_digest(f"{prefix}{hmac_hex(secret, message)}", signature.strip())
