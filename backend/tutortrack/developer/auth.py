"""Bearer-token authentication for the public API (FR-27-2, E27-T01/T02).

``ApiTokenMiddleware`` sits after Django's session authentication and before the tenant
middleware. For ``Authorization: Bearer <token>`` it:

1. finds the organisation from the token prefix (``CredentialRoute``) and checks the key or
   OAuth access token inside that tenant (hash, expiry, revocation, IP allowlist, the
   acting user still an active member);
2. sets ``request.user`` to the token's user with ``token_permissions`` = the patterns its
   scopes cover (``core.permissions.has_perm`` intersects them with the user's role);
3. applies the per-token rate limit and adds ``X-RateLimit-*`` headers;
4. in ``process_view`` refuses internal endpoints and endpoints whose resource the token
   has no scope for, and narrows branch-scoped keys to their branch.

``resolve`` (``settings.TENANT_RESOLVER``) makes the token's organisation the tenant, and
``ApiTokenAuthentication`` hands the user to DRF without the session/CSRF machinery.
Session-authenticated requests are untouched.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import structlog
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from tutortrack.core.context import (
    current_branch_ids,
    get_request_context,
    set_branch_ids,
    tenant_context,
)
from tutortrack.core.middleware import client_ip
from tutortrack.core.time import now

from . import deprecations, ratelimit, scopes, tokens
from .models import CredentialKind

logger = structlog.get_logger(__name__)
GetResponse = Callable[[HttpRequest], HttpResponse]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOUCH_INTERVAL = timedelta(minutes=1)
# OAuth endpoints authenticate the *client*, not a bearer token.
UNAUTHENTICATED_PATHS = ("/api/v1/oauth/token", "/api/v1/oauth/revoke")


@dataclass
class Credential:
    """What a valid bearer token stands for during one request."""

    kind: str  # api_key | access
    id: uuid.UUID
    prefix: str
    name: str
    organisation_id: uuid.UUID
    user: Any
    scopes: tuple[str, ...]
    branch_id: uuid.UUID | None = None
    rate_limit_per_minute: int | None = None
    application_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def has_scope(self, resource: str, write: bool) -> bool:
        return scopes.has_scope(self.scopes, resource, write)


@dataclass(frozen=True)
class AuthFailure:
    code: str
    detail: str


def _ip_allowed(ip: str | None, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _api_key(prefix: str, raw: str, ip: str | None) -> Credential | AuthFailure:
    from .models import ApiKey

    key = ApiKey.objects.select_related("user").filter(prefix=prefix).first()
    if key is None or not tokens.matches(raw, key.secret_hash):
        return AuthFailure("invalid-token", "The API key is not valid.")
    current = now()
    if key.revoked_at is not None:
        return AuthFailure("invalid-token", "The API key has been revoked.")
    if key.expires_at is not None and key.expires_at <= current:
        return AuthFailure("invalid-token", "The API key has expired.")
    if not _ip_allowed(ip, list(key.ip_allowlist or [])):
        return AuthFailure("ip-not-allowed", "Requests from this IP address are not allowed.")
    if key.last_used_at is None or current - key.last_used_at > TOUCH_INTERVAL:
        ApiKey.objects.filter(pk=key.pk).update(last_used_at=current, last_used_ip=ip)
    return Credential(
        kind=CredentialKind.API_KEY,
        id=key.pk,
        prefix=key.prefix,
        name=key.name,
        organisation_id=key.organisation_id,
        user=key.user,
        scopes=tuple(key.scopes or ()),
        branch_id=key.branch_id,
        rate_limit_per_minute=key.rate_limit_per_minute,
    )


def _access_token(prefix: str, raw: str) -> Credential | AuthFailure:
    from .models import OAuthGrant, OAuthToken

    token = (
        OAuthToken.objects.select_related("grant__user", "grant__application")
        .filter(prefix=prefix, kind=CredentialKind.ACCESS_TOKEN)
        .first()
    )
    if token is None or not tokens.matches(raw, token.secret_hash):
        return AuthFailure("invalid-token", "The access token is not valid.")
    current = now()
    grant = token.grant
    if (
        token.revoked_at is not None
        or token.expires_at <= current
        or grant.revoked_at is not None
        or grant.application.revoked_at is not None
    ):
        return AuthFailure("invalid-token", "The access token has expired or been revoked.")
    if grant.last_used_at is None or current - grant.last_used_at > TOUCH_INTERVAL:
        OAuthGrant.objects.filter(pk=grant.pk).update(last_used_at=current)
    return Credential(
        kind=CredentialKind.ACCESS_TOKEN,
        id=token.pk,
        prefix=token.prefix,
        name=grant.application.name,
        organisation_id=token.organisation_id,
        user=grant.user,
        scopes=tuple(token.scopes or ()),
        application_id=grant.application_id,
    )


def authenticate_token(raw: str, ip: str | None = None) -> Credential | AuthFailure:
    """Check a bearer token. Never raises for bad input; returns ``AuthFailure`` instead."""
    from tutortrack.identity.selectors import branch_ids_for, membership_for

    from .models import CredentialRoute

    parsed = tokens.parse(raw)
    if parsed is None or parsed.kind not in (CredentialKind.API_KEY, CredentialKind.ACCESS_TOKEN):
        return AuthFailure("invalid-token", "The token is malformed.")
    route = CredentialRoute.objects.filter(prefix=parsed.prefix, kind=parsed.kind).first()
    if route is None:
        return AuthFailure("invalid-token", "The token is not valid.")
    with tenant_context(route.organisation_id):
        result = (
            _api_key(parsed.prefix, parsed.token, ip)
            if parsed.kind == CredentialKind.API_KEY
            else _access_token(parsed.prefix, parsed.token)
        )
        if isinstance(result, AuthFailure):
            return result
        user = result.user
        membership = membership_for(user, route.organisation_id) if user.is_active else None
        if membership is None:
            return AuthFailure("invalid-token", "The token's user is no longer a member.")
        if result.branch_id is not None:
            allowed = branch_ids_for(membership)
            if allowed is not None and result.branch_id not in allowed:
                return AuthFailure("invalid-token", "The token's branch is not available.")
    # has_perm intersects role grants with these patterns (core.permissions).
    user.token_permissions = scopes.permission_patterns(result.scopes)
    return result


def _problem(
    status: int, code: str, title: str, detail: str, headers: dict[str, str] | None = None,
    **extra: Any,
) -> JsonResponse:  # fmt: skip
    body: dict[str, Any] = {
        **extra,
        "type": f"https://docs.tutortrack.app/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    request_id = get_request_context().request_id
    if request_id:
        body["request_id"] = request_id
    response = JsonResponse(body, status=status, content_type="application/problem+json")
    for name, value in (headers or {}).items():
        response[name] = value
    return response


class ApiTokenMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        header = request.headers.get("Authorization", "")
        scheme, _sep, raw = header.partition(" ")
        if (
            scheme.lower() != "bearer"
            or not raw.strip()
            or not request.path.startswith("/api/")
            or request.path.startswith(UNAUTHENTICATED_PATHS)
        ):
            response = self.get_response(request)
            return self._with_deprecation(request, response)

        result = authenticate_token(raw.strip(), client_ip(request))
        if isinstance(result, AuthFailure):
            return _problem(
                401, result.code, "Invalid credentials", result.detail,
                {"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )  # fmt: skip
        request.api_credential = result  # type: ignore[attr-defined]
        request.user = result.user
        request._dont_enforce_csrf_checks = True  # type: ignore[attr-defined]
        structlog.contextvars.bind_contextvars(api_credential=f"{result.kind}:{result.prefix}")

        verdict = ratelimit.hit(result.prefix, result.rate_limit_per_minute)
        if verdict.exceeded:
            return _problem(
                429,
                "rate-limited",
                "Too many requests",
                "This token has made too many requests. Retry after the indicated time.",
                verdict.headers(),
            )
        response = self.get_response(request)
        for name, value in verdict.headers().items():
            response[name] = value
        return self._with_deprecation(request, response)

    @staticmethod
    def _with_deprecation(request: HttpRequest, response: HttpResponse) -> HttpResponse:
        deprecation = getattr(request, "_tt_deprecation", None)
        if deprecation is not None:
            for name, value in deprecation.headers().items():
                response[name] = value
        return response

    def process_view(
        self, request: HttpRequest, view_func: Any, view_args: Any, view_kwargs: Any
    ) -> HttpResponse | None:
        view_class = getattr(view_func, "cls", None)
        request._tt_deprecation = deprecations.for_view(view_class)  # type: ignore[attr-defined]
        credential: Credential | None = getattr(request, "api_credential", None)
        if credential is None:
            return None
        resource = scopes.resource_for(view_class)
        if resource is None:
            return _problem(
                403,
                "endpoint-not-public",
                "Not available to API tokens",
                "This endpoint is internal to TutorTrack's own apps.",
            )
        write = (request.method or "GET") not in SAFE_METHODS
        if not credential.has_scope(resource, write):
            needed = f"{resource}:{'write' if write else 'read'}"
            return _problem(
                403,
                "insufficient-scope",
                "Insufficient scope",
                f"This request needs the {needed} scope.",
                {"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{needed}"'},
                required_scope=needed,
            )
        if credential.branch_id is not None:
            visible = current_branch_ids()
            if visible is None or credential.branch_id in visible:
                set_branch_ids({credential.branch_id})  # TenantMiddleware resets it
            else:
                set_branch_ids(set())
        return None


class ApiTokenAuthentication(BaseAuthentication):
    """Hands the middleware's token user to DRF (first in the authentication classes, so
    token requests never fall through to session authentication and its CSRF check)."""

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        credential = getattr(request._request, "api_credential", None)
        if credential is None:
            return None
        return credential.user, credential


def resolve(request: HttpRequest) -> Any:
    """Tenant resolver: a token's organisation is the tenant. A token used on another
    organisation's address resolves to "unknown" (404), never to the other tenant."""
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.resolution import Resolution
    from tutortrack.tenancy.resolution import resolve as default_resolve

    credential: Credential | None = getattr(request, "api_credential", None)
    if credential is None:
        return default_resolve(request)
    resolution = default_resolve(request)
    if resolution.unknown:
        return resolution
    if resolution.via in ("custom_domain", "subdomain", "header") and (
        resolution.organisation is not None
        and resolution.organisation.pk != credential.organisation_id
    ):
        return Resolution(unknown=True)
    organisation = Organisation.objects.filter(pk=credential.organisation_id).first()
    if organisation is None:
        return Resolution(unknown=True)
    return Resolution(organisation, via="api_token")
