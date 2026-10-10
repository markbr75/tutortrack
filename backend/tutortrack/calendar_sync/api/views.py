"""Calendar sync and online meeting API (E22-T02..T09)."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, scope_queryset
from tutortrack.core.time import now
from tutortrack.core.workflows import ops
from tutortrack.integrations import providers
from tutortrack.integrations import selectors as integration_selectors
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import ProviderError
from tutortrack.scheduling.external import join_link
from tutortrack.scheduling.models import Lesson

from .. import selectors, services
from ..models import ExternalBusyBlock, MeetingPreference, OnlineMeeting
from ..processes import (
    MeetingInput,
    OnlineMeetingProvisioningWorkflow,
    calendar_workflow_id,
    meeting_workflow_id,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def _calendar_connection(request: Request, pk: Any) -> IntegrationConnection:
    connection = get_object_or_404(integration_selectors.visible_connections(request.user), pk=pk)
    if not services.is_calendar(connection):
        raise BusinessRuleViolation("This connection isn't a personal calendar.")
    return connection


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


class CalendarSyncSettingsView(APIView):
    """A personal calendar connection's sync settings and the calendars to choose from."""

    permission_classes = AUTH

    def _page(self, connection: IntegrationConnection) -> dict[str, Any]:
        sync = services.settings_for(connection)
        calendars: list[Any] = []
        error = ""
        try:
            creds = integrations.credentials(connection)
            calendars = providers.calendar_client(connection.provider).list_calendars(creds)
        except ProviderError as exc:
            error = str(exc)
        return {
            "settings": sync,
            "calendars": [c.__dict__ for c in calendars],
            "calendars_error": error,
            "two_way_allowed": bool(_setting("integrations.calendar_two_way")),
        }

    @extend_schema(responses=s.CalendarSyncPageSerializer)
    def get(self, request: Request, pk: str) -> Response:
        connection = _calendar_connection(request, pk)
        return Response(s.CalendarSyncPageSerializer(self._page(connection)).data)

    @extend_schema(
        request=s.CalendarSyncSettingsUpdateSerializer, responses=s.CalendarSyncPageSerializer
    )
    def patch(self, request: Request, pk: str) -> Response:
        """Choose busy calendars (free/busy only), the write calendar ("" = a "TutorTrack"
        calendar we create), two-way edits and the event title format."""
        connection = _calendar_connection(request, pk)
        if not integration_selectors.can_manage(request.user, connection):
            raise PermissionDenied("You can't change this connection.")
        payload = s.CalendarSyncSettingsUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.update_sync_settings(services.settings_for(connection), **payload.validated_data)
        return Response(s.CalendarSyncPageSerializer(self._page(connection)).data)


class CalendarSyncNowView(APIView):
    permission_classes = AUTH

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, pk: str) -> Response:
        """Sync this calendar now (instead of waiting for the next poll)."""
        connection = _calendar_connection(request, pk)
        ops.signal(calendar_workflow_id(connection.organisation_id, connection.pk), "changed")
        return Response(status=status.HTTP_202_ACCEPTED)


class BusyBlockViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Busy time from connected calendars (times only). ``?user=``, ``?start=``, ``?end=``."""

    model = ExternalBusyBlock
    serializer_class = s.ExternalBusyBlockSerializer
    permission_classes = AUTH

    def get_tenant_queryset(self) -> Any:
        qs = selectors.busy_blocks(self.request.user)
        params = self.request.query_params
        if params.get("user"):
            qs = qs.filter(user_id=params["user"])
        if params.get("start"):
            qs = qs.filter(end__gt=params["start"])
        if params.get("end"):
            qs = qs.filter(start__lt=params["end"])
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("user", str, required=False),
            OpenApiParameter("start", str, required=False),
            OpenApiParameter("end", str, required=False),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class OnlineMeetingViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Online meetings of lessons you can see (``?lesson=``, ``?status=failed``)."""

    model = OnlineMeeting
    serializer_class = s.OnlineMeetingSerializer
    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "scheduling.lesson.view"})]

    def get_tenant_queryset(self) -> Any:
        qs = selectors.meetings(self.request.user)
        params = self.request.query_params
        if params.get("lesson"):
            qs = qs.filter(lesson_id=params["lesson"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("lesson", str, required=False),
            OpenApiParameter("status", str, required=False),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class ProvisionMeetingView(APIView):
    permission_classes = [*AUTH, HasMethodPermission.for_({"POST": "scheduling.lesson.edit"})]

    @extend_schema(request=s.ProvisionSerializer, responses={202: s.ProvisionResultSerializer})
    def post(self, request: Request) -> Response:
        """Create (or re-create) the lesson's online meeting now, e.g. after a failure."""
        payload = s.ProvisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lessons = scope_queryset(request.user, Lesson.objects.all(), "scheduling.lesson.edit")
        lesson = get_object_or_404(lessons, pk=payload.validated_data["lesson"])
        org = str(lesson.organisation_id)
        ops.start(
            OnlineMeetingProvisioningWorkflow,
            MeetingInput(organisation_id=org, lesson_ids=[str(lesson.pk)]),
            id=meeting_workflow_id(org, lesson.pk, f"manual-{now():%Y%m%d%H%M%S%f}"),
            subject=("lesson", str(lesson.pk)),
        )
        return Response({"started": True}, status=status.HTTP_202_ACCEPTED)


class MeetingPreferenceView(APIView):
    """Your default video provider for your online lessons."""

    permission_classes = AUTH

    def _get(self, request: Request) -> MeetingPreference:
        found, _created = MeetingPreference.objects.get_or_create(user=request.user)
        return found

    @extend_schema(responses=s.MeetingPreferenceSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.MeetingPreferenceSerializer(self._get(request)).data)

    @extend_schema(request=s.MeetingPreferenceSerializer, responses=s.MeetingPreferenceSerializer)
    def put(self, request: Request) -> Response:
        from tutortrack.core import audit

        preference = self._get(request)
        payload = s.MeetingPreferenceSerializer(preference, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        with audit.track(preference):
            payload.save()
        return Response(s.MeetingPreferenceSerializer(preference).data)


class LessonJoinView(APIView):
    """The requester's join link for an online lesson: the host link for its tutors, the
    participant link otherwise. ``open`` is true from N minutes before the start (org
    setting ``integrations.join_window_minutes``) until the end."""

    permission_classes = [*AUTH, HasMethodPermission.for_({"GET": "scheduling.lesson.view"})]

    @extend_schema(responses={200: s.JoinLinkSerializer, 204: None})
    def get(self, request: Request, pk: str) -> Response:
        lessons = scope_queryset(request.user, Lesson.objects.all(), "scheduling.lesson.view")
        lesson = get_object_or_404(lessons, pk=pk)
        is_tutor = lesson.tutors.filter(tutor__membership__user=request.user).exists()
        link = join_link(lesson, "host" if is_tutor else "participant")
        if link is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(s.JoinLinkSerializer(join_payload(link, lesson)).data)


def join_payload(link: Any, lesson: Any) -> dict[str, Any]:
    current = now()
    opens = link.opens_at or lesson.start
    return {
        "url": link.url,
        "opens_at": link.opens_at,
        "provider": link.provider,
        "role": link.role,
        "open": opens <= current <= lesson.end,
    }
