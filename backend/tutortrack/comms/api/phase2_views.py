"""Broadcasts, the inbox, channel set-up and marketing sync (E13 Phase 2 API), plus the
inbound email webhook. Views stay thin: services and selectors do the work."""

from __future__ import annotations

import hmac
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import tenant_context
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm

from .. import broadcasts, inbox, marketing, selectors, senders
from ..models import (
    Broadcast,
    BroadcastRecipient,
    CannedReply,
    PhoneNumber,
    Segment,
    SenderDomain,
    Thread,
    WhatsAppTemplate,
)
from . import phase2_serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def managed(view: str, manage: str) -> dict[str, str]:
    return {"GET": view, "POST": manage, "PATCH": manage, "PUT": manage, "DELETE": manage}


BROADCASTS = managed("comms.broadcast.view", "comms.broadcast.send")
INBOX = managed("comms.inbox.view", "comms.inbox.reply")
CHANNELS = managed("comms.channels.manage", "comms.channels.manage")

EXAMPLE_DEFINITION = {
    "client_statuses": ["active"],
    "student_statuses": ["active", "trial"],
    "contacts": "primary",
}


# --- segments -----------------------------------------------------------------------------------


class SegmentViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Saved broadcast audiences (FR-13-6): client contacts or tutors, narrowed by
    status, branch, tags, a saved list view, a class, a job or a pipeline stage."""

    model = Segment
    serializer_class = s.SegmentSerializer
    permission_classes = perms(BROADCASTS)
    http_method_names = ["get", "post", "put", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Segment]:
        return selectors.segments_for(self.request.user)

    @extend_schema(
        request=s.SegmentWriteSerializer,
        responses={201: s.SegmentSerializer},
        examples=[
            OpenApiExample(
                "Active families (main contact only)",
                value={
                    "name": "Active families",
                    "audience": "contacts",
                    "definition": EXAMPLE_DEFINITION,
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.SegmentWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = broadcasts.save_segment(user=request.user, **payload.validated_data)
        return Response(s.SegmentSerializer(row).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.SegmentWriteSerializer, responses=s.SegmentSerializer)
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.SegmentWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = broadcasts.save_segment(self.get_object(), **payload.validated_data)
        return Response(s.SegmentSerializer(row).data)

    def perform_destroy(self, instance: Segment) -> None:
        broadcasts.delete_segment(instance)

    @extend_schema(
        request=s.AudiencePreviewRequestSerializer,
        responses=s.AudiencePreviewSerializer,
        examples=[
            OpenApiExample(
                "Who a marketing email would reach",
                value={
                    "audience": "contacts",
                    "definition": EXAMPLE_DEFINITION,
                    "channel": "email",
                    "purpose": "marketing",
                },
                request_only=True,
            )
        ],
    )
    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request: Request) -> Response:
        """How many people a segment reaches now, why others would be skipped (no
        consent, unsubscribed, no address...) and a sample."""
        payload = s.AudiencePreviewRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(broadcasts.preview_recipients(**payload.validated_data))

    @extend_schema(responses=s.SegmentOptionsSerializer)
    @action(detail=False, methods=["get"], url_path="options", pagination_class=None)
    def builder_options(self, request: Request) -> Response:
        """Choices for the segment builder."""
        from tutortrack.courses.models import GroupClass
        from tutortrack.crm.models import SavedView, Tag
        from tutortrack.leads.models import PipelineStage
        from tutortrack.people.models import Client, Student, TutorProfile
        from tutortrack.tenancy.models import Branch

        def opts(rows: Any) -> list[dict[str, str]]:
            return [{"value": str(v), "name": str(n)} for v, n in rows]

        views = SavedView.objects.filter(
            entity_type__in=["people.client", "people.student", "people.tutor"]
        ).filter(shared=True) | SavedView.objects.filter(owner=request.user)
        return Response(
            {
                "branches": opts(Branch.objects.values_list("pk", "name")),
                "tags": opts(Tag.objects.values_list("pk", "name")),
                "saved_views": opts(
                    (v.pk, f"{v.name} ({v.entity_type.split('.')[-1]})") for v in views.distinct()
                ),
                "group_classes": opts(GroupClass.objects.values_list("pk", "name")[:500]),
                "pipeline_stages": opts(
                    (st.pk, f"{st.pipeline.name}: {st.name}")
                    for st in PipelineStage.objects.select_related("pipeline")
                ),
                "client_statuses": opts(Client.Status.choices),
                "student_statuses": opts(Student.Status.choices),
                "tutor_statuses": opts(TutorProfile.Status.choices),
            }
        )


# --- broadcasts ---------------------------------------------------------------------------------


class BroadcastFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Broadcast.Status.choices)
    channel = filters.ChoiceFilter(choices=s.BROADCAST_CHANNELS)

    class Meta:
        model = Broadcast
        fields: list[str] = []


class RecipientFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=BroadcastRecipient.Status.choices)

    class Meta:
        model = BroadcastRecipient
        fields: list[str] = []


class BroadcastViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Bulk email, text and WhatsApp messages to a segment (FR-13-6). Drafts are edited
    freely; ``schedule`` hands them to ``BroadcastWorkflow`` (now or later), which sends
    throttled batches; ``pause``, ``resume`` and ``cancel`` signal it. Statistics come
    from delivery tracking (opens and clicks for email)."""

    model = Broadcast
    serializer_class = s.BroadcastSerializer
    filterset_class = BroadcastFilter
    permission_classes = perms(BROADCASTS)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Broadcast]:
        return selectors.broadcasts(self.request.user)

    @extend_schema(
        request=s.BroadcastWriteSerializer,
        responses={201: s.BroadcastSerializer},
        examples=[
            OpenApiExample(
                "Half-term news to active families",
                value={
                    "name": "Half-term timetable",
                    "channel": "email",
                    "purpose": "operational",
                    "subject": "Half-term lessons",
                    "body": "Hello {{ recipient.first_name }},\n\nLessons pause next week.",
                    "audience": "contacts",
                    "definition": EXAMPLE_DEFINITION,
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.BroadcastWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = broadcasts.create_broadcast(user=request.user, **payload.validated_data)
        return Response(s.BroadcastSerializer(row).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.BroadcastWriteSerializer, responses=s.BroadcastSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.BroadcastWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        row = broadcasts.update_broadcast(self.get_object(), **payload.validated_data)
        return Response(s.BroadcastSerializer(row).data)

    def perform_destroy(self, instance: Broadcast) -> None:
        broadcasts.delete_broadcast(instance)

    @extend_schema(request=None, responses=s.ContentPreviewSerializer)
    @action(detail=True, methods=["post"], url_path="preview")
    def preview(self, request: Request, pk: str) -> Response:
        """The message as a sample recipient would see it."""
        return Response(broadcasts.preview(self.get_object()))

    @extend_schema(request=None, responses=s.AudiencePreviewSerializer)
    @action(detail=True, methods=["post"], url_path="audience")
    def audience(self, request: Request, pk: str) -> Response:
        """Who it would reach if sent now."""
        row = self.get_object()
        return Response(
            broadcasts.preview_recipients(
                audience=row.audience,
                definition=row.definition,
                channel=row.channel,
                purpose=row.purpose,
            )
        )

    @extend_schema(
        request=s.ScheduleSerializer,
        responses=s.BroadcastSerializer,
        examples=[
            OpenApiExample("Send now", value={"scheduled_for": None}, request_only=True),
            OpenApiExample(
                "Send on Monday morning",
                value={"scheduled_for": "2026-10-19T09:00:00+01:00"},
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"])
    def schedule(self, request: Request, pk: str) -> Response:
        payload = s.ScheduleSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = broadcasts.schedule(
            self.get_object(),
            scheduled_for=payload.validated_data["scheduled_for"],
            user=request.user,
        )
        return Response(s.BroadcastSerializer(row).data)

    @extend_schema(request=None, responses=s.BroadcastSerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, pk: str) -> Response:
        return Response(s.BroadcastSerializer(broadcasts.pause(self.get_object())).data)

    @extend_schema(request=None, responses=s.BroadcastSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str) -> Response:
        return Response(s.BroadcastSerializer(broadcasts.resume(self.get_object())).data)

    @extend_schema(request=None, responses=s.BroadcastSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        return Response(s.BroadcastSerializer(broadcasts.cancel(self.get_object())).data)

    @extend_schema(
        responses=s.BroadcastRecipientSerializer(many=True),
        parameters=[OpenApiParameter("status", str, enum=BroadcastRecipient.Status.values)],
    )
    @action(detail=True, methods=["get"])
    def recipients(self, request: Request, pk: str) -> Response:
        """Who it went to (or why not), page by page."""
        row = self.get_object()
        qs = RecipientFilter(
            request.query_params, queryset=row.recipients.select_related("message")
        ).qs
        page = self.paginate_queryset(qs)
        data = s.BroadcastRecipientSerializer(page, many=True).data
        return self.get_paginated_response(data)


# --- inbox --------------------------------------------------------------------------------------


class ThreadFilter(filters.FilterSet):
    box = filters.ChoiceFilter(choices=[(b, b) for b in selectors.BOXES], method="by_box")
    kind = filters.ChoiceFilter(choices=Thread.Kind.choices)
    client = filters.UUIDFilter()
    tutor = filters.UUIDFilter()
    q = filters.CharFilter(method="search")

    class Meta:
        model = Thread
        fields: list[str] = []

    def by_box(self, qs: QuerySet[Thread], name: str, value: str) -> QuerySet[Thread]:
        return selectors.filter_box(qs, value, self.request.user)

    def search(self, qs: QuerySet[Thread], name: str, value: str) -> QuerySet[Thread]:
        from django.db.models import Q

        return qs.filter(
            Q(subject__icontains=value)
            | Q(contact_name__icontains=value)
            | Q(contact_email__icontains=value)
            | Q(client__display_name__icontains=value)
            | Q(tutor__last_name__icontains=value)
            | Q(tutor__first_name__icontains=value)
        )


class ThreadViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """The shared team inbox (FR-13-7): conversations by email, text, WhatsApp and
    portal chat. ``?box=open|mine|unassigned|snoozed|closed|flagged``. Tutors
    (``comms.inbox.*:own``) see only the conversations they take part in."""

    model = Thread
    filterset_class = ThreadFilter
    permission_classes = perms(INBOX)

    def get_serializer_class(self) -> Any:
        return s.ThreadDetailSerializer if self.action == "retrieve" else s.ThreadSerializer

    def get_tenant_queryset(self) -> QuerySet[Thread]:
        qs = selectors.threads(self.request.user)
        if self.action == "retrieve":
            qs = qs.prefetch_related("participants")
        return qs

    def _manage(self) -> Thread:
        if not has_perm(self.request.user, "comms.inbox.assign"):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        thread: Thread = self.get_object()
        return thread

    @extend_schema(
        request=s.StartThreadSerializer,
        responses={201: s.ThreadDetailSerializer},
        examples=[
            OpenApiExample(
                "Message a family in the portal",
                value={
                    "kind": "client",
                    "client": "0192a8e0-0000-7000-8000-000000000001",
                    "subject": "Next term",
                    "body": "Hello! Would Sam like to keep Thursday lessons next term?",
                    "channel": "chat",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        from tutortrack.people.models import Client, TutorProfile

        payload = s.StartThreadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client = (
            Client.objects.filter(pk=data.get("client")).first() if data.get("client") else None
        )
        tutor = (
            TutorProfile.objects.filter(pk=data.get("tutor")).first() if data.get("tutor") else None
        )
        thread = inbox.start_conversation(
            request.user,
            kind=data["kind"],
            body=data["body"],
            subject=data["subject"],
            client=client,
            tutor=tutor,
            channel=data["channel"],
        )
        thread = selectors.threads(request.user).prefetch_related("participants").get(pk=thread.pk)
        return Response(
            s.ThreadDetailSerializer(thread, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(responses=s.ThreadMessageSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def messages(self, request: Request, pk: str) -> Response:
        """The conversation (with internal notes), oldest first; marks it read."""
        thread = self.get_object()
        rows = list(selectors.thread_messages(thread, include_internal=True))[-500:]
        inbox.mark_read(thread, request.user)
        return Response(s.ThreadMessageSerializer(rows, many=True).data)

    @extend_schema(
        request=s.ReplySerializer,
        responses={201: s.ThreadMessageSerializer},
        examples=[
            OpenApiExample(
                "Reply by text",
                value={"body": "Yes, 5pm works. See you then!", "channel": "sms"},
                request_only=True,
            )
        ],
    )
    @messages.mapping.post
    def reply(self, request: Request, pk: str) -> Response:
        """Reply by the conversation's channel (or another: email, text, WhatsApp within
        24 hours of their last WhatsApp message, or portal chat)."""
        payload = s.ReplySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        entry = inbox.reply(
            self.get_object(),
            request.user,
            body=data["body"],
            channel=data.get("channel"),
            attachments=data["attachments"],
            subject=data["subject"],
        )
        return Response(s.ThreadMessageSerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.ThreadNoteSerializer, responses={201: s.ThreadMessageSerializer})
    @action(detail=True, methods=["post"])
    def notes(self, request: Request, pk: str) -> Response:
        """An internal note: staff only, never sent."""
        payload = s.ThreadNoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        entry = inbox.add_note(self.get_object(), request.user, body=payload.validated_data["body"])
        return Response(s.ThreadMessageSerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.AssignSerializer, responses=s.ThreadSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request: Request, pk: str) -> Response:
        from tutortrack.identity.models import User

        thread = self._manage()
        payload = s.AssignSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        assignee = None
        if payload.validated_data["assignee"]:
            assignee = User.objects.filter(pk=payload.validated_data["assignee"]).first()
            if assignee is None:
                raise NotFound()
        thread = inbox.assign(thread, assignee, by=request.user)
        return Response(s.ThreadSerializer(thread, context={"request": request}).data)

    @extend_schema(request=s.SnoozeSerializer, responses=s.ThreadSerializer)
    @action(detail=True, methods=["post"])
    def snooze(self, request: Request, pk: str) -> Response:
        """Hide it until a time; it reopens by itself then (or when they write)."""
        payload = s.SnoozeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        thread = inbox.snooze(self._manage(), until=payload.validated_data["until"])
        return Response(s.ThreadSerializer(thread, context={"request": request}).data)

    @extend_schema(request=None, responses=s.ThreadSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str) -> Response:
        thread = inbox.close(self._manage())
        return Response(s.ThreadSerializer(thread, context={"request": request}).data)

    @extend_schema(request=None, responses=s.ThreadSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request: Request, pk: str) -> Response:
        thread = inbox.reopen(self._manage())
        return Response(s.ThreadSerializer(thread, context={"request": request}).data)

    @extend_schema(responses=s.BoxCountsSerializer)
    @action(detail=False, methods=["get"], pagination_class=None)
    def counts(self, request: Request) -> Response:
        qs = selectors.threads(request.user)
        return Response(
            {
                box: selectors.filter_box(qs, box, request.user).count()
                for box in ("open", "mine", "unassigned", "snoozed", "flagged")
            }
        )

    @extend_schema(responses=s.AssigneeSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def assignees(self, request: Request) -> Response:
        """Staff who can reply to conversations (for assignment)."""
        from ..catalogue import staff_with

        rows = [{"id": r.user_id, "name": r.name} for r in staff_with("comms.inbox.reply")]
        return Response(sorted(rows, key=lambda r: str(r["name"]).lower()))


class CannedReplyViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Saved replies for the inbox (insert and edit before sending)."""

    model = CannedReply
    serializer_class = s.CannedReplySerializer
    permission_classes = perms(
        {
            "GET": "comms.inbox.reply",
            "POST": "comms.inbox.assign",
            "PUT": "comms.inbox.assign",
            "PATCH": "comms.inbox.assign",
            "DELETE": "comms.inbox.assign",
        }
    )
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[CannedReply]:
        return selectors.canned_replies(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = inbox.save_canned_reply(
            user=self.request.user, **serializer.validated_data
        )

    def perform_update(self, serializer: Any) -> None:
        data = {**s.CannedReplySerializer(serializer.instance).data, **serializer.validated_data}
        serializer.instance = inbox.save_canned_reply(
            serializer.instance, title=data["title"], body=data["body"], shortcut=data["shortcut"]
        )

    def perform_destroy(self, instance: CannedReply) -> None:
        inbox.delete_canned_reply(instance)


# --- channels and senders -----------------------------------------------------------------------


class SenderDomainViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Custom sending domains (FR-13-1, plan feature ``custom_domain``): add a domain,
    publish the DNS records shown, then ``check``. Once verified, the default domain is
    used as the From address of every email."""

    model = SenderDomain
    serializer_class = s.SenderDomainSerializer
    permission_classes = perms(CHANNELS)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[SenderDomain]:
        return selectors.sender_domains(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Send from hello@brightminds.co.uk",
                value={"domain": "brightminds.co.uk", "local_part": "hello"},
                request_only=True,
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = senders.add_sender_domain(
            domain=payload.validated_data["domain"],
            local_part=payload.validated_data.get("local_part", "hello"),
        )
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.SenderDomainUpdateSerializer, responses=s.SenderDomainSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = s.SenderDomainUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = senders.update_sender_domain(self.get_object(), **payload.validated_data)
        return Response(self.get_serializer(row).data)

    def perform_destroy(self, instance: SenderDomain) -> None:
        senders.remove_sender_domain(instance)

    @extend_schema(request=None, responses=s.SenderDomainSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request: Request, pk: str) -> Response:
        """Ask the email provider to check the DNS records now."""
        return Response(self.get_serializer(senders.check_sender_domain(self.get_object())).data)


class PhoneNumberViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """The organisation's own texting/WhatsApp numbers: messages go from them and replies
    come back to the inbox. Point the number's incoming-message webhook at
    ``/webhooks/twilio/inbound``."""

    model = PhoneNumber
    serializer_class = s.PhoneNumberSerializer
    permission_classes = perms(CHANNELS)

    def get_tenant_queryset(self) -> QuerySet[PhoneNumber]:
        return selectors.phone_numbers(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "A texting number",
                value={"channel": "sms", "number": "+447700900123", "label": "Office"},
                request_only=True,
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = senders.add_phone_number(**payload.validated_data)
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: PhoneNumber) -> None:
        senders.remove_phone_number(instance)


class WhatsAppTemplateViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """WhatsApp message templates approved by Meta (through Twilio Content): map one to a
    notification (``type_key``) or use it in WhatsApp broadcasts. ``variables`` fill
    ``{{1}}``, ``{{2}}``... and may use the same variables as the notification."""

    model = WhatsAppTemplate
    serializer_class = s.WhatsAppTemplateSerializer
    permission_classes = perms(
        {
            "GET": "comms.broadcast.view",
            "POST": "comms.channels.manage",
            "PATCH": "comms.channels.manage",
            "DELETE": "comms.channels.manage",
        }
    )
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[WhatsAppTemplate]:
        return selectors.whatsapp_templates(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Lesson reminder",
                value={
                    "name": "lesson_reminder",
                    "language": "en_GB",
                    "category": "utility",
                    "content_sid": "HX-your-content-template-sid",
                    "body": "Hi {{1}}, a reminder: {{2}} is on {{3}}.",
                    "variables": [
                        "{{ recipient.first_name }}",
                        "{{ lesson.title }}",
                        '{{ lesson.start|datetime("short") }}',
                    ],
                    "type_key": "lesson_reminder",
                    "status": "approved",
                },
                request_only=True,
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = senders.save_whatsapp_template(None, **payload.validated_data)
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = senders.save_whatsapp_template(
            serializer.instance, **serializer.validated_data
        )

    def perform_destroy(self, instance: WhatsAppTemplate) -> None:
        from tutortrack.core import audit

        with transaction.atomic():
            audit.record(instance, "delete")
            instance.delete()


# --- marketing sync -----------------------------------------------------------------------------


def _marketing_row(provider: str) -> dict[str, Any]:
    from tutortrack.integrations.providers import get_spec

    connection = marketing.connection_for(provider)
    settings_ = connection.settings if connection else {}
    return {
        "provider": provider,
        "name": get_spec(provider).label,
        "connection": connection.pk if connection else None,
        "account_name": connection.account_name if connection else "",
        "status": connection.status if connection else "",
        "audience_id": str(settings_.get("audience_id", "")),
        "audience_name": str(settings_.get("audience_name", "")),
        "last_sync_at": connection.last_sync_at if connection else None,
        "error": connection.error if connection else "",
    }


def _connected(provider: str) -> Any:
    connection = marketing.connection_for(provider)
    if connection is None:
        raise NotFound()
    return connection


class MarketingSyncView(APIView):
    """Mailchimp and Brevo (FR-13-9): connect with an API key through
    ``/integrations/connections`` (level ``organisation``), choose the audience, and
    contacts with marketing consent stay in sync."""

    permission_classes = perms({"GET": "comms.channels.manage"})

    @extend_schema(responses=s.MarketingConnectionSerializer(many=True))
    def get(self, request: Request) -> Response:
        from ..marketing_providers import PROVIDERS

        return Response([_marketing_row(p) for p in PROVIDERS])


class MarketingAudienceView(APIView):
    permission_classes = perms({"GET": "comms.channels.manage", "PUT": "comms.channels.manage"})

    @extend_schema(responses=s.MarketingAudienceSerializer(many=True))
    def get(self, request: Request, provider: str) -> Response:
        """The account's audiences (Mailchimp) or lists (Brevo)."""
        rows = marketing.audiences(_connected(provider))
        return Response([{"id": a.id, "name": a.name, "members": a.members} for a in rows])

    @extend_schema(request=s.ChooseAudienceSerializer, responses=s.MarketingConnectionSerializer)
    def put(self, request: Request, provider: str) -> Response:
        payload = s.ChooseAudienceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        marketing.choose_audience(_connected(provider), payload.validated_data["audience_id"])
        return Response(_marketing_row(provider))


class MarketingSyncNowView(APIView):
    permission_classes = perms({"POST": "comms.channels.manage"})

    @extend_schema(request=None, responses=s.MarketingSyncResultSerializer)
    def post(self, request: Request, provider: str) -> Response:
        """Send everyone now: consented contacts in, the rest unsubscribed."""
        return Response(marketing.sync_all(_connected(provider)))


# --- inbound email webhook ----------------------------------------------------------------------


@csrf_exempt
def inbound_email(request: HttpRequest) -> HttpResponse:
    """``POST /webhooks/inbound/email?token=``: Postmark inbound JSON for
    ``reply+<subdomain>.<thread>.<signature>@`` and ``inbox+<subdomain>@`` addresses on
    ``COMMS["REPLY_DOMAIN"]`` (FR-13-7). The token is compared in constant time; thread
    addresses carry an HMAC so they can't be guessed."""
    from tutortrack.tenancy.models import Organisation

    expected = str(settings.COMMS["INBOUND_TOKEN"] or "")
    if request.method != "POST":
        return HttpResponse(status=405)
    if not expected or not hmac.compare_digest(request.GET.get("token", ""), expected):
        return HttpResponse(status=403)
    try:
        body = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    route = senders.parse_mailbox_hash(str(body.get("MailboxHash", "")))
    sender = body.get("FromFull") or {}
    email = str(sender.get("Email") or body.get("From", "")).strip()
    org = Organisation.objects.filter(slug=route.slug).first() if route else None
    if route is None or org is None or not org.is_operational or not email:
        return HttpResponse(status=200)  # nothing we can route: accept and drop
    text = str(body.get("StrippedTextReply") or body.get("TextBody") or "")
    with tenant_context(org):
        thread_id = ""
        if route.thread_hex:
            import uuid

            thread_id = str(uuid.UUID(route.thread_hex))
            if not Thread.objects.filter(pk=thread_id).exists():
                thread_id = ""
        inbox.receive_email(
            thread_id=thread_id,
            from_email=email,
            from_name=str(sender.get("Name", "")),
            subject=str(body.get("Subject", "")),
            body=text,
            message_id=str(body.get("MessageID", "")),
            attachments=list(body.get("Attachments") or []),
        )
    return HttpResponse(status=200)


__all__ = [
    "BroadcastViewSet",
    "CannedReplyViewSet",
    "MarketingAudienceView",
    "MarketingSyncNowView",
    "MarketingSyncView",
    "PhoneNumberViewSet",
    "SegmentViewSet",
    "SenderDomainViewSet",
    "ThreadViewSet",
    "WhatsAppTemplateViewSet",
    "inbound_email",
]
