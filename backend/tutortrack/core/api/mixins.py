"""Optimistic concurrency for updates via ``ETag`` / ``If-Match``."""

from __future__ import annotations

import hashlib
from typing import Any

from django.db import models
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.request import Request
from rest_framework.response import Response


class PreconditionFailed(APIException):
    status_code = status.HTTP_412_PRECONDITION_FAILED
    default_detail = "The resource has changed since you fetched it. Reload and try again."
    default_code = "precondition_failed"


class PreconditionRequired(APIException):
    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    default_detail = "This update requires an If-Match header with the resource's ETag."
    default_code = "precondition_required"


def etag_for(instance: models.Model) -> str:
    version = getattr(instance, "updated_at", None)
    raw = f"{instance._meta.label_lower}:{instance.pk}:{version.isoformat() if version else ''}"
    return f'W/"{hashlib.sha256(raw.encode()).hexdigest()[:32]}"'


class ConditionalUpdateMixin:
    """For ``GenericViewSet`` subclasses. ``require_if_match = True`` makes If-Match
    mandatory (428 without it); otherwise it is checked only when sent."""

    supports_if_match = True
    require_if_match = False

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response: Response = super().retrieve(request, *args, **kwargs)  # type: ignore[misc]
        response["ETag"] = etag_for(self.get_object())  # type: ignore[attr-defined]
        return response

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()  # type: ignore[attr-defined]
        if_match = request.headers.get("If-Match")
        if if_match is None:
            if self.require_if_match:
                raise PreconditionRequired()
        elif if_match.strip() not in {etag_for(instance), "*"}:
            raise PreconditionFailed()
        response: Response = super().update(request, *args, **kwargs)  # type: ignore[misc]
        instance.refresh_from_db()
        response["ETag"] = etag_for(instance)
        return response
