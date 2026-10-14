"""Change your sign-in email (FR-03-9, gap batch G2).

1. ``request_change``: the signed-in person confirms their password (when they have one)
   and gives the new address. We email a 24-hour link to the **new** address and tell the
   **old** address that a change was asked for.
2. ``confirm_change``: the link (a signed token bound to the old and new address, so it
   works once) switches the email, marks it verified, signs out every other session and
   tells the old address it has changed, with a hint to contact support if it wasn't them.

Both steps are audited. Linked SSO accounts keep working (they match by subject).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpRequest
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .auth import SID_KEY, AuthenticationFailed, InvalidCode, revoke_all_sessions
from .events import UserEmailChanged
from .models import User

SALT = "tutortrack.identity.email-change"
MAX_AGE = 24 * 3600


def _invalid(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {"new_email": [message]}})


def change_token(user: User, new_email: str) -> str:
    return signing.dumps({"u": str(user.pk), "o": user.email, "n": new_email}, salt=SALT)


@transaction.atomic
def request_change(request: HttpRequest, user: User, *, new_email: str, password: str = "") -> str:
    """Email a confirmation link to ``new_email``. Returns the (normalised) new address."""
    from .tasks import send_email_change_notice, send_email_change_verification

    if user.has_usable_password() and not user.check_password(password or ""):
        raise AuthenticationFailed(_("Your password is incorrect."))
    email = new_email.strip().lower()
    try:
        validate_email(email)
    except DjangoValidationError as exc:
        raise _invalid(_("Enter a valid email address.")) from exc
    if email == user.email:
        raise _invalid(_("That is already your email address."))
    if User.objects.filter(email=email).exclude(pk=user.pk).exists():
        raise _invalid(_("Another account uses this email address."))
    url = f"{settings.APP_URL}/confirm-email?token={change_token(user, email)}"
    audit.record(user, "email_change_requested", {"email": [user.email, email]})
    user_id, old = str(user.pk), user.email
    transaction.on_commit(
        lambda: send_email_change_verification.delay(user_id=user_id, email=email, url=url)
    )
    transaction.on_commit(
        lambda: send_email_change_notice.delay(email=old, new_email=email, done=False)
    )
    return email


@transaction.atomic
def confirm_change(token: str, *, request: HttpRequest | None = None) -> User:
    """Apply a change from its link. Other sessions are signed out; when the link is opened
    in a browser signed in as this person, that session stays."""
    from .tasks import send_email_change_notice

    try:
        data: dict[str, Any] = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidCode(_("This link is invalid or has expired.")) from exc
    user = (
        User.objects.select_for_update().filter(pk=str(data.get("u", "")), is_active=True).first()
    )
    if user is None or user.email != data.get("o"):
        raise InvalidCode(_("This link is invalid or has expired."))
    new_email = str(data.get("n", ""))
    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
        raise InvalidCode(_("Another account now uses this email address."))
    old = user.email
    with audit.track(user, action="email_change"):
        user.email = new_email
        user.email_verified_at = now()
        user.save(update_fields=["email", "email_verified_at"])
    keep = None
    if request is not None and getattr(getattr(request, "user", None), "pk", None) == user.pk:
        keep = request.session.get(SID_KEY)
    revoke_all_sessions(user, except_id=keep)
    publish(UserEmailChanged(subject_id=user.pk))
    transaction.on_commit(
        lambda: send_email_change_notice.delay(email=old, new_email=new_email, done=True)
    )
    return user
