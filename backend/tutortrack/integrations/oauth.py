"""OAuth2 authorization code + PKCE for connecting accounts (E22-T01).

Flow:
1. ``POST /api/v1/integrations/oauth/start`` (tenant host, signed in) returns the
   provider's authorization URL. ``state`` is a signed, short-lived token
   ``{nonce, org, user, provider, level, next}``; the PKCE verifier is derived from the
   nonce with an HMAC of ``SECRET_KEY``, so nothing is stored and the verifier never
   travels through the browser.
2. The provider redirects to the fixed callback on the root app host (the only URL that
   can be registered with providers). It checks the signature and forwards the browser to
   the organisation's app (``next``) with ``code`` and ``state``.
3. The app posts both to ``/oauth/complete`` on the tenant host. The signed-in user and
   organisation must be the ones in ``state`` (so a link started by someone else can't
   attach their account to you, or yours to them), then the code is exchanged.

The same pattern as ``identity.sso`` (signed state, PKCE S256), without a cookie: the
connection is bound to the signed-in session at step 3 instead.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core import signing

STATE_SALT = "tutortrack.integrations.oauth-state"
STATE_MAX_AGE = 900


class OAuthStateError(Exception):
    pass


@dataclass(frozen=True)
class State:
    nonce: str
    organisation_id: str
    user_id: str
    provider: str
    level: str
    next_path: str


def callback_url() -> str:
    return f"{settings.APP_URL}/api/v1/integrations/oauth/callback"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def verifier_for(nonce: str) -> str:
    digest = hmac.new(settings.SECRET_KEY.encode(), f"pkce:{nonce}".encode(), hashlib.sha256)
    return _b64(digest.digest() + digest.digest()[:8])  # 54 chars: within RFC 7636's 43-128


def challenge_for(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode()).digest())


def safe_next(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/"


def make_state(
    *, organisation_id: Any, user_id: Any, provider: str, level: str, next_path: str
) -> tuple[str, State]:
    state = State(
        nonce=secrets.token_urlsafe(18),
        organisation_id=str(organisation_id),
        user_id=str(user_id),
        provider=provider,
        level=level,
        next_path=safe_next(next_path),
    )
    token = signing.dumps(
        {
            "n": state.nonce,
            "o": state.organisation_id,
            "u": state.user_id,
            "p": provider,
            "l": level,
            "x": state.next_path,
        },
        salt=STATE_SALT,
        compress=True,
    )
    return token, state


def read_state(token: str) -> State:
    try:
        data: dict[str, Any] = signing.loads(token, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise OAuthStateError("state") from exc
    return State(
        nonce=str(data["n"]),
        organisation_id=str(data["o"]),
        user_id=str(data["u"]),
        provider=str(data["p"]),
        level=str(data["l"]),
        next_path=safe_next(str(data.get("x", "/"))),
    )
