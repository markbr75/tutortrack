"""``Idempotency-Key`` support for POST requests (docs/02-architecture.md §8).

* Same key + same request  -> the stored response is replayed (``Idempotent-Replayed: true``).
* Same key + different body -> 422 ``idempotency-key-reused``.
* Same key while the first request is still running -> 409 ``idempotency-request-in-progress``.
* 5xx responses are not stored, so the client can retry.

Keys are scoped per organisation and per principal (user id, or a hash of the
Authorization header for API token clients, which authenticate later in DRF).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse

from .context import current_organisation_id
from .models import IdempotencyRecord
from .time import now

HEADER = "Idempotency-Key"
MAX_KEY_LENGTH = 255
MAX_STORED_BODY = 1024 * 1024


def _problem(status: int, problem_type: str, title: str, detail: str) -> HttpResponse:
    body = {"type": problem_type, "title": title, "status": status, "detail": detail}
    return HttpResponse(json.dumps(body), status=status, content_type="application/problem+json")


def _principal(request: HttpRequest) -> str | None:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"
    auth = request.headers.get("Authorization")
    if auth:
        return "token:" + hashlib.sha256(auth.encode()).hexdigest()[:40]
    return None


def _request_hash(request: HttpRequest) -> str:
    digest = hashlib.sha256()
    digest.update(request.method.encode() if request.method else b"")
    digest.update(request.get_full_path().encode())
    digest.update(request.body)
    return digest.hexdigest()


class IdempotencyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        key = request.headers.get(HEADER)
        if request.method != "POST" or not key:
            return self.get_response(request)
        if len(key) > MAX_KEY_LENGTH:
            return _problem(
                400,
                "invalid-idempotency-key",
                "Invalid Idempotency-Key",
                f"{HEADER} must be at most {MAX_KEY_LENGTH} characters.",
            )
        principal = _principal(request)
        if principal is None:
            return self.get_response(request)  # unauthenticated: the view will reject it

        org_id = current_organisation_id()
        request_hash = _request_hash(request)
        ttl = timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS)

        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    organisation_id=org_id,
                    principal=principal,
                    key=key,
                    request_hash=request_hash,
                    expires_at=now() + ttl,
                )
        except IntegrityError:
            existing = IdempotencyRecord.objects.get(
                organisation_id=org_id, principal=principal, key=key
            )
            replay = self._handle_existing(existing, request_hash)
            if replay is not None:
                return replay
            # Expired record was replaced; fall through with the fresh one.
            record = IdempotencyRecord.objects.create(
                organisation_id=org_id,
                principal=principal,
                key=key,
                request_hash=request_hash,
                expires_at=now() + ttl,
            )

        try:
            response = self.get_response(request)
        except Exception:
            record.delete()
            raise

        if response.status_code >= 500 or getattr(response, "streaming", False):
            record.delete()
            return response

        body = bytes(response.content)
        if len(body) > MAX_STORED_BODY:
            record.delete()
            return response
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = response.status_code
        record.response_body = body
        record.response_content_type = response.get("Content-Type", "")
        record.save(
            update_fields=["status", "response_status", "response_body", "response_content_type"]
        )
        return response

    @staticmethod
    def _handle_existing(record: IdempotencyRecord, request_hash: str) -> HttpResponse | None:
        if record.expires_at <= now():
            record.delete()
            return None
        if record.request_hash != request_hash:
            return _problem(
                422,
                "idempotency-key-reused",
                "Idempotency-Key reused",
                "This Idempotency-Key was already used with a different request.",
            )
        if record.status == IdempotencyRecord.Status.IN_PROGRESS:
            return _problem(
                409,
                "idempotency-request-in-progress",
                "Request in progress",
                "A request with this Idempotency-Key is still being processed.",
            )
        response = HttpResponse(
            bytes(record.response_body or b""),
            status=record.response_status or 200,
            content_type=record.response_content_type or "application/json",
        )
        response["Idempotent-Replayed"] = "true"
        return response
