"""Authentication services (FR-03-2, FR-03-3): password, magic link, MFA, sessions.

Sign-in is two-step when the user has a second factor: the first factor stores a pending
marker in the session and only ``verify_mfa`` completes the login. Every attempt is
recorded as a ``LoginEvent``; repeated failures for an email trigger a progressive delay.
Error messages are uniform so they never reveal whether an account exists.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pyotp
import structlog
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import DomainError
from tutortrack.core.middleware import client_ip
from tutortrack.core.time import now

from .models import LoginEvent, LoginToken, MFADevice, RecoveryCode, User, UserSession

logger = structlog.get_logger(__name__)

SESSION_BACKEND = "django.contrib.auth.backends.ModelBackend"
SID_KEY = "tt_sid"
MFA_PENDING_KEY = "tt_mfa_pending"
MFA_PENDING_SECONDS = 300
LOCKOUT_FREE_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=15)
MAGIC_LINK_TTL = timedelta(minutes=15)
RECOVERY_CODE_COUNT = 10


class AuthenticationFailed(DomainError):
    status_code = 400
    problem_type = "authentication-failed"
    title = "Incorrect email or password"


class AccountLocked(DomainError):
    status_code = 429
    problem_type = "account-locked"
    title = "Too many attempts"


class InvalidCode(DomainError):
    status_code = 400
    problem_type = "invalid-code"
    title = "That code is not valid"


class MFANotPending(DomainError):
    status_code = 400
    problem_type = "mfa-not-pending"
    title = "Sign in again"


@dataclass(frozen=True)
class LoginResult:
    user: User
    mfa_required: bool


# --- helpers ------------------------------------------------------------------------------------


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def device_hash(user_agent: str) -> str:
    return hashlib.sha256(user_agent.encode()).hexdigest()


def _record(
    request: HttpRequest,
    email: str,
    method: str,
    *,
    user: User | None,
    success: bool,
    reason: str = "",
) -> LoginEvent:
    ua = request.headers.get("User-Agent", "")[:500]
    return LoginEvent.objects.create(
        user=user,
        email=email[:254],
        ip=client_ip(request),
        user_agent=ua,
        device_hash=device_hash(ua) if success else "",
        method=method,
        success=success,
        reason=reason,
    )


def lockout_seconds(email: str) -> int:
    """Seconds until another attempt is allowed (0 = allowed)."""
    since = now() - LOCKOUT_WINDOW
    recent = LoginEvent.objects.filter(email=email, created_at__gte=since).order_by("-created_at")
    failures = []
    for event in recent[:50]:
        if event.success:
            break
        failures.append(event)
    if len(failures) < LOCKOUT_FREE_ATTEMPTS:
        return 0
    delay = min(30 * 2 ** (len(failures) - LOCKOUT_FREE_ATTEMPTS), 900)
    elapsed = (now() - failures[0].created_at).total_seconds()
    return max(0, int(delay - elapsed))


def _check_lockout(email: str) -> None:
    wait = lockout_seconds(email)
    if wait:
        raise AccountLocked(
            _("Too many attempts. Try again in a few minutes."), extra={"retry_after": wait}
        )


# --- completing a login ---------------------------------------------------------------------------


def complete_login(
    request: HttpRequest,
    user: User,
    *,
    method: str,
    remember: bool = False,
    mfa_verified: bool = False,
) -> UserSession:
    """Start an authenticated session (after every factor has passed)."""
    request.session.pop(MFA_PENDING_KEY, None)
    request._tt_login_meta = {  # type: ignore[attr-defined]
        "method": method,
        "remember": remember,
        "mfa_verified": mfa_verified,
    }
    login(request, user, backend=SESSION_BACKEND)  # signals.track_session creates the session
    if remember:
        request.session.set_expiry(timedelta(days=settings.PORTAL_REMEMBER_DAYS))
    else:
        request.session.set_expiry(0 if settings.SESSION_EXPIRE_AT_BROWSER_CLOSE else None)
    is_new_device = not LoginEvent.objects.filter(
        user=user,
        success=True,
        device_hash=device_hash(request.headers.get("User-Agent", "")[:500]),
    ).exists()
    had_logins = LoginEvent.objects.filter(user=user, success=True).exists()
    _record(request, user.email, method, user=user, success=True)
    if is_new_device and had_logins:
        from .tasks import send_new_device_alert

        transaction.on_commit(
            lambda: send_new_device_alert.delay(
                user_id=str(user.pk),
                ip=client_ip(request) or "",
                user_agent=request.headers.get("User-Agent", "")[:200],
            )
        )
    session_id = request.session[SID_KEY]
    return UserSession.objects.get(pk=session_id)


def _begin_or_complete(
    request: HttpRequest, user: User, *, method: str, remember: bool
) -> LoginResult:
    if user.has_mfa:
        request.session[MFA_PENDING_KEY] = {
            "user_id": str(user.pk),
            "method": method,
            "remember": remember,
            "expires": (now() + timedelta(seconds=MFA_PENDING_SECONDS)).isoformat(),
        }
        return LoginResult(user=user, mfa_required=True)
    complete_login(request, user, method=method, remember=remember)
    return LoginResult(user=user, mfa_required=False)


# --- password -------------------------------------------------------------------------------------
# Not wrapped in a transaction: failed attempts must be recorded (lockout, security review)
# even though the call then raises.


def login_with_password(
    request: HttpRequest, email: str, password: str, *, remember: bool = False
) -> LoginResult:
    email = email.strip().lower()
    _check_lockout(email)
    user = User.objects.filter(email=email).first()
    if user is None or not user.is_active or not user.check_password(password):
        if user is None:
            make_password(password)  # equalise timing with the existing-user path
        _record(request, email, "password", user=user, success=False, reason="bad_credentials")
        raise AuthenticationFailed()
    return _begin_or_complete(request, user, method="password", remember=remember)


# --- magic link -----------------------------------------------------------------------------------


@transaction.atomic
def request_magic_link(request: HttpRequest, email: str, *, next_path: str = "/") -> None:
    """Email a 15-minute single-use sign-in link. Silent if the address is unknown."""
    email = email.strip().lower()
    user = User.objects.filter(email=email, is_active=True).first()
    if user is None:
        return
    raw = secrets.token_urlsafe(32)
    LoginToken.objects.create(
        user=user,
        purpose=LoginToken.Purpose.MAGIC_LINK,
        token_hash=token_hash(raw),
        expires_at=now() + MAGIC_LINK_TTL,
    )
    origin = f"{request.scheme}://{request.get_host()}"
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    url = f"{origin}/login/magic?token={raw}&next={safe_next}"
    from .tasks import send_magic_link

    transaction.on_commit(lambda: send_magic_link.delay(user_id=str(user.pk), url=url))


def login_with_magic_link(
    request: HttpRequest, token: str, *, remember: bool = False
) -> LoginResult:
    # Consume the token atomically (and commit it) before starting the session.
    used = LoginToken.objects.filter(
        token_hash=token_hash(token),
        purpose=LoginToken.Purpose.MAGIC_LINK,
        used_at__isnull=True,
        expires_at__gt=now(),
    ).update(used_at=now())
    record = (
        LoginToken.objects.select_related("user").filter(token_hash=token_hash(token)).first()
        if used
        else None
    )
    if record is None or not record.user.is_active:
        raise InvalidCode(_("This sign-in link is invalid or has expired."))
    return _begin_or_complete(request, record.user, method="magic_link", remember=remember)


# --- MFA ------------------------------------------------------------------------------------------


def pending_mfa_user(request: HttpRequest) -> tuple[User, dict[str, Any]]:
    pending = request.session.get(MFA_PENDING_KEY)
    if not pending or pending.get("expires", "") < now().isoformat():
        raise MFANotPending()
    user = User.objects.filter(pk=pending["user_id"], is_active=True).first()
    if user is None:
        raise MFANotPending()
    return user, pending


def check_totp(user: User, code: str) -> bool:
    """Valid current (±1 step) code for a confirmed device; each step is usable once."""
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    for device in user.mfa_devices.filter(confirmed_at__isnull=False):
        totp = pyotp.TOTP(device.secret)
        current = totp.timecode(now())
        for step in (current - 1, current, current + 1):
            if totp.generate_otp(step) == code and (
                device.last_used_step is None or step > device.last_used_step
            ):
                MFADevice.objects.filter(pk=device.pk).update(last_used_step=step)
                return True
    return False


def use_recovery_code(user: User, code: str) -> bool:
    normalised = code.strip().replace("-", "").replace(" ", "").lower()
    for rc in RecoveryCode.objects.filter(user=user, used_at__isnull=True):
        if check_password(normalised, rc.code_hash):
            rc.used_at = now()
            rc.save(update_fields=["used_at"])
            return True
    return False


def verify_mfa(request: HttpRequest, code: str) -> User:
    user, pending = pending_mfa_user(request)
    _check_lockout(user.email)
    if not (check_totp(user, code) or use_recovery_code(user, code)):
        _record(request, user.email, "mfa", user=user, success=False, reason="bad_code")
        raise InvalidCode()
    complete_login(
        request, user, method=pending["method"], remember=pending["remember"], mfa_verified=True
    )
    return user


def start_totp_setup(user: User) -> tuple[MFADevice, str]:
    """A new unconfirmed TOTP device; returns it and the otpauth:// URI."""
    MFADevice.objects.filter(user=user, confirmed_at__isnull=True).delete()
    secret = pyotp.random_base32()
    device = MFADevice.objects.create(user=user, secret=secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="TutorTrack")
    return device, uri


@transaction.atomic
def confirm_totp(user: User, device_id: str, code: str) -> list[str]:
    device = MFADevice.objects.filter(pk=device_id, user=user, confirmed_at__isnull=True).first()
    if device is None:
        raise InvalidCode(_("Start the set-up again."))
    totp = pyotp.TOTP(device.secret)
    if not totp.verify(code.strip().replace(" ", ""), valid_window=1):
        raise InvalidCode()
    device.confirmed_at = now()
    device.last_used_step = totp.timecode(now())
    device.save(update_fields=["confirmed_at", "last_used_step"])
    MFADevice.objects.filter(user=user, confirmed_at__isnull=False).exclude(pk=device.pk).delete()
    codes = regenerate_recovery_codes(user)
    from tutortrack.core.events import publish

    from .events import UserMFAEnabled

    publish(UserMFAEnabled(subject_id=user.pk, method="totp"), organisation_id=None)
    return codes


def regenerate_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = [secrets.token_hex(5) for _ in range(RECOVERY_CODE_COUNT)]
    RecoveryCode.objects.bulk_create(
        [RecoveryCode(user=user, code_hash=make_password(c)) for c in codes]
    )
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def disable_mfa(user: User) -> None:
    MFADevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()


# --- sessions -------------------------------------------------------------------------------------


def revoke_session(session: UserSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = now()
        session.save(update_fields=["revoked_at"])


def revoke_all_sessions(user: User, *, except_id: Any = None) -> int:
    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_id is not None:
        qs = qs.exclude(pk=except_id)
    return qs.update(revoked_at=now())


def sign_out(request: HttpRequest) -> None:
    sid = request.session.get(SID_KEY)
    if sid:
        UserSession.objects.filter(pk=sid, revoked_at__isnull=True).update(revoked_at=now())
    logout(request)


# --- passwords ------------------------------------------------------------------------------------


def request_password_reset(request: HttpRequest, email: str) -> None:
    """Email a 1-hour single-use reset link; silent for unknown addresses."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    user = User.objects.filter(email=email.strip().lower(), is_active=True).first()
    if user is None:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = f"{request.scheme}://{request.get_host()}/reset-password?uid={uid}&token={token}"
    from .tasks import send_password_reset

    transaction.on_commit(lambda: send_password_reset.delay(user_id=str(user.pk), url=url))


@transaction.atomic
def reset_password(uid: str, token: str, new_password: str) -> User:
    from django.contrib.auth.password_validation import validate_password
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode

    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uid).decode())
    except (ValueError, User.DoesNotExist, UnicodeDecodeError) as exc:
        raise InvalidCode(_("This reset link is invalid or has expired.")) from exc
    # The token embeds the password hash and last login, so it is single-use.
    if not default_token_generator.check_token(user, token):
        raise InvalidCode(_("This reset link is invalid or has expired."))
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    revoke_all_sessions(user)
    return user


@transaction.atomic
def change_password(request: HttpRequest, user: User, current: str, new_password: str) -> None:
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.password_validation import validate_password

    if not user.check_password(current):
        raise AuthenticationFailed(_("Your current password is incorrect."))
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    update_session_auth_hash(request, user)
    revoke_all_sessions(user, except_id=request.session.get(SID_KEY))
