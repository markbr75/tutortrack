"""Gap batch G5a API: compliance export and bulk document requests (FR-18-8), probation
reviews, performance notes and offboarding (FR-18-9), and tutor subject tests (FR-18-3)."""

from __future__ import annotations

import csv
import io
from typing import Any

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core import audit
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.people.models import TutorProfile

from .. import compliance, performance, subject_tests
from ..models import OffboardingChecklist, PerformanceNote, ProbationReview
from . import serializers as s
from .views import AUTH, DASHBOARD_FILTERS, _my_tutor, _tutor, dashboard_filters, perms


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    return "'" + value if value[:1] in {"=", "+", "-", "@", "\t"} else value


# --- compliance (FR-18-8) -------------------------------------------------------------------


class DashboardExportView(APIView):
    """The compliance matrix as CSV, with the dashboard's filters (audited)."""

    permission_classes = perms({"GET": "compliance.view"})

    @extend_schema(
        parameters=DASHBOARD_FILTERS,
        responses={(200, "text/csv"): OpenApiResponse(response=OpenApiTypes.BINARY)},
    )
    def get(self, request: Request) -> HttpResponse:
        from tutortrack.core.context import require_organisation_id
        from tutortrack.tenancy.models import Organisation

        filters = dashboard_filters(request)
        board = compliance.dashboard(**filters)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in compliance.export_rows(board):
            writer.writerow([_csv_safe(str(cell)) for cell in row])
        organisation = Organisation.objects.get(pk=require_organisation_id())
        audit.record(
            organisation,
            "export",
            {"rows": [None, len(board["rows"])], "filters": [None, filters]},
            object_repr="compliance dashboard",
        )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="compliance.csv"'
        return response


class RequestMissingView(APIView):
    """Bulk "request missing documents": each tutor (all with gaps, or the chosen ones) is
    told which documents are missing, rejected or expired."""

    permission_classes = perms({"POST": "compliance.verify"})

    @extend_schema(
        request=s.RequestMissingSerializer,
        responses=s.RequestMissingResultSerializer,
        examples=[
            OpenApiExample("Everyone with gaps", value={}, request_only=True),
            OpenApiExample(
                "Two tutors, DBS only",
                value={
                    "tutors": [
                        "0192b0f4-8f3a-7c1e-9a1b-1c2d3e4f5a6b",
                        "0192b0f4-8f3a-7c1e-9a1b-1c2d3e4f5a6c",
                    ],
                    "requirements": ["dbs_enhanced"],
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request: Request) -> Response:
        payload = s.RequestMissingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        sent = compliance.request_missing(
            tutor_ids=d["tutors"], requirements=d["requirements"], user=request.user
        )
        return Response({"count": len(sent), "requests": sent})


# --- probation reviews and performance notes (FR-18-9) --------------------------------------


class ProbationReviewViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Probation reviews; ``ProbationReviewWorkflow`` reminds staff before each is due."""

    model = ProbationReview
    serializer_class = s.ProbationReviewSerializer
    permission_classes = perms(
        {"GET": "recruitment.performance.view", "POST": "recruitment.performance.manage"}
    )

    def get_tenant_queryset(self) -> Any:
        qs = ProbationReview.objects.select_related("tutor", "reviewer")
        q = self.request.query_params
        for key in ("tutor", "status"):
            if q.get(key):
                qs = qs.filter(**{key: q[key]})
        return qs

    @extend_schema(parameters=[OpenApiParameter("tutor", str), OpenApiParameter("status", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.ScheduleProbationSerializer,
        responses={201: s.ProbationReviewSerializer},
        examples=[
            OpenApiExample(
                "Schedule",
                value={"tutor": "0192b0f4-8f3a-7c1e-9a1b-1c2d3e4f5a6b", "due_on": "2027-01-15"},
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = s.ScheduleProbationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = _tutor(payload.validated_data["tutor"])
        review = performance.schedule_probation(
            tutor, due_on=payload.validated_data["due_on"], user=request.user
        )
        return Response(s.ProbationReviewSerializer(review).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=s.CompleteProbationSerializer,
        responses=s.ProbationReviewSerializer,
        examples=[
            OpenApiExample(
                "Extend",
                value={"outcome": "extended", "notes": "Punctuality", "extend_to": "2027-03-01"},
                request_only=True,
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: Any = None) -> Response:
        payload = s.CompleteProbationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        review = performance.complete_probation(
            self.get_object(),
            outcome=d["outcome"],
            notes=d["notes"],
            user=request.user,
            extend_to=d["extend_to"],
        )
        return Response(s.ProbationReviewSerializer(review).data)


class PerformanceNoteViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Staff notes on a tutor's performance: praise, concerns and notes."""

    model = PerformanceNote
    serializer_class = s.PerformanceNoteSerializer
    permission_classes = perms(
        {
            "GET": "recruitment.performance.view",
            "POST": "recruitment.performance.manage",
            "DELETE": "recruitment.performance.manage",
        }
    )

    def get_tenant_queryset(self) -> Any:
        qs = PerformanceNote.objects.select_related("author")
        q = self.request.query_params
        for key in ("tutor", "kind"):
            if q.get(key):
                qs = qs.filter(**{key: q[key]})
        return qs

    @extend_schema(parameters=[OpenApiParameter("tutor", str), OpenApiParameter("kind", str)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.AddPerformanceNoteSerializer,
        responses={201: s.PerformanceNoteSerializer},
        examples=[
            OpenApiExample(
                "Praise",
                value={
                    "tutor": "0192b0f4-8f3a-7c1e-9a1b-1c2d3e4f5a6b",
                    "kind": "praise",
                    "body": "Lovely feedback from the Patels.",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = s.AddPerformanceNoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        note = performance.add_note(
            _tutor(d["tutor"]), kind=d["kind"], body=d["body"], user=request.user
        )
        return Response(s.PerformanceNoteSerializer(note).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: PerformanceNote) -> None:
        performance.delete_note(instance)


# --- offboarding (FR-18-9) ------------------------------------------------------------------


def _offboarding(tutor: TutorProfile) -> Response:
    checklist = (
        OffboardingChecklist.objects.filter(tutor=tutor).select_related("tutor__membership").first()
    )
    tutor.refresh_from_db(fields=["status"])
    if checklist is None:
        data: dict[str, Any] = {
            "id": None,
            "reason": "",
            "leaving_on": None,
            "started_at": None,
            "completed_at": None,
            "items": [],
            "tutor_status": tutor.status,
        }
    else:
        data = {
            "id": checklist.pk,
            "reason": checklist.reason,
            "leaving_on": checklist.leaving_on,
            "started_at": checklist.created_at,
            "completed_at": checklist.completed_at,
            "items": performance.offboarding_state(checklist),
            "tutor_status": tutor.status,
        }
    return Response(s.OffboardingSerializer(data).data)


def _open_checklist(tutor: TutorProfile) -> OffboardingChecklist:
    checklist = performance.open_offboarding(tutor)
    if checklist is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("This tutor isn't being offboarded.")
    return checklist


class TutorOffboardingView(APIView):
    """``/tutors/{id}/offboarding``: the latest checklist; POST starts offboarding (the
    tutor becomes inactive)."""

    permission_classes = perms(
        {"GET": "recruitment.offboarding.manage", "POST": "recruitment.offboarding.manage"}
    )

    @extend_schema(responses=s.OffboardingSerializer)
    def get(self, request: Request, pk: str) -> Response:
        return _offboarding(_tutor(pk))

    @extend_schema(
        request=s.StartOffboardingSerializer,
        responses=s.OffboardingSerializer,
        examples=[
            OpenApiExample(
                "Start",
                value={"reason": "Moving abroad", "leaving_on": "2026-12-20"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request, pk: str) -> Response:
        payload = s.StartOffboardingSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor = _tutor(pk)
        performance.start_offboarding(tutor, user=request.user, **payload.validated_data)
        return _offboarding(tutor)


class TutorOffboardingItemView(APIView):
    permission_classes = perms({"POST": "recruitment.offboarding.manage"})

    @extend_schema(request=None, responses=s.OffboardingSerializer)
    def post(self, request: Request, pk: str, key: str) -> Response:
        tutor = _tutor(pk)
        performance.tick_offboarding(_open_checklist(tutor), key, user=request.user)
        return _offboarding(tutor)


class TutorRevokeAccessView(APIView):
    permission_classes = perms({"POST": "recruitment.offboarding.manage"})

    @extend_schema(request=None, responses=s.OffboardingSerializer)
    def post(self, request: Request, pk: str) -> Response:
        tutor = _tutor(pk)
        performance.revoke_access(_open_checklist(tutor), user=request.user)
        return _offboarding(tutor)


class TutorCompleteOffboardingView(APIView):
    permission_classes = perms({"POST": "recruitment.offboarding.manage"})

    @extend_schema(request=None, responses=s.OffboardingSerializer)
    def post(self, request: Request, pk: str) -> Response:
        tutor = _tutor(pk)
        performance.complete_offboarding(_open_checklist(tutor), user=request.user)
        return _offboarding(tutor)


# --- subject tests (FR-18-3) ----------------------------------------------------------------


class MySubjectTestsView(APIView):
    """The tutor's subject tests (tutor portal)."""

    permission_classes = AUTH

    @extend_schema(responses=s.SubjectTestSerializer(many=True))
    def get(self, request: Request) -> Response:
        tests = subject_tests.tests_for(_my_tutor(request))
        return Response(s.SubjectTestSerializer(tests, many=True).data)


class MySubjectTestView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.SubjectTestDetailSerializer)
    def get(self, request: Request, quiz_id: str) -> Response:
        entry = subject_tests.entry_for(_my_tutor(request), quiz_id)
        return Response(s.SubjectTestDetailSerializer(entry).data)

    @extend_schema(
        request=s.TakeSubjectTestSerializer,
        responses=s.SubjectTestResultSerializer,
        examples=[
            OpenApiExample(
                "Answers",
                value={"answers": {"0192b0f4-8f3a-7c1e-9a1b-1c2d3e4f5a6b": ["b"]}},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request, quiz_id: str) -> Response:
        payload = s.TakeSubjectTestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = subject_tests.take(
            _my_tutor(request),
            quiz_id,
            answers=payload.validated_data["answers"],
            user=request.user,
        )
        return Response(s.SubjectTestResultSerializer(result).data)


class TutorSubjectTestsView(APIView):
    """Staff: the tutor's subject-test results (tutor record)."""

    permission_classes = perms({"GET": "people.tutor.approve_subjects"})

    @extend_schema(responses=s.SubjectTestAttemptSerializer(many=True))
    def get(self, request: Request, pk: str) -> Response:
        attempts = subject_tests.results_for(_tutor(pk))
        return Response(s.SubjectTestAttemptSerializer(attempts, many=True).data)
