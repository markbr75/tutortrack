"""Gap batch G4 endpoints for communications: the realtime notification stream, digest
preferences and Mailchimp/Brevo unsubscribe webhooks."""

from __future__ import annotations

from typing import Any

from django.core.handlers.asgi import ASGIRequest
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.context import require_organisation_id
from tutortrack.core.permissions import HasOrganisation

from .. import digests, realtime, selectors
from . import g4_serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


class EventStreamRenderer(BaseRenderer):
    """Lets ``Accept: text/event-stream`` (EventSource) through content negotiation; errors
    (401/403) are sent as one ``error`` event."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = "utf-8"

    def render(
        self, data: Any, accepted_media_type: Any = None, renderer_context: Any = None
    ) -> Any:
        return realtime.frame("error", data or {}).encode()


class NotificationStreamView(APIView):
    """Your in-app notifications as Server-Sent Events (G4, FR-13-8).

    Events: ``ready`` (with the unread count), ``notification`` (id, type, title, link)
    and ``read`` (some were marked read). Comments (``: keep-alive``) keep proxies from
    closing the connection. The stream ends after a few minutes and the browser
    reconnects. If it can't connect, keep polling ``/notifications/unread-count``."""

    permission_classes = AUTH
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    @extend_schema(
        responses={
            (200, "text/event-stream"): OpenApiResponse(
                OpenApiTypes.STR,
                examples=[
                    OpenApiExample(
                        "Events",
                        value='event: ready\ndata: {"unread": 2}\n\n'
                        'event: notification\ndata: {"id": "…", "title": "Lesson moved"}\n\n',
                    )
                ],
            )
        }
    )
    def get(self, request: Request) -> Any:
        organisation_id = require_organisation_id()
        unread = selectors.notifications_for(request.user).filter(read_at__isnull=True).count()
        channel = realtime.channel_name(organisation_id, request.user.pk)
        if isinstance(request._request, ASGIRequest):
            content: Any = realtime.async_stream(channel, unread=unread)
        else:
            content = realtime.sync_stream(channel, unread=unread)
        response = StreamingHttpResponse(content, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"  # nginx/ALB-style proxies: don't buffer
        return response


# --- digest preferences ---------------------------------------------------------------------------


class MyDigestsView(APIView):
    """The digest emails the signed-in person can get (G4, FR-13-2/7): on or off, the
    local time and (weekly) the day. Tutors: daily agenda and message digest; family
    contacts: weekly schedule and message digest; staff: message digest."""

    permission_classes = AUTH

    @extend_schema(responses=s.DigestPreferenceSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            s.DigestPreferenceSerializer(digests.my_digests(request.user), many=True).data
        )

    @extend_schema(
        request=s.DigestPreferenceWriteSerializer(many=True),
        responses=s.DigestPreferenceSerializer(many=True),
        examples=[
            OpenApiExample(
                "Agenda at 06:30",
                value=[{"kind": "tutor_agenda", "enabled": True, "send_time": "06:30"}],
                request_only=True,
            )
        ],
    )
    def put(self, request: Request) -> Response:
        payload = s.DigestPreferenceWriteSerializer(data=request.data, many=True)
        payload.is_valid(raise_exception=True)
        rows = digests.set_my_digests(request.user, list(payload.validated_data))
        return Response(s.DigestPreferenceSerializer(rows, many=True).data)


# --- Mailchimp / Brevo webhooks -------------------------------------------------------------------


@csrf_exempt
def marketing_webhook(request: HttpRequest, provider: str, token: str) -> HttpResponse:
    """Unsubscribes, cleaned addresses and spam reports from Mailchimp or Brevo (G4,
    FR-13-9). The URL carries a signed token naming the organisation and provider (neither
    service signs its webhooks); Mailchimp checks the URL with a GET first."""
    from .. import marketing_inbound

    route = marketing_inbound.read_webhook_token(token)
    if route is None or route["p"] != provider:
        return HttpResponse(status=403)
    if request.method == "GET":
        return HttpResponse(status=200)  # Mailchimp's URL validation
    if request.method != "POST":
        return HttpResponse(status=405)
    handled = marketing_inbound.handle_webhook(route, request)
    return HttpResponse(status=200 if handled is not None else 400)
