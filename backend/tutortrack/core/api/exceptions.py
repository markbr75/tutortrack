"""RFC 7807 Problem Details for every API error.

{"type": "...", "title": "...", "status": 422, "detail": "...",
 "errors": {"field": ["message"]}, "request_id": "..."}
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import exception_handler

from ..context import get_request_context
from ..exceptions import DomainError

PROBLEM_BASE = "https://docs.tutortrack.app/problems/"
CONTENT_TYPE = "application/problem+json"


RESERVED = frozenset({"type", "title", "status", "detail", "request_id"})


def _problem(
    status: int, problem_type: str, title: str, detail: Any, extra: dict[str, Any] | None = None
) -> Response:
    body: dict[str, Any] = {
        # Extension members first so they can never overwrite the standard ones.
        **{k: v for k, v in (extra or {}).items() if k not in RESERVED},
        "type": problem_type
        if problem_type.startswith(("http", "about:"))
        else PROBLEM_BASE + problem_type,
        "title": title,
        "status": status,
        "detail": detail,
    }
    request_id = get_request_context().request_id
    if request_id:
        body["request_id"] = request_id
    return Response(body, status=status, content_type=CONTENT_TYPE)


def _flatten_errors(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return {k: _flatten_errors(v) if isinstance(v, dict) else v for k, v in detail.items()}
    if isinstance(detail, list):
        return {"non_field_errors": detail}
    return {"non_field_errors": [detail]}


def problem_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        domain = _problem(exc.status_code, exc.problem_type, exc.title, exc.detail, exc.extra)
        if "retry_after" in exc.extra:
            domain["Retry-After"] = str(exc.extra["retry_after"])
        return domain

    if isinstance(exc, Http404):
        exc = drf.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None  # unhandled -> 500 via Django (and Sentry)

    if isinstance(exc, drf.ValidationError):
        problem = _problem(
            400,
            "validation-error",
            "Validation failed",
            "One or more fields are invalid.",
            {"errors": _flatten_errors(exc.detail)},
        )
    else:
        codes = exc.get_codes() if isinstance(exc, drf.APIException) else "error"
        code = codes if isinstance(codes, str) else "error"
        default_detail = getattr(exc, "default_detail", "Error")
        problem = _problem(
            response.status_code,
            code.replace("_", "-"),
            str(default_detail),
            response.data.get("detail", response.data)
            if isinstance(response.data, dict)
            else response.data,
        )
    for header in ("WWW-Authenticate", "Retry-After", "Allow"):
        if header in response:
            problem[header] = response[header]
    return problem
