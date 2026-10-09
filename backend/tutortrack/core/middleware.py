"""Request middleware: request ids and logging context, user context and timezone.

Tenant resolution lives in ``tutortrack.tenancy.middleware`` (E02)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from .context import (
    RequestContext,
    reset_request_context,
    set_request_context,
    update_request_context,
)
from .time import is_valid_timezone

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GetResponse = Callable[[HttpRequest], HttpResponse]


def client_ip(request: HttpRequest) -> str | None:
    """Client IP, trusting ``NUM_PROXIES`` hops of X-Forwarded-For (0 = ignore the header)."""
    num_proxies = getattr(settings, "NUM_PROXIES", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if num_proxies and forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= num_proxies:
            return hops[-num_proxies]
    addr: str | None = request.META.get("REMOTE_ADDR")
    return addr


class RequestContextMiddleware:
    """Assigns a request id, binds it to logs and exposes it as ``X-Request-ID``."""

    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        token = set_request_context(
            RequestContext(
                request_id=request_id,
                ip=client_ip(request),
                user_agent=request.headers.get("User-Agent", "")[:500],
            )
        )
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_context(token)
            structlog.contextvars.clear_contextvars()
        response["X-Request-ID"] = request_id
        return response


class UserContextMiddleware:
    """After authentication: record the user in context and activate their timezone."""

    def __init__(self, get_response: GetResponse):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            impersonator = getattr(request, "impersonator", None)
            update_request_context(
                user_id=user.pk, impersonator_id=impersonator.pk if impersonator else None
            )
            structlog.contextvars.bind_contextvars(user_id=str(user.pk))
            tz_name = getattr(user, "timezone", "")
            if tz_name and is_valid_timezone(tz_name):
                timezone.activate(tz_name)
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
