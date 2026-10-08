"""Cloudflare Turnstile verification for public forms (signup, enquiries...).

With ``TURNSTILE_SECRET_KEY`` unset (local dev, tests) verification is skipped; production
settings refuse to start without it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def turnstile_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def verify_turnstile(token: str, remote_ip: str | None = None) -> bool:
    if not turnstile_enabled():
        return True
    if not token:
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    request = urllib.request.Request(
        VERIFY_URL, data=urllib.parse.urlencode(data).encode(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            body = json.loads(response.read())
    except (OSError, ValueError):
        logger.warning("captcha.turnstile_unavailable")
        return False
    if not body.get("success"):
        logger.info("captcha.turnstile_failed", codes=body.get("error-codes"))
    return bool(body.get("success"))
