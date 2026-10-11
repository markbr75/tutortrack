"""Integration framework writes (E22-T01): connect (OAuth or credentials), token refresh,
health and error bookkeeping, disconnect. Every mutation is audited; connect/disconnect/
error publish domain events that other apps (calendar sync, E23 accounting) react to."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.time import now

from . import events, oauth, providers
from .models import IntegrationConnection
from .providers import AuthError, Credentials, ProviderError, TokenSet

logger = structlog.get_logger(__name__)
REFRESH_MARGIN = timedelta(minutes=3)
Status = IntegrationConnection.Status


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _spec(provider: str) -> providers.ProviderSpec:
    try:
        return providers.get_spec(provider)
    except ProviderError as exc:
        raise _invalid("provider", _("Unknown provider.")) from exc


def _check_level(spec: providers.ProviderSpec, level: str) -> None:
    if level not in spec.levels:
        raise _invalid(
            "level", _("%(provider)s can't be connected that way.") % {"provider": spec.label}
        )


def _payload(connection: IntegrationConnection) -> dict[str, Any]:
    spec = providers.get_spec(connection.provider)
    return {
        "provider": connection.provider,
        "level": connection.level,
        "user_id": str(connection.user_id) if connection.user_id else None,
        "capabilities": sorted(spec.capabilities),
    }


# --- connect ------------------------------------------------------------------------------------


def start_oauth(user: Any, *, provider: str, level: str, next_path: str = "/") -> str:
    """The provider's authorization URL for ``user`` (see ``oauth`` for the flow)."""
    spec = _spec(provider)
    if spec.auth != "oauth2":
        raise _invalid(
            "provider",
            _("%(provider)s connects with a password or key.") % {"provider": spec.label},
        )
    _check_level(spec, level)
    token, state = oauth.make_state(
        organisation_id=require_organisation_id(),
        user_id=user.pk,
        provider=provider,
        level=level,
        next_path=next_path,
    )
    return providers.oauth_client(provider).authorize_url(
        state=token,
        redirect_uri=oauth.callback_url(),
        code_challenge=oauth.challenge_for(oauth.verifier_for(state.nonce)),
        scopes=providers.scopes(provider),
    )


def complete_oauth(
    user: Any, *, code: str, state: str, account_id: str = ""
) -> IntegrationConnection:
    """``account_id``: an account the provider names only on the redirect (QuickBooks
    ``realmId``), used when the token response doesn't identify the account."""
    try:
        parsed = oauth.read_state(state)
    except oauth.OAuthStateError as exc:
        raise _invalid("state", _("The connection link expired. Please try again.")) from exc
    if parsed.user_id != str(user.pk) or parsed.organisation_id != str(require_organisation_id()):
        raise PermissionDenied(_("This connection was started by someone else."))
    spec = _spec(parsed.provider)
    _check_level(spec, parsed.level)
    try:
        tokens = providers.oauth_client(parsed.provider).exchange(
            code=code,
            redirect_uri=oauth.callback_url(),
            code_verifier=oauth.verifier_for(parsed.nonce),
        )
    except ProviderError as exc:
        raise _invalid("code", str(exc)) from exc
    if account_id and not tokens.account_id:
        tokens = TokenSet(**{**tokens.__dict__, "account_id": account_id[:255]})
    return _save(
        user if parsed.level == IntegrationConnection.Level.USER else None,
        parsed.provider,
        parsed.level,
        tokens=tokens,
    )


def connect_with_credentials(
    user: Any,
    *,
    provider: str,
    level: str,
    username: str = "",
    password: str = "",
    server_url: str = "",
    api_key: str = "",
) -> IntegrationConnection:
    """CalDAV app-specific passwords and API keys: verified at the provider, stored
    encrypted."""
    spec = _spec(provider)
    if spec.auth != "credentials":
        raise _invalid(
            "provider", _("%(provider)s connects by signing in.") % {"provider": spec.label}
        )
    _check_level(spec, level)
    secret = password or api_key
    if not secret:
        raise _invalid(
            "password" if "password" in spec.credential_fields else "api_key",
            _("Enter the password or key."),
        )
    if server_url and not providers.is_fake(provider):
        from tutortrack.core.net import UnsafeURL, safe_url

        try:
            safe_url(server_url)
        except UnsafeURL as exc:
            raise _invalid("server_url", str(exc)) from exc
    creds = Credentials(secret=secret, username=username, server_url=server_url)
    try:
        account = providers.credential_client(provider).verify(creds)
    except ProviderError as exc:
        raise _invalid("password" if username else "api_key", str(exc)) from exc
    return _save(
        user if level == IntegrationConnection.Level.USER else None,
        provider,
        level,
        tokens=TokenSet(
            access_token="", account_id=account.account_id, account_name=account.account_name
        ),
        secret=secret,
        extra={"username": username, "server_url": server_url},
    )


@transaction.atomic
def _save(
    owner: Any,
    provider: str,
    level: str,
    *,
    tokens: TokenSet,
    secret: str = "",
    extra: dict[str, Any] | None = None,
) -> IntegrationConnection:
    existing = (
        IntegrationConnection.objects.select_for_update()
        .filter(provider=provider, user=owner, level=level)
        .exclude(status=Status.DISCONNECTED)
        .first()
    )
    if existing is not None and existing.external_account_id != tokens.account_id:
        _disconnect(existing, revoke=False)  # a different account replaces the old one
        existing = None
    connection = existing or IntegrationConnection(provider=provider, user=owner, level=level)
    reconnected = existing is not None
    with audit.track(connection, action="reconnect" if reconnected else "connect"):
        connection.status = Status.ACTIVE
        connection.access_token = tokens.access_token
        connection.refresh_token = tokens.refresh_token or connection.refresh_token
        connection.expires_at = tokens.expires_at
        connection.scopes = list(tokens.scopes)
        connection.external_account_id = tokens.account_id
        connection.account_name = tokens.account_name
        if secret:
            connection.secret = secret
        if extra:
            connection.settings = {**connection.settings, **extra}
        connection.error, connection.error_count, connection.error_at = "", 0, None
        connection.connected_at = now()
        connection.last_checked_at = now()
        connection.save()
    if not reconnected:
        audit.record_create(connection)
    publish(
        events.IntegrationConnected(
            subject_id=connection.pk, reconnected=reconnected, **_payload(connection)
        )
    )
    return connection


# --- tokens and health ----------------------------------------------------------------------------


def credentials(connection: IntegrationConnection) -> Credentials:
    """Decrypted, fresh credentials for a client call (refreshes OAuth tokens near expiry)."""
    if connection.status in (Status.DISCONNECTED, Status.NEEDS_RECONNECT):
        raise AuthError(_("The account needs reconnecting."))
    if (
        connection.refresh_token
        and connection.expires_at is not None
        and connection.expires_at <= now() + REFRESH_MARGIN
    ):
        connection = refresh(connection)
    return Credentials(
        access_token=connection.access_token,
        secret=connection.secret,
        username=str(connection.settings.get("username", "")),
        server_url=str(connection.settings.get("server_url", "")),
        account_id=connection.external_account_id,
        settings=dict(connection.settings),
    )


def refresh(connection: IntegrationConnection) -> IntegrationConnection:
    """Refresh the access token (once, even with concurrent callers)."""
    try:
        return _refresh(connection)
    except AuthError as exc:
        record_failure(connection, exc)  # outside the rolled-back transaction
        raise


def _refresh(connection: IntegrationConnection) -> IntegrationConnection:
    with transaction.atomic():
        locked = IntegrationConnection.objects.select_for_update().get(pk=connection.pk)
        if locked.expires_at is not None and locked.expires_at > now() + REFRESH_MARGIN:
            return locked  # someone else refreshed it meanwhile
        tokens = providers.oauth_client(locked.provider).refresh(locked.refresh_token)
        locked.access_token = tokens.access_token
        locked.refresh_token = tokens.refresh_token or locked.refresh_token
        locked.expires_at = tokens.expires_at
        locked.save(update_fields=["access_token", "refresh_token", "expires_at", "updated_at"])
    return locked


def record_success(connection: IntegrationConnection, *, synced: bool = False) -> None:
    fields = ["last_checked_at", "updated_at"]
    connection.last_checked_at = now()
    if synced:
        connection.last_sync_at = now()
        fields.append("last_sync_at")
    if connection.status == Status.ERROR or connection.error:
        with audit.track(connection, action="recovered"):
            connection.status = Status.ACTIVE
            connection.error, connection.error_count, connection.error_at = "", 0, None
            connection.save()
        return
    connection.save(update_fields=fields)


@transaction.atomic
def record_failure(connection: IntegrationConnection, exc: Exception) -> str:
    """Remember an error. Revoked grants need reconnecting; anything else is an error the
    next sync may clear. The owner (or admins, for organisation connections) are told
    once, when the status changes. Returns the new status."""
    connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk)
    if connection.status == Status.DISCONNECTED:
        return connection.status
    new_status = Status.NEEDS_RECONNECT if isinstance(exc, AuthError) else Status.ERROR
    changed = connection.status != new_status
    message = str(exc)[:500] or exc.__class__.__name__
    with audit.track(connection, action="error"):
        connection.status = new_status
        connection.error = message
        connection.error_at = now()
        connection.error_count += 1
        connection.last_checked_at = now()
        connection.save()
    if changed:
        publish(
            events.IntegrationError(
                subject_id=connection.pk, status=new_status, error=message, **_payload(connection)
            )
        )
        from .notifications import notify_problem

        notify_problem(connection)
    logger.info("integrations.failure", provider=connection.provider, status=new_status)
    return str(new_status)


def check(connection: IntegrationConnection) -> IntegrationConnection:
    """A light provider call to confirm the connection works (health check)."""
    spec = providers.get_spec(connection.provider)
    try:
        creds = credentials(connection)
        if "calendar" in spec.capabilities:
            providers.calendar_client(connection.provider).list_calendars(creds)
        elif providers.health_check(connection.provider, creds):
            pass
        elif spec.auth == "credentials":
            providers.credential_client(connection.provider).verify(creds)
    except ProviderError as exc:
        record_failure(connection, exc)
    else:
        record_success(connection)
    connection.refresh_from_db()
    return connection


# --- disconnect ----------------------------------------------------------------------------------


def _disconnect(connection: IntegrationConnection, *, revoke: bool) -> None:
    if revoke and connection.refresh_token and connection.provider != "caldav":
        token = connection.refresh_token
        provider = connection.provider

        def _revoke() -> None:
            try:
                providers.oauth_client(provider).revoke(token)
            except ProviderError:
                logger.info("integrations.revoke_failed", provider=provider)

        transaction.on_commit(_revoke)
    with audit.track(connection, action="disconnect"):
        connection.status = Status.DISCONNECTED
        connection.access_token = ""
        connection.refresh_token = ""
        connection.secret = ""
        connection.expires_at = None
        connection.disconnected_at = now()
        connection.save()
    publish(events.IntegrationDisconnected(subject_id=connection.pk, **_payload(connection)))


@transaction.atomic
def disconnect(connection: IntegrationConnection) -> IntegrationConnection:
    connection = IntegrationConnection.objects.select_for_update().get(pk=connection.pk)
    if connection.status != Status.DISCONNECTED:
        _disconnect(connection, revoke=True)
    return connection


def update_settings(connection: IntegrationConnection, **values: Any) -> IntegrationConnection:
    """Provider-specific, non-secret settings (other apps keep their own models)."""
    with transaction.atomic(), audit.track(connection):
        connection.settings = {**connection.settings, **values}
        connection.save(update_fields=["settings", "updated_at"])
    return connection
