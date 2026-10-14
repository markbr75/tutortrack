"""AI assistant API (E31) under ``/api/v1/ai/``.

Every feature endpoint needs ``ai.use`` (the copilot ``ai.copilot``) *and* the permission
of the data it reads, checked in the feature module. Responses are drafts, proposals or
answers; nothing changes until a person applies a draft through the owning app's
endpoints or confirms a proposal (``/ai/proposals/{id}/confirm``).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils.translation import gettext as _
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission

from .. import metering, selectors, services
from ..features import assistant, content, enquiry, inbox, lesson_report, matching, progress
from ..models import AIAssist, AIProposal, AIRequestLog, ThreadInsight
from . import serializers as s

AUTH: list[Any] = [IsAuthenticated, HasOrganisation]
USE: list[Any] = [*AUTH, HasPermission.for_("ai.use")]

REQUEST_ID = "0192f5a0-7c1e-7b3a-9d2e-5f4c3b2a1d0e"


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _valid(serializer_class: type, request: Request) -> dict[str, Any]:
    payload = serializer_class(data=request.data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


# --- status, settings, usage, logs --------------------------------------------------------------


class AIStatusView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.AIStatusSerializer, operation_id="ai_status")
    def get(self, request: Request) -> Response:
        """Whether the plan includes AI, which features the organisation turned on and
        (for ``ai.usage.view``) its AI credits."""
        return Response(s.AIStatusSerializer(selectors.status(request.user)).data)


class AIFeatureListView(APIView):
    permission_classes = USE

    @extend_schema(responses=s.AIFeatureSettingSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.AIFeatureSettingSerializer(selectors.feature_settings(), many=True).data)


class AIFeatureDetailView(APIView):
    permission_classes = perms({"PATCH": "ai.settings.manage"})

    @extend_schema(
        request=s.AIFeatureUpdateSerializer,
        responses=s.AIFeatureSettingSerializer(many=True),
        examples=[OpenApiExample("Turn on", value={"enabled": True, "tone": "formal"})],
    )
    def patch(self, request: Request, feature: str) -> Response:
        """Opt the organisation into a feature (or out), with tone and spelling."""
        services.update_feature(feature, **_valid(s.AIFeatureUpdateSerializer, request))
        return Response(s.AIFeatureSettingSerializer(selectors.feature_settings(), many=True).data)


class AIUsageView(APIView):
    permission_classes = perms({"GET": "ai.usage.view"})

    @extend_schema(
        parameters=[OpenApiParameter("month", str, description="YYYY-MM (default: this month).")],
        responses=s.AIUsageSerializer,
    )
    def get(self, request: Request) -> Response:
        month = request.query_params.get("month") or ""
        try:
            period = date.fromisoformat(f"{month}-01") if month else metering.month_start()
        except ValueError as exc:
            raise BusinessRuleViolation(_("Use a month like 2026-10.")) from exc
        body = {**selectors.usage(period), "credits": metering.credit_summary()}
        return Response(s.AIUsageSerializer(body).data)


class RequestLogFilter(filters.FilterSet):
    feature = filters.CharFilter()
    status = filters.CharFilter()

    class Meta:
        model = AIRequestLog
        fields: list[str] = []


class AIRequestLogViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """The request log: prompts are never stored, only a hash of the redacted input."""

    model = AIRequestLog
    serializer_class = s.AIRequestLogSerializer
    permission_classes = perms({"GET": "ai.usage.view"})
    filterset_class = RequestLogFilter
    ordering = ["-created_at"]

    def get_tenant_queryset(self) -> Any:
        return selectors.request_logs(self.request.user)


# --- feedback, assists, proposals, insights -----------------------------------------------------


class AIFeedbackView(APIView):
    permission_classes = USE

    @extend_schema(
        request=s.AIFeedbackInSerializer,
        responses=s.AIFeedbackOutSerializer,
        examples=[
            OpenApiExample(
                "Thumbs up after editing",
                value={
                    "request": REQUEST_ID,
                    "rating": "up",
                    "draft_text": "Sam worked well.",
                    "final_text": "Sam worked really well.",
                },
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """Rate a response; with the draft and the final text, only edit statistics are
        kept (the texts are not stored)."""
        data = _valid(s.AIFeedbackInSerializer, request)
        feedback = services.record_feedback(
            request.user,
            data["request"],
            rating=data.get("rating", ""),
            comment=data.get("comment", ""),
            draft_text=data.get("draft_text"),
            final_text=data.get("final_text"),
        )
        body = {
            "id": feedback.pk,
            "rating": feedback.rating,
            "similarity_percent": feedback.similarity_percent,
        }
        return Response(s.AIFeedbackOutSerializer(body).data)


class AIAssistViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The AI-assisted flag: drafts people applied to records."""

    model = AIAssist
    serializer_class = s.AIAssistSerializer
    permission_classes = USE

    def get_tenant_queryset(self) -> Any:
        ids = [i for i in self.request.query_params.get("subject_id", "").split(",") if i]
        return selectors.assists(self.request.query_params.get("subject_type", ""), ids)

    @extend_schema(
        parameters=[
            OpenApiParameter("subject_type", str, description="e.g. lesson_report"),
            OpenApiParameter("subject_id", str, description="One or more ids, comma separated."),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.AIAssistInSerializer,
        responses={201: s.AIAssistSerializer},
        examples=[
            OpenApiExample(
                "Applied to a lesson report",
                value={
                    "request": REQUEST_ID,
                    "subject_type": "lesson_report",
                    "subject_id": "0192f5a0-0000-7000-8000-000000000001",
                },
            )
        ],
    )
    def create(self, request: Request) -> Response:
        """Record that a person used a draft on a record (marks it AI-assisted)."""
        data = _valid(s.AIAssistInSerializer, request)
        assist = services.mark_applied(
            request.user,
            data["request"],
            subject_type=data["subject_type"],
            subject_id=data["subject_id"],
        )
        return Response(s.AIAssistSerializer(assist).data, status=status.HTTP_201_CREATED)


class AIProposalViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Actions the AI proposed to the requesting person (never anyone else's)."""

    model = AIProposal
    serializer_class = s.AIProposalSerializer
    permission_classes = USE

    def get_tenant_queryset(self) -> Any:
        qs = selectors.proposals(self.request.user)
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs

    @extend_schema(request=None, responses=s.AIProposalSerializer)
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: Any = None) -> Response:
        """Carry out the proposal with your permissions (409 if already decided)."""
        return Response(s.AIProposalSerializer(services.confirm(request.user, pk)).data)

    @extend_schema(request=None, responses=s.AIProposalSerializer)
    @action(detail=True, methods=["post"])
    def discard(self, request: Request, pk: Any = None) -> Response:
        return Response(s.AIProposalSerializer(services.discard(request.user, pk)).data)


class AIThreadInsightViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    model = ThreadInsight
    serializer_class = s.AIThreadInsightSerializer
    permission_classes = perms({"GET": "comms.inbox.view"})

    def get_tenant_queryset(self) -> Any:
        ids = [i for i in self.request.query_params.get("thread", "").split(",") if i]
        return selectors.thread_insights(self.request.user, ids or None).order_by("-classified_at")

    @extend_schema(
        parameters=[OpenApiParameter("thread", str, description="Thread ids, comma separated.")]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


# --- features -----------------------------------------------------------------------------------


class AILessonReportDraftView(APIView):
    permission_classes = USE
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        request={
            "multipart/form-data": s.AILessonReportDraftInSerializer,
            "application/json": s.AILessonReportDraftInSerializer,
        },
        responses=s.AILessonReportDraftSerializer,
        examples=[
            OpenApiExample(
                "Rough notes",
                value={"notes": "fractions - adding with different denominators, good effort"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request, report_id: Any) -> Response:
        """FR-31-1: draft a lesson report's answers from notes and/or a voice note. The
        draft is returned, not saved; submit it through the lesson report endpoints."""
        data = _valid(s.AILessonReportDraftInSerializer, request)
        body = lesson_report.draft(
            request.user, report_id, notes=data.get("notes", ""), audio=data.get("audio")
        )
        return Response(s.AILessonReportDraftSerializer(body).data)


class AIProgressDraftView(APIView):
    permission_classes = USE

    @extend_schema(request=None, responses=s.AIProgressDraftSerializer)
    def post(self, request: Request, report_id: Any) -> Response:
        """FR-31-2: draft the summary comments of a progress report from its snapshot."""
        return Response(s.AIProgressDraftSerializer(progress.draft(request.user, report_id)).data)


class AIRewriteView(APIView):
    permission_classes = USE

    @extend_schema(
        request=s.AIRewriteInSerializer,
        responses=s.AIRewriteSerializer,
        examples=[
            OpenApiExample(
                "Explain to a parent in French",
                value={"text": "Secure at KS3 AO2 problem solving.", "language": "fr"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """FR-31-2 "Explain to parent": plain words, optionally translated (the
        contact's preferred language when ``contact`` is given)."""
        data = _valid(s.AIRewriteInSerializer, request)
        body = progress.rewrite(
            request.user,
            text=data["text"],
            language=data.get("language", ""),
            contact_id=data.get("contact"),
            student_id=data.get("student"),
        )
        return Response(s.AIRewriteSerializer(body).data)


class AIEnquiryExtractView(APIView):
    permission_classes = USE

    @extend_schema(
        request=s.AIExtractInSerializer,
        responses=s.AIExtractSerializer,
        examples=[
            OpenApiExample(
                "An email",
                value={"text": "Hi, my son needs GCSE maths help, Tuesdays after 4pm, LS6."},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """FR-31-4: structured fields from a free-text enquiry, to prefill the form."""
        data = _valid(s.AIExtractInSerializer, request)
        return Response(s.AIExtractSerializer(enquiry.extract(request.user, data["text"])).data)


class AIEnquiryTriageView(APIView):
    permission_classes = USE

    @extend_schema(request=None, responses=s.AITriageSerializer)
    def post(self, request: Request, enquiry_id: Any) -> Response:
        """FR-31-4: next steps, a priority and a draft reply; field changes come back as
        a proposal to confirm."""
        body = enquiry.triage(request.user, enquiry_id)
        return Response(s.AITriageSerializer(body).data)


class AIThreadReplyView(APIView):
    permission_classes = USE

    @extend_schema(request=None, responses=s.AIReplySerializer)
    def post(self, request: Request, thread_id: Any) -> Response:
        """FR-31-3: a suggested reply (not sent) using the conversation and account."""
        return Response(s.AIReplySerializer(inbox.suggest_reply(request.user, thread_id)).data)


class AIThreadSummaryView(APIView):
    permission_classes = USE

    @extend_schema(request=None, responses=s.AISummarySerializer)
    def post(self, request: Request, thread_id: Any) -> Response:
        return Response(s.AISummarySerializer(inbox.summarise(request.user, thread_id)).data)


class AIThreadClassifyView(APIView):
    permission_classes = USE

    @extend_schema(request=None, responses=s.AIClassifySerializer)
    def post(self, request: Request, thread_id: Any) -> Response:
        """FR-31-3: the conversation's intent; routing (if configured) is a proposal."""
        body = inbox.classify_for(request.user, thread_id)
        return Response(s.AIClassifySerializer(body).data)


class AICommandView(APIView):
    permission_classes = USE

    @extend_schema(
        request=s.AICommandInSerializer,
        responses=s.AICommandSerializer,
        examples=[
            OpenApiExample(
                "Reschedule",
                value={"text": "Move Sam's Thursday maths to 5pm from next week"},
                request_only=True,
            ),
            OpenApiExample(
                "Search",
                value={"text": "Find a GCSE chemistry tutor free Tuesday evenings near LS6"},
                request_only=True,
            ),
        ],
    )
    def post(self, request: Request) -> Response:
        """FR-31-5: proposed actions (confirm each with ``/ai/proposals/{id}/confirm``)
        and tutor-search filters."""
        data = _valid(s.AICommandInSerializer, request)
        return Response(s.AICommandSerializer(assistant.command(request.user, data["text"])).data)


class AICopilotView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("ai.copilot")]

    @extend_schema(
        request=s.AICopilotInSerializer,
        responses=s.AICopilotSerializer,
        examples=[
            OpenApiExample(
                "Debtors",
                value={"question": "What's our outstanding balance over 30 days?"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """FR-31-7: an answer from the standard reports you may run, citing each report
        and its filters with a link to open it."""
        data = _valid(s.AICopilotInSerializer, request)
        body = assistant.ask(request.user, data["question"], data.get("history") or [])
        return Response(s.AICopilotSerializer(body).data)


class AIContentView(APIView):
    permission_classes = USE

    @extend_schema(
        request=s.AIContentInSerializer,
        responses=s.AIContentSerializer,
        examples=[
            OpenApiExample(
                "Half-term broadcast",
                value={"kind": "broadcast", "brief": "Half-term revision sessions, 20% off"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """FR-31-8: draft a broadcast, tutor bio, website page or job advert."""
        data = _valid(s.AIContentInSerializer, request)
        body = content.write(
            request.user,
            kind=data["kind"],
            brief=data.get("brief", ""),
            channel=data.get("channel", "email"),
            title=data.get("title", ""),
            tutor_id=data.get("tutor"),
            subjects=data.get("subjects") or [],
            location=data.get("location", ""),
        )
        return Response(s.AIContentSerializer(body).data)


class AIMatchExplainView(APIView):
    permission_classes = USE

    @extend_schema(request=s.AIMatchExplainInSerializer, responses=s.AIMatchExplainSerializer)
    def post(self, request: Request) -> Response:
        """FR-31-6: why a tutor ranks where they do, and an intro message."""
        data = _valid(s.AIMatchExplainInSerializer, request)
        body = matching.explain(
            request.user,
            tutor_id=data["tutor"],
            job_id=data.get("job"),
            criteria=data.get("criteria") or None,
        )
        return Response(s.AIMatchExplainSerializer(body).data)
