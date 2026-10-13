"""Passkeys and security keys (WebAuthn, FR-03-2, E03-T08) on ``py_webauthn``.

* **Register** (signed in): ``registration_options`` stores the challenge in the session;
  ``register`` verifies the attestation (``none`` is accepted: we trust the browser, not a
  vendor list) and saves the credential. A first passkey also issues recovery codes, like
  TOTP, because it is a second factor.
* **Second factor**: after a password or magic link, ``authentication_options`` lists the
  pending user's credentials and ``verify_second_factor`` completes the sign-in.
* **Passkey-only sign-in**: ``authentication_options`` without a user asks for any
  discoverable credential; ``login_with_passkey`` finds it and signs the user in. User
  verification (PIN or biometric) is required, so this counts as multi-factor.

The relying party id is ``WEBAUTHN_RP_ID`` (default ``TENANT_BASE_DOMAIN``), so a passkey
works on every organisation's subdomain and the root app host. Custom domains (E24) can't
use it (browsers bind passkeys to the registrable domain): people there sign in with a
password or SSO.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from tutortrack.core.time import now

from .auth import InvalidCode, _check_lockout, _record, complete_login, pending_mfa_user
from .models import User, WebAuthnCredential

REGISTER_KEY = "tt_webauthn_register"
AUTH_KEY = "tt_webauthn_auth"
MAX_CREDENTIALS = 10


def rp_id() -> str:
    return str(getattr(settings, "WEBAUTHN_RP_ID", "") or settings.TENANT_BASE_DOMAIN)


def expected_origin(request: HttpRequest) -> str:
    """The page's origin; it must be on the relying party's domain."""
    origin = f"{request.scheme}://{request.get_host()}"
    host = request.get_host().split(":")[0]
    if host != rp_id() and not host.endswith(f".{rp_id()}"):
        raise InvalidCode(_("Passkeys can't be used on this address."))
    return origin


def _descriptors(user: User) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
        for c in user.webauthn_credentials.all()
    ]


def registration_options(request: HttpRequest, user: User) -> dict[str, Any]:
    expected_origin(request)
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name="TutorTrack",
        user_id=user.pk.bytes,
        user_name=user.email,
        user_display_name=user.get_full_name(),
        exclude_credentials=_descriptors(user),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    request.session[REGISTER_KEY] = bytes_to_base64url(options.challenge)
    result: dict[str, Any] = json.loads(options_to_json(options))
    return result


@transaction.atomic
def register(
    request: HttpRequest, user: User, credential: dict[str, Any], *, name: str = ""
) -> tuple[WebAuthnCredential, list[str]]:
    """Save a new passkey. Returns it and, for the user's first second factor, recovery
    codes (shown once)."""
    from .auth import regenerate_recovery_codes

    challenge = request.session.pop(REGISTER_KEY, None)
    if not challenge:
        raise InvalidCode(_("Start adding the passkey again."))
    if user.webauthn_credentials.count() >= MAX_CREDENTIALS:
        raise InvalidCode(_("You can have at most %(n)s passkeys.") % {"n": MAX_CREDENTIALS})
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id(),
            expected_origin=expected_origin(request),
        )
    except InvalidRegistrationResponse as exc:
        raise InvalidCode(_("That passkey couldn't be added.")) from exc
    had_mfa = user.has_mfa
    stored = WebAuthnCredential.objects.create(
        user=user,
        name=(name or _("Passkey"))[:100],
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=list((credential.get("response") or {}).get("transports") or [])[:10],
        aaguid=str(verified.aaguid or ""),
        backed_up=bool(verified.credential_backed_up),
    )
    codes: list[str] = []
    if not had_mfa:
        codes = regenerate_recovery_codes(user)
        from tutortrack.core.events import publish

        from .events import UserMFAEnabled

        publish(UserMFAEnabled(subject_id=user.pk, method="webauthn"), organisation_id=None)
    return stored, codes


def authentication_options(request: HttpRequest, user: User | None = None) -> dict[str, Any]:
    expected_origin(request)
    options = generate_authentication_options(
        rp_id=rp_id(),
        allow_credentials=_descriptors(user) if user is not None else [],
        user_verification=(
            UserVerificationRequirement.PREFERRED
            if user is not None
            else UserVerificationRequirement.REQUIRED
        ),
    )
    request.session[AUTH_KEY] = bytes_to_base64url(options.challenge)
    result: dict[str, Any] = json.loads(options_to_json(options))
    return result


def _verify(
    request: HttpRequest, credential: dict[str, Any], *, user: User | None, require_uv: bool
) -> WebAuthnCredential:
    challenge = request.session.pop(AUTH_KEY, None)
    raw_id = str(credential.get("rawId") or credential.get("id") or "")
    stored = WebAuthnCredential.objects.select_related("user").filter(credential_id=raw_id).first()
    if not challenge or stored is None or (user is not None and stored.user_id != user.pk):
        raise InvalidCode(_("That passkey isn't recognised."))
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id(),
            expected_origin=expected_origin(request),
            credential_public_key=bytes(stored.public_key),
            credential_current_sign_count=stored.sign_count,
            require_user_verification=require_uv,
        )
    except InvalidAuthenticationResponse as exc:
        raise InvalidCode(_("That passkey couldn't be checked.")) from exc
    WebAuthnCredential.objects.filter(pk=stored.pk).update(
        sign_count=verified.new_sign_count, last_used_at=now()
    )
    return stored


def verify_second_factor(request: HttpRequest, credential: dict[str, Any]) -> User:
    user, pending = pending_mfa_user(request)
    _check_lockout(user.email)
    try:
        _verify(request, credential, user=user, require_uv=False)
    except InvalidCode:
        _record(request, user.email, "webauthn", user=user, success=False, reason="bad_passkey")
        raise
    complete_login(
        request, user, method=pending["method"], remember=pending["remember"], mfa_verified=True
    )
    return user


def login_with_passkey(
    request: HttpRequest, credential: dict[str, Any], *, remember: bool = False
) -> User:
    """Passkey-only sign-in with a discoverable credential (user verification required)."""
    stored = _verify(request, credential, user=None, require_uv=True)
    user = stored.user
    if not user.is_active:
        raise InvalidCode(_("That passkey isn't recognised."))
    complete_login(request, user, method="passkey", remember=remember, mfa_verified=True)
    return user


def remove(credential: WebAuthnCredential) -> None:
    from .models import RecoveryCode

    user = credential.user
    credential.delete()
    if not user.has_mfa:
        RecoveryCode.objects.filter(user=user).delete()
