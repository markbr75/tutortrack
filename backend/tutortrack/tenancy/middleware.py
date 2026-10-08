"""Resolves the organisation for each request and sets the tenant context (FR-02-3).

After resolution it also attaches the user's membership (``request.membership``), applies
their branch scope (FR-02-2) and remembers the organisation as the user's last active one
(FR-02-7). Database row-level security follows automatically: ``core.db`` sends the tenant
in context to Postgres before each query.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, JsonResponse
from django.http.response import HttpResponseRedirectBase
from django.utils.module_loading import import_string

from tutortrack.core.context import (
    reset_branch_ids,
    reset_organisation,
    set_branch_ids,
    set_organisation,
)

from .resolution import SESSION_KEY, Resolution

GetResponse = Callable[[HttpRequest], HttpResponse]


class HttpResponsePermanentRedirect308(HttpResponseRedirectBase):
    """308 keeps the method and body, so API POSTs survive a slug change."""

    status_code = 308
    allowed_schemes = ["http", "https"]


def _not_found(request: HttpRequest) -> HttpResponse:
    if request.path.startswith("/api/"):
        body = {
            "type": "https://docs.tutortrack.app/problems/organisation-not-found",
            "title": "Organisation not found",
            "status": 404,
            "detail": "No organisation exists at this address.",
        }
        return JsonResponse(body, status=404, content_type="application/problem+json")
    return HttpResponseNotFound("Organisation not found")


class TenantMiddleware:
    def __init__(self, get_response: GetResponse):
        self.get_response = get_response
        path = getattr(settings, "TENANT_RESOLVER", "tutortrack.tenancy.resolution.resolve")
        self.resolve: Callable[[HttpRequest], Resolution] = import_string(path)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path in ("/healthz", "/readyz"):
            request.organisation = None  # type: ignore[attr-defined]
            request.membership = None  # type: ignore[attr-defined]
            return self.get_response(request)

        resolution = self.resolve(request)
        if resolution.redirect_to:
            return HttpResponsePermanentRedirect308(resolution.redirect_to)
        if resolution.unknown:
            return _not_found(request)

        organisation = resolution.organisation
        org_token = set_organisation(organisation)
        membership = self._membership(request, organisation)
        request.organisation = organisation  # type: ignore[attr-defined]
        request.membership = membership  # type: ignore[attr-defined]
        branch_token = set_branch_ids(self._branch_ids(membership))
        if organisation is not None:
            structlog.contextvars.bind_contextvars(organisation_id=str(organisation.pk))
        try:
            if membership is not None:
                self._remember(request, membership)
            return self.get_response(request)
        finally:
            reset_branch_ids(branch_token)
            reset_organisation(org_token)

    @staticmethod
    def _membership(request: HttpRequest, organisation: Any) -> Any:
        user = getattr(request, "user", None)
        if organisation is None or user is None or not user.is_authenticated:
            return None
        from tutortrack.identity.selectors import membership_for

        return membership_for(user, organisation.pk)

    @staticmethod
    def _branch_ids(membership: Any) -> Any:
        if membership is None:
            return None
        from tutortrack.identity.selectors import branch_ids_for

        return branch_ids_for(membership)

    @staticmethod
    def _remember(request: HttpRequest, membership: Any) -> None:
        from tutortrack.identity.services import touch_last_active

        session = getattr(request, "session", None)
        org_id = str(membership.organisation_id)
        if session is not None and session.get(SESSION_KEY) != org_id:
            session[SESSION_KEY] = org_id
        touch_last_active(membership)


def _problem(status: int, code: str, title: str, detail: str) -> JsonResponse:
    body = {
        "type": f"https://docs.tutortrack.app/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    return JsonResponse(body, status=status, content_type="application/problem+json")


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OrganisationStatusMiddleware:
    """Enforces suspension and closure (FR-02-3, FR-02-8). Runs after TenantMiddleware.

    * Closed: 410 Gone for everyone except platform staff.
    * Suspended: owners/admins (and platform staff) keep read-only access, plus writes to
      ``SUSPENDED_ORG_WRITE_ALLOWLIST`` (billing, so they can pay and reactivate); everyone
      else, including portal users, gets 403 ``organisation-suspended``.
    Authentication endpoints stay reachable so owners can still sign in.
    """

    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        organisation = getattr(request, "organisation", None)
        if organisation is None or organisation.is_operational:
            return self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            return self.get_response(request)
        if request.path.startswith(tuple(settings.ORG_STATUS_EXEMPT_PATHS)):
            return self.get_response(request)

        if organisation.is_closed:
            return _problem(
                410,
                "organisation-closed",
                "Account closed",
                "This organisation's account has been closed.",
            )
        membership = getattr(request, "membership", None)
        if membership is None or not membership.is_owner_or_admin:
            return _problem(
                403,
                "organisation-suspended",
                "Account suspended",
                "This account is temporarily unavailable. Please contact the organisation.",
            )
        if request.method not in SAFE_METHODS and not request.path.startswith(
            tuple(settings.SUSPENDED_ORG_WRITE_ALLOWLIST)
        ):
            return _problem(
                423,
                "organisation-read-only",
                "Account suspended",
                "The account is suspended and read-only. Update billing to reactivate it.",
            )
        return self.get_response(request)
