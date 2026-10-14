"""Video provider webhooks (E22-T10): attendance and recordings.

* ``/webhooks/zoom``: Zoom signs each request (``x-zm-signature`` = ``v0=`` + hex
  HMAC-SHA256 of ``v0:{timestamp}:{body}`` with the app's secret token) and validates the
  endpoint with a ``plainToken`` challenge. Requests older than five minutes are refused.
* ``/webhooks/lessonspace/<token>``: the URL itself is the credential: an HMAC token
  naming the organisation and lesson (``integrations.routes.callback_token``), passed to
  Lessonspace when the space is launched.
"""

from __future__ import annotations

import json
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from tutortrack.integrations import routes

from .. import video

MAX_SKEW = 300  # seconds


@csrf_exempt
def zoom_webhook(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)
    secret = str(settings.INTEGRATIONS.get("ZOOM_WEBHOOK_SECRET", ""))
    if not secret:
        return HttpResponse(status=403)
    try:
        event: dict[str, Any] = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    timestamp = request.headers.get("x-zm-request-timestamp", "")
    message = f"v0:{timestamp}:".encode() + request.body
    if not routes.verify_hmac(
        secret, message, request.headers.get("x-zm-signature", ""), prefix="v0="
    ):
        return HttpResponse(status=401)
    try:
        if abs(time.time() - int(timestamp)) > MAX_SKEW:
            return HttpResponse(status=401)
    except ValueError:
        return HttpResponse(status=401)
    if event.get("event") == "endpoint.url_validation":
        plain = str((event.get("payload") or {}).get("plainToken", ""))
        return JsonResponse(
            {"plainToken": plain, "encryptedToken": routes.hmac_hex(secret, plain.encode())}
        )
    video.handle_zoom_event(event)
    return HttpResponse(status=200)


@csrf_exempt
def lessonspace_webhook(request: HttpRequest, token: str) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)
    parsed = routes.read_callback_token("lessonspace", token)
    if parsed is None:
        return HttpResponse(status=403)
    try:
        body: dict[str, Any] = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    organisation_id, lesson_id = parsed
    video.handle_lessonspace_event(
        organisation_id,
        lesson_id,
        request.GET.get("event", ""),
        body if isinstance(body, dict) else {},
    )
    return HttpResponse(status=200)
