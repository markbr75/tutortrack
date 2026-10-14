"""Step-up re-authentication for sensitive reads (E12 "full bank details need re-auth",
gap G3). There was no shared step-up pattern before (password checks were inline), so
this is the reusable one:

* ``methods(user)``: what the person can confirm with: their password, an authenticator
  code (or recovery code), or a passkey;
* ``confirm(request, ...)`` checks one of them and records the time in the session
  (``tt_reauth_at``); failures count towards the normal login lockout;
* ``require_recent(request)`` raises ``ReauthenticationRequired`` (403,
  ``reauthentication-required``, with the methods) unless the person confirmed within
  ``REAUTH_MAX_AGE`` (5 minutes).

Recent confirmations live in the server-side session only, so a stolen session cookie
alone doesn't skip the step after five minutes, and signing out forgets it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.http import HttpRequest
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.time import now

SESSION_KEY = "tt_reauth_at"
REAUTH_MAX_AGE = timedelta(minutes=5)


class ReauthenticationRequired(PermissionDenied):
    problem_type = "reauthentication-required"
    title = "Please confirm it's you"


class ReauthenticationFailed(PermissionDenied):
    problem_type = "reauthentication-failed"
    title = "That didn't match"


def methods(user: Any) -> list[str]:
    out = []
    if user.has_usable_password():
        out.append("password")
    if user.mfa_devices.filter(confirmed_at__isnull=False).exists():
        out.append("totp")
    if user.webauthn_credentials.exists():
        out.append("passkey")
    return out


def is_recent(request: HttpRequest) -> bool:
    stamp = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
    if not stamp:
        return False
    try:
        at = float(stamp)
    except (TypeError, ValueError):
        return False
    return now().timestamp() - at <= REAUTH_MAX_AGE.total_seconds()


def require_recent(request: HttpRequest) -> None:
    if not is_recent(request):
        raise ReauthenticationRequired(
            _("Confirm it's you to see this."),
            extra={"code": "reauthentication_required", "methods": methods(request.user)},
        )


def passkey_options(request: HttpRequest) -> dict[str, Any]:
    from .passkeys import authentication_options

    return authentication_options(request, request.user)  # type: ignore[arg-type]


def confirm(
    request: HttpRequest,
    *,
    password: str = "",
    code: str = "",
    credential: dict[str, Any] | None = None,
) -> str:
    """Check one method; on success remember the time. Returns the method used."""
    from .auth import InvalidCode, _check_lockout, _record, check_totp, use_recovery_code

    user: Any = request.user
    _check_lockout(user.email)
    method = "password" if password else "totp" if code else "passkey" if credential else ""
    ok = False
    if method == "password":
        ok = user.has_usable_password() and user.check_password(password)
    elif method == "totp":
        ok = check_totp(user, code) or use_recovery_code(user, code)
    elif method == "passkey":
        from .passkeys import _verify

        try:
            _verify(request, credential or {}, user=user, require_uv=False)
            ok = True
        except InvalidCode:
            ok = False
    if not ok:
        _record(
            request,
            user.email,
            "reauth",
            user=user,
            success=False,
            reason="bad_" + (method or "none"),
        )
        raise ReauthenticationFailed(_("That didn't match. Try again."))
    request.session[SESSION_KEY] = str(now().timestamp())
    audit.record(user, "reauthenticate", {"method": method})
    return method
