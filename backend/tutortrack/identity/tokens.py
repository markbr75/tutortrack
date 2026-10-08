"""Signed, expiring tokens for email verification and cross-host session handoff.

* Email verification: valid for ``EMAIL_VERIFICATION_MAX_AGE_SECONDS`` and bound to the
  address it was sent to (changing email invalidates it).
* Session handoff: after signup on the root app the user continues on their new
  organisation's subdomain. Where cookies cannot be shared between the two hosts (local
  development, custom domains) the app exchanges this token for a session on the tenant
  host. It is short-lived (2 minutes), bound to one organisation and single-use.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core import signing
from django.core.cache import cache

from .models import User

EMAIL_SALT = "tutortrack.identity.email-verification"
HANDOFF_SALT = "tutortrack.identity.session-handoff"
HANDOFF_MAX_AGE = 120


class InvalidToken(Exception):
    pass


def email_verification_token(user: User) -> str:
    return signing.dumps({"u": str(user.pk), "e": user.email}, salt=EMAIL_SALT, compress=True)


def user_from_email_token(token: str) -> User:
    try:
        data: dict[str, Any] = signing.loads(
            token, salt=EMAIL_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS
        )
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise InvalidToken from exc
    user = User.objects.filter(pk=str(data.get("u", "")), is_active=True).first()
    if user is None or user.email != data.get("e"):
        raise InvalidToken
    return user


def handoff_token(user: User, organisation_id: uuid.UUID) -> str:
    payload = {"u": str(user.pk), "o": str(organisation_id), "j": uuid.uuid4().hex}
    return signing.dumps(payload, salt=HANDOFF_SALT, compress=True)


def consume_handoff_token(token: str, organisation_id: uuid.UUID) -> User:
    try:
        data: dict[str, Any] = signing.loads(token, salt=HANDOFF_SALT, max_age=HANDOFF_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidToken from exc
    if data.get("o") != str(organisation_id):
        raise InvalidToken
    # cache.add is atomic: only the first exchange of a token succeeds.
    if not cache.add(f"handoff:{data.get('j')}", 1, HANDOFF_MAX_AGE * 2):
        raise InvalidToken
    user = User.objects.filter(pk=str(data.get("u", "")), is_active=True).first()
    if user is None:
        raise InvalidToken
    return user
