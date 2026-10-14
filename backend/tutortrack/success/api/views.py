"""Success API (E30 Part 2): help articles and "What's new", guidance state (tours, NPS
prompt), the setup checklist, survey answers, support chat with TutorTrack and the
consent-gated product analytics intake."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.utils.translation import get_language
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission

from .. import analytics, help, selectors, services
from ..models import SupportConversation
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def _locale(request: Request) -> str:
    language = getattr(request, "LANGUAGE_CODE", "") or get_language() or ""
    parts = language.replace("_", "-").split("-")
    return f"{parts[0].lower()}-{parts[1].upper()}" if len(parts) > 1 else help.FALLBACK_LOCALE


def _impersonating(request: Request) -> bool:
    return getattr(request, "impersonator", None) is not None


def _guidance(request: Request) -> Response:
    data = selectors.guidance(
        request.user,
        getattr(request, "membership", None),
        impersonating=_impersonating(request),
    )
    return Response(s.GuidanceSerializer(data).data)


# --- help (FR-30-5) -----------------------------------------------------------------------------


class HelpArticlesView(APIView):
    """Search the help articles, or list those for the page the person is on."""

    permission_classes = AUTH

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search words"),
            OpenApiParameter("route", str, description="Current page, e.g. /billing"),
        ],
        responses=s.HelpArticleRowSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        locale = _locale(request)
        query = request.query_params.get("q", "")[:200]
        found = help.search(query, request.query_params.get("route", ""), locale)
        if not found and not query:
            found = help.search(route="/", locale=locale)
        return Response(s.HelpArticleRowSerializer(found[:20], many=True).data)


class HelpArticleView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.HelpArticleSerializer)
    def get(self, request: Request, slug: str) -> Response:
        found = help.article(slug, _locale(request))
        if found is None:
            raise NotFound()
        return Response(s.HelpArticleSerializer(found).data)


class ChangelogView(APIView):
    """What's new in TutorTrack, newest first."""

    permission_classes = AUTH

    @extend_schema(responses=s.HelpChangelogEntrySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.HelpChangelogEntrySerializer(help.changelog()[:20], many=True).data)


class ChangelogSeenView(APIView):
    permission_classes = AUTH

    @extend_schema(request=None, responses=s.GuidanceSerializer)
    def post(self, request: Request) -> Response:
        services.mark_changelog_seen(request.user)
        return _guidance(request)


# --- guidance (tours, prompts) ------------------------------------------------------------------


class GuidanceView(APIView):
    """What the help layer needs on every page: finished tours, unread "What's new" entries
    and support replies, whether to ask for NPS and whether usage analytics may run."""

    permission_classes = AUTH

    @extend_schema(responses=s.GuidanceSerializer)
    def get(self, request: Request) -> Response:
        return _guidance(request)


class TourView(APIView):
    permission_classes = AUTH

    @extend_schema(
        request=s.TourStatusSerializer,
        responses=s.GuidanceSerializer,
        examples=[OpenApiExample("Finished", value={"status": "completed"}, request_only=True)],
    )
    def post(self, request: Request, key: str) -> Response:
        payload = s.TourStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        choice = payload.validated_data["status"]
        if choice == "restart":
            services.restart_tour(request.user, key)
        else:
            services.finish_tour(request.user, key, dismissed=choice == "dismissed")
        return _guidance(request)


# --- setup checklist ----------------------------------------------------------------------------


class SetupChecklistView(APIView):
    """The dashboard checklist; staff may hide it (``success.checklist.manage``)."""

    permission_classes = [*AUTH, HasMethodPermission.for_({"PATCH": "success.checklist.manage"})]

    def get_permissions(self) -> Any:
        if self.request.method == "GET":
            return [p() for p in AUTH]
        return super().get_permissions()

    @extend_schema(responses=s.SetupChecklistSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.SetupChecklistSerializer(selectors.checklist(services.checklist())).data)

    @extend_schema(
        request=s.SetupChecklistUpdateSerializer,
        responses=s.SetupChecklistSerializer,
        examples=[OpenApiExample("Hide", value={"dismissed": True}, request_only=True)],
    )
    def patch(self, request: Request) -> Response:
        payload = s.SetupChecklistUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        state = services.dismiss_checklist(dismissed=payload.validated_data["dismissed"])
        return Response(s.SetupChecklistSerializer(selectors.checklist(state)).data)


# --- surveys ------------------------------------------------------------------------------------


class SurveyResponsesView(APIView):
    permission_classes = AUTH

    @extend_schema(
        request=s.SurveyAnswerSerializer,
        responses={201: s.SurveyResponseSerializer},
        examples=[
            OpenApiExample(
                "NPS answer",
                value={"kind": "nps", "score": 9, "comment": "The calendar saves me hours."},
                request_only=True,
            ),
            OpenApiExample("Not now", value={"kind": "nps", "score": None}, request_only=True),
        ],
    )
    def post(self, request: Request) -> Response:
        payload = s.SurveyAnswerSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        membership = getattr(request, "membership", None)
        values = dict(payload.validated_data)
        response = services.answer_survey(
            request.user,
            role=membership.role if membership else "",
            context=values.pop("topic", ""),
            **values,
        )
        return Response(s.SurveyResponseSerializer(response).data, status=status.HTTP_201_CREATED)


# --- support chat -------------------------------------------------------------------------------


class SupportConversationViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Chat with TutorTrack support. Opening a conversation marks its replies as read."""

    model = SupportConversation
    permission_classes = [*AUTH, HasPermission.for_("success.support.chat")]
    serializer_class = s.SupportConversationSerializer

    def get_tenant_queryset(self) -> QuerySet[SupportConversation]:
        return selectors.support_conversations(self.request.user)

    def get_serializer_class(self) -> Any:
        if self.action == "retrieve":
            return s.SupportConversationDetailSerializer
        return s.SupportConversationSerializer

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        conversation = self.get_object()
        if not _impersonating(request):
            services.mark_read(conversation, by_support=False)
        return Response(s.SupportConversationDetailSerializer(conversation).data)

    @extend_schema(
        request=s.SupportConversationCreateSerializer,
        responses={201: s.SupportConversationDetailSerializer},
        examples=[
            OpenApiExample(
                "Question",
                value={
                    "subject": "Invoice run",
                    "body": "How do I invoice every family at the end of the month?",
                    "page": "/billing",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = s.SupportConversationCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        conversation = services.open_conversation(request.user, **payload.validated_data)
        return Response(
            s.SupportConversationDetailSerializer(conversation).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=s.SupportMessageCreateSerializer,
        responses={201: s.SupportConversationDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def messages(self, request: Request, pk: str | None = None) -> Response:
        conversation = self.get_object()
        payload = s.SupportMessageCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.post_message(conversation, request.user, body=payload.validated_data["body"])
        conversation.refresh_from_db()
        return Response(
            s.SupportConversationDetailSerializer(conversation).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=s.SupportConversationDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        conversation = services.close_conversation(self.get_object())
        return Response(s.SupportConversationDetailSerializer(conversation).data)


# --- product analytics (FR-30-6) ----------------------------------------------------------------


class ProductEventsView(APIView):
    """Usage events from the admin app. Accepted only with the person's analytics consent
    (``tt_consent`` cookie), the organisation's permission and a staff role; otherwise the
    batch is dropped and ``accepted`` is 0. Properties that could identify anyone are
    removed (see ``success.analytics``)."""

    permission_classes = AUTH

    @extend_schema(
        request=s.ProductEventBatchSerializer,
        responses={202: s.AcceptedSerializer},
        examples=[
            OpenApiExample(
                "Page view",
                value={
                    "events": [
                        {
                            "name": "page.viewed",
                            "route": "/clients/$id",
                            "properties": {"tab": "billing"},
                        }
                    ]
                },
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        payload = s.ProductEventBatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        accepted = 0
        membership = getattr(request, "membership", None)
        allowed = selectors.analytics_allowed(membership, impersonating=_impersonating(request))
        if allowed and analytics.consented(request.COOKIES):
            captured = analytics.build(
                request.organisation.pk,  # type: ignore[attr-defined]
                request.user.pk,
                payload.validated_data["events"],
            )
            analytics.emit(captured)
            accepted = len(captured)
        return Response({"accepted": accepted}, status=status.HTTP_202_ACCEPTED)
