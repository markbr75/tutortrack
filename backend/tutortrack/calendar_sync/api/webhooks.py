"""Push notifications from Google Calendar (watch channels) and Microsoft Graph
(subscriptions). Each carries the HMAC channel token we registered
(``services.channel_token``): it names the organisation and sync state and is verified
before anything is looked up. A valid notification signals ``changed`` to the connection's
workflow, which syncs incrementally (FR-22-1 AC: busy within 2 minutes)."""

from __future__ import annotations

import json
from typing import Any

import structlog
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tutortrack.core.context import tenant_context
from tutortrack.core.workflows import ops

from ..models import SyncState
from ..processes import calendar_workflow_id
from ..services import read_channel_token

logger = structlog.get_logger(__name__)


def _signal(token: str, channel_id: str) -> bool:
    parsed = read_channel_token(token)
    if parsed is None:
        return False
    org, state_id = parsed
    with tenant_context(org):
        state = SyncState.objects.filter(pk=state_id).first()
        if state is None or (channel_id and state.channel_id != channel_id):
            return False
        workflow = calendar_workflow_id(org, state.connection_id)
    ops.signal_now(workflow, "changed")
    return True


@csrf_exempt
@require_POST
def google_calendar(request: HttpRequest) -> HttpResponse:
    token = request.headers.get("X-Goog-Channel-Token", "")
    channel = request.headers.get("X-Goog-Channel-ID", "")
    state = request.headers.get("X-Goog-Resource-State", "")
    if read_channel_token(token) is None:
        return HttpResponse(status=403)
    if state == "sync":
        return HttpResponse(status=200)  # the channel was just created
    if not _signal(token, channel):
        logger.info("calendar_sync.unknown_channel")  # stale channel: let it expire
    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def microsoft_graph(request: HttpRequest) -> HttpResponse:
    validation = request.GET.get("validationToken")
    if validation is not None:  # subscription handshake: echo the token as plain text
        return HttpResponse(validation[:1000], content_type="text/plain", status=200)
    try:
        body: dict[str, Any] = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)
    accepted = 0
    for note in body.get("value", [])[:100]:
        token = str(note.get("clientState", ""))
        if read_channel_token(token) is None:
            continue
        if _signal(token, str(note.get("subscriptionId", ""))):
            accepted += 1
    return HttpResponse(status=202 if accepted or not body.get("value") else 403)
