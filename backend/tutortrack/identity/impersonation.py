"""Impersonation (FR-03-7): owners/admins view the app as a tutor, client or student of
their own organisation. Read-only unless the owner turns on write access. Every request
is audited with the impersonator (``RequestContext.impersonator_id``) and the start/end
are recorded as events. Platform-staff support access (with a reason) is ``support.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now

from .events import ImpersonationEnded, ImpersonationStarted
from .models import Membership, User

SESSION_KEY = "tt_impersonation"
TARGET_ROLES = {Membership.Role.TUTOR, Membership.Role.CLIENT, Membership.Role.STUDENT}
ALWAYS_ALLOWED = ("/api/v1/impersonate/stop", "/api/v1/auth/logout")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
GetResponse = Callable[[HttpRequest], HttpResponse]


class ImpersonationMiddleware:
    """Swaps ``request.user`` for the impersonated user (after authentication)."""

    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.impersonator = None  # type: ignore[attr-defined]
        user = getattr(request, "user", None)
        state = request.session.get(SESSION_KEY) if hasattr(request, "session") else None
        if state and user is not None and user.is_authenticated:
            if str(user.pk) != state.get("impersonator_id"):
                request.session.pop(SESSION_KEY, None)
            else:
                target = User.objects.filter(pk=state["target_user_id"], is_active=True).first()
                if target is None:
                    request.session.pop(SESSION_KEY, None)
                else:
                    request.impersonator = user  # type: ignore[attr-defined]
                    request.impersonation = state  # type: ignore[attr-defined]
                    request.user = target
        return self.get_response(request)


def _problem(status: int, code: str, detail: str) -> JsonResponse:
    body = {
        "type": f"https://docs.tutortrack.app/problems/{code}",
        "title": "Impersonation",
        "status": status,
        "detail": detail,
    }
    return JsonResponse(body, status=status, content_type="application/problem+json")


def check_request(request: HttpRequest) -> HttpResponse | None:
    """After tenant resolution: stay inside the organisation and respect read-only."""
    state = getattr(request, "impersonation", None)
    if not state:
        return None
    organisation = getattr(request, "organisation", None)
    if organisation is None or str(organisation.pk) != state["organisation_id"]:
        return _problem(403, "impersonation-other-organisation", _("Stop impersonating first."))
    if request.path.startswith(ALWAYS_ALLOWED):
        return None
    if request.method not in SAFE_METHODS and not state.get("write"):
        return _problem(
            403, "impersonation-read-only", _("You are viewing as someone else (read-only).")
        )
    return None


@transaction.atomic
def start(request: HttpRequest, membership_id: Any, *, write: bool = False) -> Membership:
    actor = request.user
    if getattr(request, "impersonator", None) is not None:
        raise BusinessRuleViolation(_("Stop the current impersonation first."))
    if not has_perm(actor, "impersonation.start"):
        raise PermissionDenied()
    if write and not has_perm(actor, "impersonation.write"):
        raise PermissionDenied(_("Only the owner can make changes while impersonating."))
    target = Membership.objects.filter(pk=membership_id, status=Membership.Status.ACTIVE).first()
    if target is None or target.role not in TARGET_ROLES or target.user_id == actor.pk:
        raise BusinessRuleViolation(_("You can view as tutors, clients and students only."))
    request.session[SESSION_KEY] = {
        "impersonator_id": str(actor.pk),
        "target_user_id": str(target.user_id),
        "membership_id": str(target.pk),
        "organisation_id": str(target.organisation_id),
        "write": write,
        "started_at": now().isoformat(),
    }
    audit.record(target, "impersonation_start", {"write": [None, write]})
    publish(
        ImpersonationStarted(
            subject_id=target.pk,
            impersonator_id=str(actor.pk),
            target_user_id=str(target.user_id),
            write=write,
        )
    )
    return target


@transaction.atomic
def stop(request: HttpRequest) -> None:
    state = request.session.pop(SESSION_KEY, None)
    if not state:
        return
    if state.get("support_session_id"):
        from .support import end

        end(state["support_session_id"])
    target = Membership.objects.filter(pk=state["membership_id"]).first()
    if target is not None:
        audit.record(target, "impersonation_end")
        publish(
            ImpersonationEnded(
                subject_id=target.pk,
                impersonator_id=state["impersonator_id"],
                target_user_id=state["target_user_id"],
            )
        )
