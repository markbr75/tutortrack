"""Communications API (E13 §4)."""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import tenant_context
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import registry, render, selectors, services
from ..models import CommunicationPreference, InAppNotification, Message
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _setting_out(key: str) -> dict[str, Any]:
    e = services.effective(key)
    return {
        "key": key,
        "label": e.type.label,
        "category": e.type.category,
        "audience": e.type.audience,
        "channels": list(e.channels),
        "available_channels": list(e.type.channels),
        "enabled": e.enabled,
        "timing": list(e.timing),
        "has_timing": bool(e.type.default_timing),
        "transactional": e.type.transactional,
        "customised": e.customised,
    }


def _type(key: str) -> registry.NotificationType:
    try:
        return registry.get(key)
    except KeyError:
        raise NotFound() from None


class NotificationSettingsView(APIView):
    """Every notification type with the organisation's choice (FR-13-2)."""

    permission_classes = perms({"GET": "comms.settings.manage"})

    @extend_schema(responses=s.NotificationSettingSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response([_setting_out(t.key) for t in registry.all_types()])


class NotificationSettingView(APIView):
    permission_classes = perms({"PUT": "comms.settings.manage"})

    @extend_schema(
        request=s.NotificationSettingUpdateSerializer, responses=s.NotificationSettingSerializer
    )
    def put(self, request: Request, key: str) -> Response:
        _type(key)
        payload = s.NotificationSettingUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.update_setting(key, **payload.validated_data)
        return Response(_setting_out(key))


def _template_out(key: str, channel: str) -> dict[str, Any]:
    t = _type(key)
    source = services.template_for(key, channel)
    if source is None:
        source = services.TemplateSource("", "", False, 0)
    return {
        "type_key": key,
        "channel": channel,
        "subject": source.subject,
        "body": source.body,
        "customised": source.customised,
        "version": source.version,
        "variables": list(t.variables),
    }


class TemplateView(APIView):
    """A type's template for one channel: the organisation's override or the default.
    ``PUT`` saves a new version; ``DELETE`` reverts to the default."""

    permission_classes = perms(
        {
            "GET": "comms.template.manage",
            "PUT": "comms.template.manage",
            "DELETE": "comms.template.manage",
        }
    )

    @extend_schema(responses=s.TemplateSerializer)
    def get(self, request: Request, key: str, channel: str) -> Response:
        return Response(_template_out(key, channel))

    @extend_schema(request=s.TemplateWriteSerializer, responses=s.TemplateSerializer)
    def put(self, request: Request, key: str, channel: str) -> Response:
        _type(key)
        payload = s.TemplateWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.save_template(key, channel, user=request.user, **payload.validated_data)
        return Response(_template_out(key, channel))

    @extend_schema(responses=s.TemplateSerializer)
    def delete(self, request: Request, key: str, channel: str) -> Response:
        _type(key)
        services.revert_template(key, channel)
        return Response(_template_out(key, channel))


class TemplatePreviewView(APIView):
    """Render a template (the saved one, or the draft sent) with sample data."""

    permission_classes = perms({"POST": "comms.template.manage"})

    @extend_schema(request=s.PreviewRequestSerializer, responses=s.PreviewSerializer)
    def post(self, request: Request, key: str, channel: str) -> Response:
        _type(key)
        payload = s.PreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subject, body = services.preview(key, channel, **payload.validated_data)
        return Response({"subject": subject, "body": body, "segments": render.sms_segments(body)})


class TemplateTestView(APIView):
    """Send the sample message to yourself (email or your notifications)."""

    permission_classes = perms({"POST": "comms.template.manage"})

    @extend_schema(request=None, responses=s.MessageSerializer)
    def post(self, request: Request, key: str, channel: str) -> Response:
        _type(key)
        message = services.test_send(key, channel, user=request.user)
        return Response(s.MessageSerializer(message).data)


class MessageFilter(filters.FilterSet):
    target_type = filters.CharFilter()
    target_id = filters.CharFilter()
    related_type = filters.CharFilter()
    related_id = filters.CharFilter()
    channel = filters.ChoiceFilter(choices=[("email", "Email"), ("sms", "Text message")])
    status = filters.MultipleChoiceFilter(choices=Message.Status.choices)

    class Meta:
        model = Message
        fields: list[str] = []


class MessageViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """The message log (FR-13-4): what was sent to whom, with delivery events."""

    model = Message
    serializer_class = s.MessageSerializer
    filterset_class = MessageFilter
    permission_classes = perms({"GET": "comms.message.view_log"})

    def get_tenant_queryset(self) -> QuerySet[Message]:
        return selectors.messages(self.request.user).prefetch_related("events")


class NotificationViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Your in-app notifications (the bell). Poll ``unread-count``."""

    model = InAppNotification
    serializer_class = s.InAppSerializer
    permission_classes = AUTH

    def get_tenant_queryset(self) -> QuerySet[InAppNotification]:
        return selectors.notifications_for(self.request.user)

    @extend_schema(responses=s.UnreadCountSerializer)
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request: Request) -> Response:
        unread = self.get_tenant_queryset().filter(read_at__isnull=True).count()
        return Response({"unread": unread})

    @extend_schema(request=s.MarkReadSerializer, responses=s.UnreadCountSerializer)
    @action(detail=False, methods=["post"], url_path="read")
    def mark_read(self, request: Request) -> Response:
        payload = s.MarkReadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.mark_read(request.user, payload.validated_data.get("ids"))
        unread = self.get_tenant_queryset().filter(read_at__isnull=True).count()
        return Response({"unread": unread})


class PreferencesView(APIView):
    """A contact's or tutor's channel choices per category (FR-13-5)."""

    permission_classes = perms(
        {"GET": "comms.preferences.manage", "PUT": "comms.preferences.manage"}
    )

    @extend_schema(
        responses=s.PreferencesSerializer,
        parameters=[OpenApiParameter("person_type", str), OpenApiParameter("person_id", str)],
    )
    def get(self, request: Request) -> Response:
        person_type = request.query_params.get("person_type", "")
        person_id = request.query_params.get("person_id", "")
        rows = CommunicationPreference.objects.filter(person_type=person_type, person_id=person_id)
        return Response(
            {
                "person_type": person_type,
                "person_id": person_id,
                "preferences": [{"category": r.category, "channels": r.channels} for r in rows],
            }
        )

    @extend_schema(request=s.PreferencesSerializer, responses=s.PreferencesSerializer)
    def put(self, request: Request) -> Response:
        payload = s.PreferencesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        for row in data["preferences"]:
            services.set_preference(
                data["person_type"], data["person_id"], row["category"], row["channels"]
            )
        return Response(data)


class UnsubscribeView(APIView):
    """One-click unsubscribe from the link in an email (RFC 8058)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    def _data(self, token: str) -> dict[str, str]:
        data = services.read_unsubscribe(token)
        if data is None:
            raise NotFound()
        return data

    @extend_schema(responses=s.UnsubscribeSerializer)
    def get(self, request: Request, token: str) -> Response:
        return Response({"category": self._data(token)["c"], "done": False})

    @extend_schema(request=None, responses=s.UnsubscribeSerializer)
    def post(self, request: Request, token: str) -> Response:
        data = self._data(token)
        with tenant_context(data["o"]):
            services.unsubscribe(data)
        return Response({"category": data["c"], "done": True})


# --- provider webhooks --------------------------------------------------------------------------


@csrf_exempt
def postmark_webhook(request: HttpRequest) -> HttpResponse:
    """Postmark delivery, open, click, bounce and spam events (token in the URL)."""
    token = settings.POSTMARK_WEBHOOK_TOKEN
    if request.method != "POST" or not token or request.GET.get("token") != token:
        return HttpResponse(status=403)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    meta = body.get("Metadata") or {}
    status = services.POSTMARK_STATUS.get(str(body.get("RecordType")))
    if not status or not meta.get("org") or not meta.get("message-id"):
        return HttpResponse(status=200)
    with tenant_context(meta["org"]):
        message = Message.objects.filter(pk=meta["message-id"]).first()
        if message is not None:
            from django.db import transaction

            with transaction.atomic():
                services.record_delivery_event(message, status, body)
    return HttpResponse(status=200)


TWILIO_STATUS = {
    "delivered": Message.Status.DELIVERED,
    "sent": Message.Status.SENT,
    "failed": Message.Status.FAILED,
    "undelivered": Message.Status.FAILED,
}


def _twilio_valid(request: HttpRequest) -> bool:
    from ..channels import twilio_signature_valid

    url = f"{settings.PLATFORM_BASE_URL}{request.get_full_path()}"
    params = {k: str(v) for k, v in request.POST.items()}
    return twilio_signature_valid(url, params, request.headers.get("X-Twilio-Signature", ""))


@csrf_exempt
def twilio_status(request: HttpRequest) -> HttpResponse:
    if request.method != "POST" or not _twilio_valid(request):
        return HttpResponse(status=403)
    status = TWILIO_STATUS.get(request.POST.get("MessageStatus", ""))
    org, message_id = request.GET.get("org"), request.GET.get("message")
    if status and org and message_id:
        from django.db import transaction

        with tenant_context(org):
            message = Message.objects.filter(pk=message_id).first()
            if message is not None:
                with transaction.atomic():
                    services.record_delivery_event(
                        message, status, {"ErrorCode": request.POST.get("ErrorCode", "")}
                    )
    return HttpResponse(status=204)


STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
START_WORDS = {"START", "YES", "UNSTOP"}


@csrf_exempt
def twilio_inbound(request: HttpRequest) -> HttpResponse:
    """Replies to the shared number: STOP/START opt-outs (FR-13-5)."""
    if request.method != "POST" or not _twilio_valid(request):
        return HttpResponse(status=403)
    word = request.POST.get("Body", "").strip().upper()
    phone = request.POST.get("From", "")
    if phone and word in STOP_WORDS:
        services.sms_opt_out(phone, stop=True)
    elif phone and word in START_WORDS:
        services.sms_opt_out(phone, stop=False)
    return HttpResponse("<Response/>", content_type="text/xml")
