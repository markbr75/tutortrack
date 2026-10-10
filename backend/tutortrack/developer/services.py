"""Developer platform writes (E27): API keys, OAuth2 provider, webhooks, sandboxes.

Every mutation is audited and publishes its domain event inside the transaction. Secrets
(API keys, OAuth client secrets, tokens) are returned once and stored only as SHA-256
hashes; webhook signing secrets are encrypted (they are needed to sign).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import time
import urllib.error
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import structlog
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import branch_scope, require_organisation_id, tenant_context
from tutortrack.core.events import EventEnvelope, publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.time import now
from tutortrack.core.workflows import signal, start

from . import catalogue, events, scopes, signing, tokens
from .models import (
    ApiKey,
    CredentialKind,
    CredentialRoute,
    OAuthApplication,
    OAuthGrant,
    OAuthToken,
    Sandbox,
    WebhookAttempt,
    WebhookDelivery,
    WebhookEndpoint,
)
from .processes import DeliveryInput, WebhookDeliveryWorkflow, delivery_workflow_id

logger = structlog.get_logger(__name__)

AUTO_DISABLE_AFTER = timedelta(days=3)
SECRET_OVERLAP = timedelta(hours=24)
CODE_TTL = timedelta(minutes=10)
SNIPPET_LIMIT = 2000
MAX_SANDBOXES = 3


def _config(key: str, default: Any) -> Any:
    return getattr(settings, "DEVELOPER_API", {}).get(key, default)


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _clean_scopes(values: list[str], field: str = "scopes") -> list[str]:
    try:
        cleaned = scopes.validate_scopes(list(values))
    except ValueError as exc:
        raise _invalid(field, _("Unknown scope: %(s)s") % {"s": exc}) from exc
    if not cleaned:
        raise _invalid(field, _("Choose at least one scope."))
    return cleaned


def _clean_allowlist(values: list[str]) -> list[str]:
    out = []
    for value in values:
        try:
            out.append(str(ipaddress.ip_network(str(value).strip(), strict=False)))
        except ValueError as exc:
            raise _invalid(
                "ip_allowlist", _("%(v)s is not an IP address or range.") % {"v": value}
            ) from exc
    return out


def _route(issued: tokens.IssuedToken) -> None:
    CredentialRoute.objects.create(
        prefix=issued.prefix, kind=issued.kind, organisation_id=require_organisation_id()
    )


# --- API keys (E27-T02) -------------------------------------------------------------------------


@transaction.atomic
def create_api_key(
    *,
    name: str,
    scopes_: list[str],
    user: Any,
    branch: Any = None,
    ip_allowlist: list[str] | None = None,
    expires_at: datetime | None = None,
    rate_limit_per_minute: int | None = None,
    rotated_from: ApiKey | None = None,
) -> tuple[ApiKey, str]:
    """Create a key acting as ``user``. Returns the key and its secret (shown once)."""
    if not name.strip():
        raise _invalid("name", _("Give the key a name."))
    if expires_at is not None and expires_at <= now():
        raise _invalid("expires_at", _("The expiry must be in the future."))
    issued = tokens.issue(CredentialKind.API_KEY)
    key = ApiKey.objects.create(
        name=name.strip(),
        user=user,
        prefix=issued.prefix,
        secret_hash=issued.hash,
        scopes=_clean_scopes(scopes_),
        branch=branch,
        ip_allowlist=_clean_allowlist(ip_allowlist or []),
        expires_at=expires_at,
        rate_limit_per_minute=rate_limit_per_minute,
        rotated_from=rotated_from,
    )
    _route(issued)
    audit.record(key, "create", {"name": [None, key.name], "scopes": [None, key.scopes]})
    publish(
        events.ApiKeyCreated(
            subject_id=key.pk,
            name=key.name,
            scopes=key.scopes,
            rotated_from=str(rotated_from.pk) if rotated_from else None,
        ),
        branch_id=key.branch_id,
    )
    return key, issued.token


@transaction.atomic
def update_api_key(key: ApiKey, **changes: Any) -> ApiKey:
    if key.revoked_at is not None:
        raise BusinessRuleViolation(_("This key has been revoked."))
    with audit.track(key):
        if "name" in changes:
            key.name = str(changes["name"]).strip() or key.name
        if "scopes" in changes:
            key.scopes = _clean_scopes(changes["scopes"])
        if "ip_allowlist" in changes:
            key.ip_allowlist = _clean_allowlist(changes["ip_allowlist"] or [])
        if "expires_at" in changes:
            key.expires_at = changes["expires_at"]
        if "rate_limit_per_minute" in changes:
            key.rate_limit_per_minute = changes["rate_limit_per_minute"]
        key.save()
    return key


@transaction.atomic
def rotate_api_key(key: ApiKey, *, user: Any) -> tuple[ApiKey, str]:
    """A new key with the same settings; the old one keeps working for the overlap period
    (``developer.api_key_rotation_overlap_hours``) so deployments can switch over."""
    key = ApiKey.objects.select_for_update().get(pk=key.pk)
    if key.revoked_at is not None:
        raise BusinessRuleViolation(_("This key has been revoked."))
    new_key, secret = create_api_key(
        name=key.name,
        scopes_=list(key.scopes),
        user=user,
        branch=key.branch,
        ip_allowlist=list(key.ip_allowlist),
        expires_at=key.expires_at if key.expires_at and key.expires_at > now() else None,
        rate_limit_per_minute=key.rate_limit_per_minute,
        rotated_from=key,
    )
    overlap_ends = now() + timedelta(
        hours=int(_setting("developer.api_key_rotation_overlap_hours"))
    )
    with audit.track(key, action="rotate"):
        if key.expires_at is None or key.expires_at > overlap_ends:
            key.expires_at = overlap_ends
        key.save(update_fields=["expires_at", "updated_at"])
    return new_key, secret


@transaction.atomic
def revoke_api_key(key: ApiKey) -> ApiKey:
    if key.revoked_at is not None:
        return key
    with audit.track(key, action="revoke"):
        key.revoked_at = now()
        key.save(update_fields=["revoked_at", "updated_at"])
    publish(events.ApiKeyRevoked(subject_id=key.pk, name=key.name), branch_id=key.branch_id)
    return key


# --- OAuth2 provider (E27-T04) ------------------------------------------------------------------


class OAuthError(Exception):
    """An RFC 6749 error (``invalid_request``, ``invalid_client``, ``invalid_grant``...)."""

    def __init__(self, error: str, description: str = "", status: int = 400):
        self.error = error
        self.description = description
        self.status = status
        super().__init__(f"{error}: {description}")

    def as_dict(self) -> dict[str, str]:
        out = {"error": self.error}
        if self.description:
            out["error_description"] = self.description
        return out


def _clean_redirect_uris(values: list[str]) -> list[str]:
    out = []
    for value in values:
        parts = urlsplit(str(value).strip())
        local = parts.hostname in ("localhost", "127.0.0.1")
        if (
            parts.fragment
            or not parts.hostname
            or (parts.scheme != "https" and not (parts.scheme == "http" and local))
        ):
            raise _invalid(
                "redirect_uris",
                _("%(v)s must be an https URL without a fragment.") % {"v": value},
            )
        out.append(str(value).strip())
    if not out:
        raise _invalid("redirect_uris", _("Add at least one redirect URL."))
    return out


@transaction.atomic
def register_application(
    *,
    name: str,
    redirect_uris: list[str],
    allowed_scopes: list[str],
    confidential: bool = True,
    description: str = "",
    homepage_url: str = "",
    logo_url: str = "",
    user: Any = None,
    partner_key: str = "",
    owner_organisation_id: Any = "current",
    published: bool = False,
) -> tuple[OAuthApplication, str | None]:
    """Register an OAuth client. Tenant apps belong to the organisation in context;
    platform partner apps (Zapier, Make) pass ``owner_organisation_id=None``. Returns the
    app and its client secret (confidential clients only; shown once)."""
    owner = (
        require_organisation_id() if owner_organisation_id == "current" else owner_organisation_id
    )
    secret = tokens.new_client_secret() if confidential else None
    app = OAuthApplication.objects.create(
        name=name.strip(),
        description=description,
        homepage_url=homepage_url,
        logo_url=logo_url,
        client_id=tokens.new_client_id(),
        client_secret_hash=tokens.hash_token(secret) if secret else "",
        confidential=confidential,
        redirect_uris=_clean_redirect_uris(redirect_uris),
        allowed_scopes=_clean_scopes(allowed_scopes, "allowed_scopes"),
        owner_organisation_id=owner,
        partner_key=partner_key,
        published=published,
        created_by=user,
    )
    if owner is not None:
        audit.record(app, "create", {"name": [None, app.name]}, organisation_id=owner)
    return app, secret


def _own_app(app: OAuthApplication) -> None:
    if app.owner_organisation_id != require_organisation_id():
        raise NotFound()


@transaction.atomic
def update_application(app: OAuthApplication, **changes: Any) -> OAuthApplication:
    _own_app(app)
    with audit.track(app):
        for field in ("name", "description", "homepage_url", "logo_url"):
            if field in changes:
                setattr(app, field, changes[field])
        if "redirect_uris" in changes:
            app.redirect_uris = _clean_redirect_uris(changes["redirect_uris"])
        if "allowed_scopes" in changes:
            app.allowed_scopes = _clean_scopes(changes["allowed_scopes"], "allowed_scopes")
        app.save()
    return app


@transaction.atomic
def rotate_client_secret(app: OAuthApplication) -> str:
    _own_app(app)
    if not app.confidential:
        raise BusinessRuleViolation(_("Public clients have no secret; they use PKCE."))
    secret = tokens.new_client_secret()
    with audit.track(app, action="rotate_secret"):
        app.client_secret_hash = tokens.hash_token(secret)
        app.save(update_fields=["client_secret_hash", "updated_at"])
    return secret


@transaction.atomic
def delete_application(app: OAuthApplication) -> None:
    """Retire an app: it can no longer be authorised and its grants here are revoked."""
    _own_app(app)
    with audit.track(app, action="delete"):
        app.revoked_at = now()
        app.save(update_fields=["revoked_at", "updated_at"])
    for grant in OAuthGrant.objects.filter(application=app, revoked_at__isnull=True):
        revoke_grant(grant)


def application_for(client_id: str) -> OAuthApplication:
    app = OAuthApplication.objects.filter(client_id=client_id, revoked_at__isnull=True).first()
    org = require_organisation_id()
    if app is None or (app.owner_organisation_id not in (None, org)):
        raise OAuthError("invalid_client", "Unknown client.")
    return app


def validate_authorization(
    *, client_id: str, redirect_uri: str, response_type: str, scope: str,
    code_challenge: str = "", code_challenge_method: str = "",
) -> tuple[OAuthApplication, list[str]]:  # fmt: skip
    """Check an authorisation request before showing the consent screen."""
    app = application_for(client_id)
    if redirect_uri not in app.redirect_uris:
        raise OAuthError("invalid_request", "redirect_uri is not registered for this client.")
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "Only response_type=code is supported.")
    requested = [s for s in scope.replace(",", " ").split() if s]
    try:
        cleaned = scopes.validate_scopes(requested)
    except ValueError as exc:
        raise OAuthError("invalid_scope", f"Unknown scope: {exc}") from exc
    if not cleaned:
        raise OAuthError("invalid_scope", "Request at least one scope.")
    if app.allowed_scopes and not set(cleaned) <= set(app.allowed_scopes):
        raise OAuthError("invalid_scope", "The client may not request these scopes.")
    pkce_used = bool(code_challenge) or not app.confidential
    if pkce_used and (code_challenge_method != "S256" or not 43 <= len(code_challenge) <= 128):
        raise OAuthError("invalid_request", "PKCE with code_challenge_method=S256 is required.")
    return app, cleaned


@transaction.atomic
def approve_authorization(
    *, app: OAuthApplication, user: Any, scopes_: list[str], redirect_uri: str,
    code_challenge: str = "", code_challenge_method: str = "",
) -> str:  # fmt: skip
    """The user consented: record the grant (a connected app) and issue a short-lived
    authorisation code. Returns the code."""
    grant = (
        OAuthGrant.objects.select_for_update()
        .filter(application=app, user=user, revoked_at__isnull=True)
        .first()
    )
    if grant is None:
        grant = OAuthGrant.objects.create(application=app, user=user, scopes=scopes_)
        audit.record(grant, "create", {"application": [None, app.name], "scopes": [None, scopes_]})
        publish(
            events.OAuthAppConnected(
                subject_id=grant.pk,
                application_id=str(app.pk),
                application=app.name,
                scopes=scopes_,
            )
        )
    elif set(grant.scopes) != set(scopes_):
        with audit.track(grant):
            grant.scopes = sorted(set(grant.scopes) | set(scopes_))
            grant.save(update_fields=["scopes", "updated_at"])
    issued = tokens.issue(CredentialKind.AUTH_CODE)
    OAuthToken.objects.create(
        grant=grant,
        kind=CredentialKind.AUTH_CODE,
        prefix=issued.prefix,
        secret_hash=issued.hash,
        scopes=scopes_,
        expires_at=now() + CODE_TTL,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    _route(issued)
    return issued.token


def redirect_with(redirect_uri: str, **params: str) -> str:
    separator = "&" if urlsplit(redirect_uri).query else "?"
    return redirect_uri + separator + urlencode({k: v for k, v in params.items() if v})


def _authenticate_client(app: OAuthApplication, client_secret: str) -> None:
    if app.confidential and not (
        client_secret and tokens.matches(client_secret, app.client_secret_hash)
    ):
        raise OAuthError("invalid_client", "Client authentication failed.", status=401)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


def _issue_tokens(grant: OAuthGrant, scopes_: list[str]) -> dict[str, Any]:
    access = tokens.issue(CredentialKind.ACCESS_TOKEN)
    refresh = tokens.issue(CredentialKind.REFRESH_TOKEN)
    lifetime = int(_config("OAUTH_ACCESS_TOKEN_SECONDS", 3600))
    current = now()
    for issued, expires in (
        (access, current + timedelta(seconds=lifetime)),
        (refresh, current + timedelta(days=int(_config("OAUTH_REFRESH_TOKEN_DAYS", 90)))),
    ):
        OAuthToken.objects.create(
            grant=grant,
            kind=issued.kind,
            prefix=issued.prefix,
            secret_hash=issued.hash,
            scopes=scopes_,
            expires_at=expires,
        )
        _route(issued)
    return {
        "access_token": access.token,
        "token_type": "Bearer",
        "expires_in": lifetime,
        "refresh_token": refresh.token,
        "scope": " ".join(scopes_),
    }


def _revoke_grant_tokens(grant: OAuthGrant) -> int:
    return OAuthToken.objects.filter(grant=grant, revoked_at__isnull=True).update(revoked_at=now())


def _token_row(raw: str, kind: str) -> tuple[Any, OAuthToken | None]:
    """(organisation id, row) for a code/refresh token, looked up via its route."""
    parsed = tokens.parse(raw)
    if parsed is None or parsed.kind != kind:
        return None, None
    route = CredentialRoute.objects.filter(prefix=parsed.prefix, kind=kind).first()
    if route is None:
        return None, None
    with tenant_context(route.organisation_id):
        row = (
            OAuthToken.objects.select_related("grant__application")
            .filter(prefix=parsed.prefix, kind=kind)
            .first()
        )
        if row is None or not tokens.matches(raw, row.secret_hash):
            return route.organisation_id, None
    return route.organisation_id, row


def _refuse_replay(org_id: Any, row: OAuthToken, client_id: str, message: str) -> None:
    """A code or refresh token presented twice means it leaked: revoke every token of the
    grant (RFC 6749 §4.1.2, §10.4), committed before the error is returned."""
    if row.used_at is None or row.grant.application.client_id != client_id:
        return
    with tenant_context(org_id), transaction.atomic():
        _revoke_grant_tokens(row.grant)
    raise OAuthError("invalid_grant", message)


def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str
) -> dict[str, Any]:
    """``grant_type=authorization_code`` on the token endpoint (no tenant until the code
    is found)."""
    org_id, row = _token_row(code, CredentialKind.AUTH_CODE)
    if row is None:
        raise OAuthError("invalid_grant", "The authorisation code is not valid.")
    _refuse_replay(org_id, row, client_id, "The authorisation code was already used.")
    with tenant_context(org_id), transaction.atomic():
        row = (
            OAuthToken.objects.select_for_update()
            .select_related("grant__application")
            .get(pk=row.pk)
        )
        app = row.grant.application
        if app.client_id != client_id:
            raise OAuthError("invalid_grant", "The code was issued to another client.")
        _authenticate_client(app, client_secret)
        if row.used_at is not None:
            raise OAuthError("invalid_grant", "The authorisation code was already used.")
        if row.revoked_at is not None or row.expires_at <= now():
            raise OAuthError("invalid_grant", "The authorisation code has expired.")
        if row.redirect_uri != redirect_uri:
            raise OAuthError("invalid_grant", "redirect_uri does not match.")
        if row.code_challenge and not _pkce_ok(code_verifier, row.code_challenge):
            raise OAuthError("invalid_grant", "The PKCE code_verifier does not match.")
        if row.grant.revoked_at is not None:
            raise OAuthError("invalid_grant", "The app has been disconnected.")
        row.used_at = now()
        row.save(update_fields=["used_at", "updated_at"])
        return _issue_tokens(row.grant, list(row.scopes))


def refresh_tokens(*, client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    """``grant_type=refresh_token``: rotates the refresh token. Reusing a rotated refresh
    token revokes the whole grant's tokens (theft detection)."""
    org_id, row = _token_row(refresh_token, CredentialKind.REFRESH_TOKEN)
    if row is None:
        raise OAuthError("invalid_grant", "The refresh token is not valid.")
    _refuse_replay(org_id, row, client_id, "The refresh token was already used.")
    with tenant_context(org_id), transaction.atomic():
        row = (
            OAuthToken.objects.select_for_update()
            .select_related("grant__application")
            .get(pk=row.pk)
        )
        app = row.grant.application
        if app.client_id != client_id:
            raise OAuthError("invalid_grant", "The token was issued to another client.")
        _authenticate_client(app, client_secret)
        if row.used_at is not None:
            raise OAuthError("invalid_grant", "The refresh token was already used.")
        if (
            row.revoked_at is not None
            or row.expires_at <= now()
            or row.grant.revoked_at is not None
            or app.revoked_at is not None
        ):
            raise OAuthError("invalid_grant", "The refresh token has expired or been revoked.")
        row.used_at = now()
        row.revoked_at = row.used_at
        row.save(update_fields=["used_at", "revoked_at", "updated_at"])
        return _issue_tokens(row.grant, list(row.scopes))


def revoke_token(*, client_id: str, client_secret: str, token: str) -> None:
    """RFC 7009 revocation: always succeeds for unknown tokens; a refresh token takes its
    access tokens with it."""
    parsed = tokens.parse(token)
    if parsed is None or parsed.kind not in (
        CredentialKind.ACCESS_TOKEN, CredentialKind.REFRESH_TOKEN,
    ):  # fmt: skip
        return
    org_id, row = _token_row(token, parsed.kind)
    if row is None:
        return
    with tenant_context(org_id), transaction.atomic():
        app = row.grant.application
        if app.client_id != client_id:
            return
        _authenticate_client(app, client_secret)
        if parsed.kind == CredentialKind.REFRESH_TOKEN:
            _revoke_grant_tokens(row.grant)
        else:
            OAuthToken.objects.filter(pk=row.pk).update(revoked_at=now())


@transaction.atomic
def revoke_grant(grant: OAuthGrant) -> OAuthGrant:
    """Disconnect a connected app: the grant and every token issued under it stop working."""
    if grant.revoked_at is not None:
        return grant
    with audit.track(grant, action="revoke"):
        grant.revoked_at = now()
        grant.save(update_fields=["revoked_at", "updated_at"])
    _revoke_grant_tokens(grant)
    publish(
        events.OAuthAppDisconnected(
            subject_id=grant.pk,
            application_id=str(grant.application_id),
            application=grant.application.name,
        )
    )
    return grant


# --- webhooks (E27-T03) -------------------------------------------------------------------------


def _check_url(url: str) -> str:
    from tutortrack.core.net import UnsafeURL, safe_url

    try:
        return safe_url(url).url
    except UnsafeURL as exc:
        raise _invalid("url", _("That address isn't allowed: %(e)s") % {"e": exc}) from exc


def _clean_events(values: list[str]) -> list[str]:
    try:
        return catalogue.validate_subscriptions(list(values))
    except ValueError as exc:
        raise _invalid(
            "events", _("Choose event types from the catalogue (not: %(e)s).") % {"e": exc}
        ) from exc


@transaction.atomic
def create_endpoint(
    *,
    url: str,
    events_: list[str],
    description: str = "",
    branch: Any = None,
    source: str = WebhookEndpoint.Source.MANUAL,
    api_version: str = "",
) -> tuple[WebhookEndpoint, str]:
    """Register an endpoint (HTTPS, public address only). Returns it with its secret."""
    secret = tokens.new_webhook_secret()
    endpoint = WebhookEndpoint.objects.create(
        url=_check_url(url),
        events=_clean_events(events_),
        description=description,
        branch=branch,
        source=source,
        api_version=api_version or _config("WEBHOOK_API_VERSION", "2026-10-01"),
        secret=secret,
    )
    audit.record(
        endpoint, "create", {"url": [None, endpoint.url], "events": [None, endpoint.events]}
    )
    publish(
        events.WebhookEndpointCreated(
            subject_id=endpoint.pk, url=endpoint.url, events=endpoint.events
        ),
        branch_id=endpoint.branch_id,
    )
    return endpoint, secret


@transaction.atomic
def update_endpoint(endpoint: WebhookEndpoint, **changes: Any) -> WebhookEndpoint:
    with audit.track(endpoint):
        if "url" in changes:
            endpoint.url = _check_url(changes["url"])
        if "events" in changes:
            endpoint.events = _clean_events(changes["events"])
        if "description" in changes:
            endpoint.description = changes["description"]
        if "branch" in changes:
            endpoint.branch = changes["branch"]
        if "status" in changes:
            status = changes["status"]
            if status not in (WebhookEndpoint.Status.ACTIVE, WebhookEndpoint.Status.PAUSED):
                raise _invalid("status", _("Set the endpoint active or paused."))
            if status == WebhookEndpoint.Status.ACTIVE:
                endpoint.failing_since = None
                endpoint.disabled_at = None
            endpoint.status = status
        endpoint.save()
    return endpoint


@transaction.atomic
def rotate_endpoint_secret(endpoint: WebhookEndpoint) -> str:
    """A new signing secret; for 24 hours deliveries are signed with both."""
    secret = tokens.new_webhook_secret()
    with audit.track(endpoint, action="rotate_secret"):
        endpoint.previous_secret = endpoint.secret
        endpoint.previous_secret_expires_at = now() + SECRET_OVERLAP
        endpoint.secret = secret
        endpoint.save()
    return secret


def reveal_secret(endpoint: WebhookEndpoint) -> str:
    audit.record_read(endpoint, "webhook signing secret")
    return endpoint.secret


@transaction.atomic
def delete_endpoint(endpoint: WebhookEndpoint) -> None:
    audit.record(endpoint, "delete", {"url": [endpoint.url, None]})
    endpoint.delete()  # running delivery workflows find it gone and stop


def _start_delivery(delivery: WebhookDelivery) -> None:
    start(
        WebhookDeliveryWorkflow,
        DeliveryInput(organisation_id=str(delivery.organisation_id), delivery_id=str(delivery.pk)),
        id=delivery_workflow_id(delivery.organisation_id, delivery.pk),
        subject=("webhook_delivery", str(delivery.pk)),
    )


def enqueue_event(event: EventEnvelope) -> list[WebhookDelivery]:
    """Outbox subscriber: one delivery per matching active endpoint (idempotent per event)."""
    if event.organisation_id is None:
        return []
    created = []
    payload_cache: dict[str, Any] = {}
    for endpoint in WebhookEndpoint.objects.filter(
        status=WebhookEndpoint.Status.ACTIVE
    ).select_related("created_by"):
        if not catalogue.subscribed(list(endpoint.events), event.type):
            continue
        if endpoint.branch_id is not None and event.branch_id != endpoint.branch_id:
            continue
        if WebhookDelivery.objects.filter(
            endpoint=endpoint, event_id=event.id, redelivery_of__isnull=True, is_test=False
        ).exists():
            continue
        payload = catalogue.build_payload(
            event, api_version=endpoint.api_version, user=endpoint.created_by, cache=payload_cache
        )
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint, event_id=event.id, event_type=event.type, payload=payload
        )
        _start_delivery(delivery)
        created.append(delivery)
    return created


@transaction.atomic
def send_test_event(endpoint: WebhookEndpoint) -> WebhookDelivery:
    payload = catalogue.test_payload(endpoint.organisation_id, endpoint.api_version)
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_id=payload["id"],
        event_type=catalogue.TEST_EVENT,
        payload=payload,
        is_test=True,
    )
    audit.record(endpoint, "send_test_event")
    _start_delivery(delivery)
    return delivery


@transaction.atomic
def redeliver(delivery: WebhookDelivery) -> WebhookDelivery:
    """Send the same event again as a new delivery (same ``Webhook-Id`` for dedupe)."""
    if delivery.endpoint.status == WebhookEndpoint.Status.DISABLED:
        raise BusinessRuleViolation(_("Re-enable the endpoint before redelivering."))
    copy = WebhookDelivery.objects.create(
        endpoint=delivery.endpoint,
        event_id=delivery.event_id,
        event_type=delivery.event_type,
        payload=delivery.payload,
        is_test=delivery.is_test,
        redelivery_of=delivery,
    )
    audit.record(delivery, "redeliver")
    _start_delivery(copy)
    return copy


def retry_now(delivery: WebhookDelivery) -> None:
    if delivery.status not in (WebhookDelivery.Status.PENDING, WebhookDelivery.Status.RETRYING):
        raise BusinessRuleViolation(_("Only deliveries waiting to retry can be retried now."))
    signal(delivery_workflow_id(delivery.organisation_id, delivery.pk), "retry_now")


def _signing_secrets(endpoint: WebhookEndpoint) -> list[str]:
    secrets_ = [endpoint.secret]
    if (
        endpoint.previous_secret
        and endpoint.previous_secret_expires_at
        and endpoint.previous_secret_expires_at > now()
    ):
        secrets_.append(endpoint.previous_secret)
    return secrets_


def _post(endpoint: WebhookEndpoint, delivery: WebhookDelivery, number: int) -> dict[str, Any]:
    """One signed POST through the SSRF guard. Never raises."""
    from tutortrack.core.net import UnsafeURL, safe_urlopen

    body = json.dumps(delivery.payload, separators=(",", ":")).encode()
    stamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "TutorTrack-Webhooks/1",
        "Webhook-Id": str(delivery.event_id),
        "Webhook-Event": delivery.event_type,
        "Webhook-Attempt": str(number),
        "Webhook-Signature": signing.header(_signing_secrets(endpoint), stamp, body),
    }
    result: dict[str, Any] = {"headers": headers, "status": None, "snippet": "", "error": ""}
    started = time.monotonic()
    try:
        with safe_urlopen(
            endpoint.url, data=body, headers=headers, method="POST", timeout=10
        ) as response:
            result["status"] = int(getattr(response, "status", 200))
            result["snippet"] = response.read(SNIPPET_LIMIT).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        try:
            result["snippet"] = exc.read(SNIPPET_LIMIT).decode("utf-8", "replace")
        except Exception:
            result["snippet"] = ""
    except UnsafeURL as exc:
        result["error"] = f"Blocked: {exc}"
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)[:500] or exc.__class__.__name__
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def attempt_delivery(delivery_id: str, number: int, attempted_at: datetime) -> str:
    """Workflow activity body. Idempotent per (delivery, attempt number)."""
    delivery = WebhookDelivery.objects.select_related("endpoint").filter(pk=delivery_id).first()
    if delivery is None:
        return "cancelled"
    done = WebhookAttempt.objects.filter(delivery=delivery, number=number).first()
    if done is not None:
        return "succeeded" if done.succeeded else "retry"
    if delivery.status in (WebhookDelivery.Status.SUCCEEDED, WebhookDelivery.Status.CANCELLED):
        return str(delivery.status)
    endpoint = delivery.endpoint
    if endpoint.status != WebhookEndpoint.Status.ACTIVE and not delivery.is_test:
        WebhookDelivery.objects.filter(pk=delivery.pk).update(
            status=WebhookDelivery.Status.CANCELLED
        )
        return "cancelled"

    result = _post(endpoint, delivery, number)
    status_code = result["status"]
    ok = status_code is not None and 200 <= status_code < 300
    with transaction.atomic():
        WebhookAttempt.objects.create(
            delivery=delivery,
            number=number,
            attempted_at=attempted_at,
            status_code=status_code,
            succeeded=ok,
            error=result["error"] or ("" if ok else f"HTTP {status_code}"),
            request_headers=result["headers"],
            response_snippet=result["snippet"][:SNIPPET_LIMIT],
            duration_ms=result["duration_ms"],
        )
        delivery.attempt_count = number
        delivery.last_status_code = status_code
        delivery.last_attempt_at = attempted_at
        delivery.status = (
            WebhookDelivery.Status.SUCCEEDED if ok else WebhookDelivery.Status.RETRYING
        )
        if ok:
            delivery.delivered_at = attempted_at
        delivery.save(
            update_fields=[
                "attempt_count", "last_status_code", "last_attempt_at", "status",
                "delivered_at", "updated_at",
            ]
        )  # fmt: skip
        if not delivery.is_test:
            _track_health(endpoint.pk, ok, attempted_at)
    return "succeeded" if ok else "retry"


def _track_health(endpoint_id: Any, ok: bool, attempted_at: datetime) -> None:
    """Continuous-failure tracking: any success clears it; three days of failures disable
    the endpoint and email the admins."""
    endpoint = WebhookEndpoint.objects.select_for_update().get(pk=endpoint_id)
    if ok:
        if endpoint.failing_since is not None:
            endpoint.failing_since = None
            endpoint.save(update_fields=["failing_since", "updated_at"])
        return
    if endpoint.failing_since is None:
        endpoint.failing_since = attempted_at
        endpoint.save(update_fields=["failing_since", "updated_at"])
        return
    if (
        endpoint.status == WebhookEndpoint.Status.ACTIVE
        and attempted_at - endpoint.failing_since >= AUTO_DISABLE_AFTER
    ):
        disable_endpoint(endpoint)


def disable_endpoint(endpoint: WebhookEndpoint) -> WebhookEndpoint:
    with audit.track(endpoint, action="auto_disable"):
        endpoint.status = WebhookEndpoint.Status.DISABLED
        endpoint.disabled_at = now()
        endpoint.save(update_fields=["status", "disabled_at", "updated_at"])
    publish(
        events.WebhookEndpointDisabled(
            subject_id=endpoint.pk,
            url=endpoint.url,
            failing_since=endpoint.failing_since.isoformat() if endpoint.failing_since else "",
        ),
        branch_id=endpoint.branch_id,
    )
    from tutortrack.comms import services as comms

    from .notifications import ENDPOINT_DISABLED

    transaction.on_commit(
        lambda: comms.notify(
            ENDPOINT_DISABLED, endpoint, key=f"{endpoint.pk}:{endpoint.disabled_at}"
        )
    )
    return endpoint


@transaction.atomic
def give_up(delivery_id: str) -> bool:
    delivery = WebhookDelivery.objects.select_for_update().filter(pk=delivery_id).first()
    if delivery is None or delivery.status != WebhookDelivery.Status.RETRYING:
        return False
    delivery.status = WebhookDelivery.Status.FAILED
    delivery.save(update_fields=["status", "updated_at"])
    publish(
        events.WebhookDeliveryFailed(
            subject_id=delivery.pk,
            endpoint_id=str(delivery.endpoint_id),
            event_type_name=delivery.event_type,
            attempts=delivery.attempt_count,
        ),
        dedupe_key=f"webhook-delivery-failed:{delivery.pk}",
    )
    return True


def purge_deliveries(days: int | None = None) -> int:
    """Delivery log retention (30 days)."""
    cutoff = now() - timedelta(days=days or int(_config("WEBHOOK_LOG_DAYS", 30)))
    deleted, _detail = WebhookDelivery.objects.filter(
        created_at__lt=cutoff,
        status__in=[
            WebhookDelivery.Status.SUCCEEDED,
            WebhookDelivery.Status.FAILED,
            WebhookDelivery.Status.CANCELLED,
        ],
    ).delete()
    return deleted


# --- sandbox organisations (E27-T09) ------------------------------------------------------------


def _sandbox_slug(base: str) -> str:
    from tutortrack.tenancy.models import Organisation

    stem = f"{base}-sandbox"[:55]
    candidate, n = stem, 1
    while Organisation.objects.filter(slug=candidate).exists():
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


@transaction.atomic
def create_sandbox(*, user: Any) -> Sandbox:
    """Copy this organisation's settings into a new organisation, load sample data and make
    ``user`` its owner. Provider connections (payments, calendars, accounting) are not
    copied, so nothing in the sandbox reaches live accounts."""
    from tutortrack.tenancy import services as tenancy
    from tutortrack.tenancy.demo import load_demo_data
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.settings_registry import registry
    from tutortrack.tenancy.settings_service import area_values, update_settings

    org = Organisation.objects.get(pk=require_organisation_id())
    if _setting("developer.sandbox_of"):
        raise BusinessRuleViolation(_("A sandbox can't have its own sandbox."))
    if Sandbox.objects.count() >= MAX_SANDBOXES:
        raise BusinessRuleViolation(
            _("You can have at most %(n)s sandboxes.") % {"n": MAX_SANDBOXES}
        )
    if user is None or not getattr(user, "is_authenticated", False):
        raise PermissionDenied()
    copied = {area: area_values(area) for area in registry.areas() if area != "developer"}
    sandbox_org = tenancy.create_organisation(
        name=f"{org.name} (sandbox)"[:200],
        owner=user,
        country=org.country,
        slug=_sandbox_slug(org.slug),
        business_type=org.business_type,
        timezone=org.timezone,
        currency=org.default_currency,
        locale=org.locale,
    )
    with tenant_context(sandbox_org), branch_scope(None):
        for area, values in copied.items():
            try:
                with transaction.atomic():
                    update_settings(area, values)
            except Exception:
                logger.info("sandbox.setting_skipped", area=area)
        update_settings("developer", {"developer.sandbox_of": str(org.pk)})
        records = load_demo_data()
    sandbox = Sandbox.objects.create(
        sandbox_organisation_id=sandbox_org.pk,
        name=sandbox_org.name,
        slug=sandbox_org.slug,
        records=records,
    )
    audit.record(sandbox, "create", {"slug": [None, sandbox.slug]})
    publish(
        events.SandboxCreated(
            subject_id=sandbox.pk,
            sandbox_organisation_id=str(sandbox_org.pk),
            slug=sandbox_org.slug,
        )
    )
    return sandbox
