"""Session security (FR-03-2/3).

``SessionSecurityMiddleware`` (after AuthenticationMiddleware): signs out sessions that
were revoked ("sign out all devices", password change) or idle too long, and keeps
``last_seen_at`` fresh.

``MFAEnforcementMiddleware`` (after TenantMiddleware): when the organisation requires 2FA
for staff, staff without a confirmed device get 403 ``mfa-enrolment-required`` from the
API until they enrol (account and auth endpoints stay reachable).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse, JsonResponse

from tutortrack.core.time import now

from .models import UserSession

SID_KEY = "tt_sid"
TOUCH_INTERVAL = timedelta(minutes=5)
GetResponse = Callable[[HttpRequest], HttpResponse]


class SessionSecurityMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and hasattr(request, "session"):
            sid = request.session.get(SID_KEY)
            tracked = UserSession.objects.filter(pk=sid).first() if sid else None
            if tracked is None or not self._valid(tracked):
                logout(request)
            else:
                request.user_session = tracked  # type: ignore[attr-defined]
                request.session_last_seen = tracked.last_seen_at  # type: ignore[attr-defined]
                if now() - tracked.last_seen_at > TOUCH_INTERVAL:
                    UserSession.objects.filter(pk=tracked.pk).update(last_seen_at=now())
        return self.get_response(request)

    @staticmethod
    def _valid(tracked: UserSession) -> bool:
        if tracked.revoked_at is not None:
            return False
        if tracked.remember:
            return True
        idle = timedelta(hours=settings.SESSION_IDLE_TIMEOUT_HOURS)
        return now() - tracked.last_seen_at <= idle


def _problem(status: int, code: str, title: str, detail: str) -> JsonResponse:
    body = {
        "type": f"https://docs.tutortrack.app/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    return JsonResponse(body, status=status, content_type="application/problem+json")


class MFAEnforcementMiddleware:
    """Organisation security policy, applied once the tenant is known: impersonation
    boundaries, the org's staff idle timeout, and required 2FA for staff."""

    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from .impersonation import check_request

        problem = check_request(request)
        if problem is not None:
            return problem
        if self._idle_too_long(request):
            logout(request)
            return _problem(401, "session-expired", "Session expired", "Please sign in again.")
        if self._blocked(request):
            body = {
                "type": "https://docs.tutortrack.app/problems/mfa-enrolment-required",
                "title": "Two-factor authentication required",
                "status": 403,
                "detail": "Your organisation requires two-factor authentication. "
                "Set it up in your account settings to continue.",
            }
            return JsonResponse(body, status=403, content_type="application/problem+json")
        return self.get_response(request)

    @staticmethod
    def _idle_too_long(request: HttpRequest) -> bool:
        tracked = getattr(request, "user_session", None)
        last_seen = getattr(request, "session_last_seen", None)
        if tracked is None or last_seen is None or tracked.remember:
            return False
        if getattr(request, "membership", None) is None:
            return False
        from tutortrack.tenancy.settings_service import get_setting

        hours = int(get_setting("security.staff_idle_timeout_hours"))
        return bool(now() - last_seen > timedelta(hours=hours))

    @staticmethod
    def _blocked(request: HttpRequest) -> bool:
        membership = getattr(request, "membership", None)
        if membership is None or not request.path.startswith("/api/"):
            return False
        if request.path.startswith(tuple(settings.MFA_ENROLMENT_EXEMPT_PATHS)):
            return False
        if getattr(request, "impersonator", None) is not None:
            return False  # the real user's own session already passed this check
        from .roles import ROLES

        role = ROLES.get(membership.role)
        if role is None or not role.is_staff:
            return False
        from tutortrack.tenancy.settings_service import get_setting

        if not get_setting("security.require_mfa_for_staff"):
            return False
        return not request.user.has_mfa  # type: ignore[union-attr]
