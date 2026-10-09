"""Every login (our API, Django admin, test clients) gets a tracked, revocable session."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.dispatch import receiver
from django.http import HttpRequest

from tutortrack.core.events import publish
from tutortrack.core.middleware import client_ip

from .events import UserLoggedIn
from .models import User, UserSession

SID_KEY = "tt_sid"


@receiver(user_logged_in, dispatch_uid="identity.track_session")
def track_session(sender: Any, request: HttpRequest | None, user: User, **_: Any) -> None:
    if request is None or not hasattr(request, "session"):
        return
    meta = getattr(request, "_tt_login_meta", {}) or {}
    with transaction.atomic():
        session = UserSession.objects.create(
            user=user,
            ip=client_ip(request),
            user_agent=request.headers.get("User-Agent", "")[:500],
            method=meta.get("method", "session"),
            remember=bool(meta.get("remember")),
            mfa_verified=bool(meta.get("mfa_verified")),
        )
        request.session[SID_KEY] = str(session.pk)
        publish(UserLoggedIn(subject_id=user.pk, method=session.method), organisation_id=None)
