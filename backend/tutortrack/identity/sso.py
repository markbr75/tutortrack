"""Google and Microsoft sign-in via OpenID Connect (FR-03-2, E03-T07).

Flow (authorization code + PKCE):
1. ``GET /api/v1/auth/sso/{provider}/start`` on the root app host stores
   ``{state, nonce, verifier, org, next, intent}`` in a signed, short-lived cookie bound to
   this browser and redirects to the provider.
2. The provider redirects to the fixed callback on the root host. We check the state cookie
   (login-CSRF protection), exchange the code, and verify the ID token's signature (JWKS),
   issuer, audience, expiry and nonce.
3. The identity is matched by linked account, then by *verified* email. New users are only
   created when ``intent=signup``. The session starts on the root host; if an organisation
   was requested the browser continues there with a single-use handoff token.

Implemented on PyJWT instead of django-allauth: we only need OIDC for two providers and
allauth brings its own account models and flows that overlap the API-first auth.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import cache
from typing import Any

import jwt
from django.conf import settings
from django.core import signing

from .models import SocialAccount, User

STATE_COOKIE = "tt_sso"
STATE_SALT = "tutortrack.identity.sso-state"
STATE_MAX_AGE = 600


@dataclass(frozen=True)
class Provider:
    key: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuer: str  # may contain {tenantid} (Microsoft multi-tenant)
    client_id: str
    client_secret: str

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)


def providers() -> dict[str, Provider]:
    return {
        "google": Provider(
            key="google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106 - a URL
            jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            issuer="https://accounts.google.com",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
        ),
        "microsoft": Provider(
            key="microsoft",
            authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",  # noqa: S106
            jwks_url="https://login.microsoftonline.com/common/discovery/v2.0/keys",
            issuer="https://login.microsoftonline.com/{tenantid}/v2.0",
            client_id=settings.MICROSOFT_CLIENT_ID,
            client_secret=settings.MICROSOFT_CLIENT_SECRET,
        ),
    }


def get_provider(key: str) -> Provider | None:
    provider = providers().get(key)
    return provider if provider is not None and provider.enabled else None


class SSOError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def callback_url(provider: Provider) -> str:
    return f"{settings.APP_URL}/api/v1/auth/sso/{provider.key}/callback"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def begin(provider: Provider, *, organisation_id: str = "", next_path: str = "/",
          intent: str = "login") -> tuple[str, str]:  # fmt: skip
    """Returns (provider authorization URL, signed state cookie value)."""
    state, nonce, verifier = (secrets.token_urlsafe(24) for _ in range(3))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    cookie = signing.dumps(
        {"s": state, "n": nonce, "v": verifier, "o": organisation_id, "x": safe_next,
         "i": intent if intent in {"login", "signup"} else "login"},
        salt=STATE_SALT,
    )  # fmt: skip
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": callback_url(provider),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{provider.authorize_url}?{urllib.parse.urlencode(params)}", cookie


def read_state(cookie: str, state: str) -> dict[str, Any]:
    try:
        data: dict[str, Any] = signing.loads(cookie, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise SSOError("state") from exc
    if not secrets.compare_digest(str(data.get("s", "")), state):
        raise SSOError("state")
    return data


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - provider URLs are constants
        url, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"Accept": "application/json"},
    )  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body: dict[str, Any] = json.loads(response.read())
            return body
    except (OSError, ValueError) as exc:
        raise SSOError("token_exchange") from exc


@cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_id_token(provider: Provider, id_token: str, nonce: str) -> dict[str, Any]:
    try:
        key = _jwks_client(provider.jwks_url).get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key.key,
            algorithms=["RS256"],
            audience=provider.client_id,
            options={"require": ["exp", "iat", "iss", "sub", "aud"], "verify_iss": False},
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise SSOError("id_token") from exc
    expected_issuer = provider.issuer.replace("{tenantid}", str(claims.get("tid", "")))
    if claims.get("iss") not in {expected_issuer, expected_issuer.replace("https://", "")}:
        raise SSOError("issuer")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SSOError("nonce")
    return claims


def exchange(provider: Provider, code: str, state: dict[str, Any]) -> dict[str, Any]:
    tokens = _post_form(
        provider.token_url,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(provider),
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
            "code_verifier": state["v"],
        },
    )
    if "id_token" not in tokens:
        raise SSOError("token_exchange")
    return verify_id_token(provider, tokens["id_token"], state["n"])


def _email_verified(provider: Provider, claims: dict[str, Any]) -> bool:
    if provider.key == "google":
        return claims.get("email_verified") is True
    # Microsoft personal and work accounts: email claim is managed by the identity provider.
    return bool(claims.get("email")) and claims.get("xms_edov", True) is not False


def match_user(provider: Provider, claims: dict[str, Any], *, intent: str) -> User:
    from tutortrack.core.time import now

    account = (
        SocialAccount.objects.select_related("user")
        .filter(provider=provider.key, subject=str(claims["sub"]))
        .first()
    )
    if account is not None:
        if not account.user.is_active:
            raise SSOError("inactive")
        SocialAccount.objects.filter(pk=account.pk).update(last_login_at=now())
        return account.user
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email or not _email_verified(provider, claims):
        raise SSOError("email_unverified")
    user = User.objects.filter(email=email).first()
    if user is None:
        if intent != "signup":
            raise SSOError("no_account")
        user = User.objects.create_user(
            email,
            None,
            first_name=str(claims.get("given_name", ""))[:100],
            last_name=str(claims.get("family_name", ""))[:100],
        )
    if not user.is_active:
        raise SSOError("inactive")
    if user.email_verified_at is None:
        user.email_verified_at = now()
        user.save(update_fields=["email_verified_at"])
    SocialAccount.objects.create(
        user=user, provider=provider.key, subject=str(claims["sub"]), email=email,
        last_login_at=now(),
    )  # fmt: skip
    return user
