"""Recruitment and compliance API (E18 §4)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.captcha import verify_turnstile
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.middleware import client_ip
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.people.models import TutorProfile

from .. import compliance, services
from ..models import (
    ApplicationStage,
    ChecklistInstance,
    ChecklistTemplate,
    ComplianceRecord,
    JobOpening,
    RequirementType,
    TutorApplication,
    TutorComplianceState,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def _all(codename: str) -> dict[str, str]:
    return dict.fromkeys(("POST", "PUT", "PATCH", "DELETE"), codename)


# --- openings, stages, templates ------------------------------------------------------------


class JobOpeningViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = JobOpening
    serializer_class = s.JobOpeningSerializer
    pagination_class = None
    permission_classes = perms(
        {"GET": "recruitment.application.view", **_all("recruitment.pipeline.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        return JobOpening.objects.all()

    def perform_create(self, serializer: Any) -> None:
        form = serializer.validated_data["form"]
        if form.type != "application":
            raise ValidationError({"form": ["Choose a tutor application form."]})
        serializer.save()


class ApplicationStageViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    model = ApplicationStage
    serializer_class = s.ApplicationStageSerializer
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]
    permission_classes = perms(
        {"GET": "recruitment.application.view", "PATCH": "recruitment.pipeline.manage"}
    )

    def get_tenant_queryset(self) -> Any:
        services.stages()
        return ApplicationStage.objects.all()


class ChecklistTemplateViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = ChecklistTemplate
    serializer_class = s.ChecklistTemplateSerializer
    pagination_class = None
    permission_classes = perms(
        {"GET": "recruitment.pipeline.manage", **_all("recruitment.pipeline.manage")}
    )

    def get_tenant_queryset(self) -> Any:
        services.default_template()
        return ChecklistTemplate.objects.all()


# --- applications ---------------------------------------------------------------------------


class ApplicationViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = TutorApplication
    serializer_class = s.ApplicationSerializer
    permission_classes = perms(
        {"GET": "recruitment.application.view", "POST": "recruitment.application.edit"}
    )

    def get_tenant_queryset(self) -> Any:
        qs = TutorApplication.objects.select_related("stage", "opening")
        q = self.request.query_params
        for key in ("stage", "status", "opening"):
            if q.get(key):
                qs = qs.filter(**{key: q[key]})
        return qs

    def get_serializer_class(self) -> Any:
        return (
            s.ApplicationDetailSerializer if self.action == "retrieve" else s.ApplicationSerializer
        )

    @extend_schema(parameters=[OpenApiParameter(k, str) for k in ("stage", "status", "opening")])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def _detail(self, application: TutorApplication) -> Response:
        application.refresh_from_db()
        return Response(s.ApplicationDetailSerializer(application).data)

    @extend_schema(request=s.StageMoveSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request: Request, pk: Any = None) -> Response:
        payload = s.StageMoveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        stage = get_object_or_404(
            ApplicationStage.objects.all(), pk=payload.validated_data["stage"]
        )
        return self._detail(services.move(self.get_object(), stage, user=request.user))

    @extend_schema(request=s.ScoreSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def score(self, request: Request, pk: Any = None) -> Response:
        payload = s.ScoreSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = self.get_object()
        services.score(application, reviewer=request.user, **payload.validated_data)
        return self._detail(application)

    def _decide(self) -> None:
        if not has_perm(self.request.user, "recruitment.application.decide"):
            raise PermissionDenied()

    @extend_schema(request=s.RejectSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, pk: Any = None) -> Response:
        self._decide()
        payload = s.RejectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._detail(services.reject(self.get_object(), **payload.validated_data))

    @extend_schema(request=s.BulkRejectSerializer, responses=s.CountResultSerializer)
    @action(detail=False, methods=["post"], url_path="bulk-reject")
    def bulk_reject(self, request: Request) -> Response:
        self._decide()
        payload = s.BulkRejectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        apps = list(self.get_queryset().filter(pk__in=payload.validated_data["applications"]))
        count = services.bulk_reject(apps, reason=payload.validated_data["reason"])
        return Response({"count": count})

    @extend_schema(request=s.ApproveSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request: Request, pk: Any = None) -> Response:
        self._decide()
        payload = s.ApproveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = self.get_object()
        services.approve(application, user=request.user, **payload.validated_data)
        return self._detail(application)

    @extend_schema(request=s.ProposeInterviewSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def interviews(self, request: Request, pk: Any = None) -> Response:
        payload = s.ProposeInterviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = self.get_object()
        services.propose_interview(application, interviewer=request.user, **payload.validated_data)
        return self._detail(application)

    @extend_schema(request=s.RequestReferenceSerializer, responses=s.ApplicationDetailSerializer)
    @action(detail=True, methods=["post"])
    def references(self, request: Request, pk: Any = None) -> Response:
        payload = s.RequestReferenceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        application = self.get_object()
        services.request_reference(application, **payload.validated_data)
        return self._detail(application)


# --- onboarding -----------------------------------------------------------------------------


def _tutor(pk: Any) -> TutorProfile:
    return get_object_or_404(TutorProfile.objects.all(), pk=pk)


def _my_tutor(request: Request) -> TutorProfile:
    tutor = TutorProfile.objects.filter(membership__user=request.user).first()
    if tutor is None:
        raise NotFound("You're not a tutor here.")
    return tutor


def _onboarding(tutor: TutorProfile) -> Response:
    instance = ChecklistInstance.objects.filter(tutor=tutor).first()
    if instance is None:
        return Response({"items": [], "completed_at": None})
    return Response(
        s.TutorOnboardingStateSerializer(
            {"items": services.checklist_state(instance), "completed_at": instance.completed_at}
        ).data
    )


class TutorOnboardingView(APIView):
    permission_classes = perms({"GET": "people.tutor.view", "POST": "recruitment.application.edit"})

    @extend_schema(responses=s.TutorOnboardingStateSerializer)
    def get(self, request: Request, pk: str) -> Response:
        return _onboarding(_tutor(pk))


class TutorOnboardingItemView(APIView):
    permission_classes = perms({"POST": "recruitment.application.edit"})

    @extend_schema(request=None, responses=s.TutorOnboardingStateSerializer)
    def post(self, request: Request, pk: str, key: str) -> Response:
        tutor = _tutor(pk)
        services.complete_item(tutor, key, user=request.user)
        return _onboarding(tutor)


class MyOnboardingView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.TutorOnboardingStateSerializer)
    def get(self, request: Request) -> Response:
        return _onboarding(_my_tutor(request))


class MyOnboardingItemView(APIView):
    """The tutor ticks an agreement or training item."""

    permission_classes = AUTH

    @extend_schema(request=None, responses=s.TutorOnboardingStateSerializer)
    def post(self, request: Request, key: str) -> Response:
        tutor = _my_tutor(request)
        instance = ChecklistInstance.objects.filter(tutor=tutor).first()
        item = next((i for i in (instance.items if instance else []) if i["key"] == key), None)
        if item is None or item.get("kind") not in ("agreement", "training", "custom"):
            raise ValidationError({"key": ["This step completes itself when you do it."]})
        services.complete_item(tutor, key, user=request.user)
        return _onboarding(tutor)


# --- compliance -----------------------------------------------------------------------------


class RequirementTypeViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = RequirementType
    serializer_class = s.RequirementTypeSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = perms({"GET": "compliance.view", **_all("compliance.manage_types")})

    def get_tenant_queryset(self) -> Any:
        compliance.ensure_requirement_types()
        return RequirementType.objects.all()


def _compliance(tutor: TutorProfile, *, show_numbers: bool) -> Response:
    applicable = compliance.applicable(tutor)
    records = ComplianceRecord.objects.filter(tutor=tutor).select_related("requirement")
    state = TutorComplianceState.objects.filter(tutor=tutor).first()
    return Response(
        s.TutorComplianceSerializer(
            {
                "restricted": bool(state and state.restricted_by_compliance),
                "problems": compliance.problems(tutor),
                "requirements": applicable,
                "records": records,
            },
            context={"show_numbers": show_numbers},
        ).data
    )


def _submit(request: Request, tutor: TutorProfile) -> None:
    from tutortrack.core.models import StoredFile

    payload = s.SubmitRecordSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    d = payload.validated_data
    requirement = get_object_or_404(RequirementType.objects.all(), pk=d["requirement"])
    files = None
    if "files" in d:
        files = list(StoredFile.objects.filter(pk__in=d["files"], uploaded_by=request.user))
        if len(files) != len(d["files"]):
            raise ValidationError({"files": ["Upload the files first."]})
    compliance.submit(
        tutor,
        requirement,
        number=d["number"],
        issue_date=d.get("issue_date"),
        expiry_date=d.get("expiry_date"),
        files=files,
        notes=d["notes"],
    )


class TutorComplianceView(APIView):
    """``/tutors/{id}/compliance``: requirements, records and restriction (FR-18-6)."""

    permission_classes = perms({"GET": "compliance.view", "POST": "compliance.verify"})

    @extend_schema(responses=s.TutorComplianceSerializer)
    def get(self, request: Request, pk: str) -> Response:
        return _compliance(_tutor(pk), show_numbers=True)

    @extend_schema(request=s.SubmitRecordSerializer, responses=s.TutorComplianceSerializer)
    def post(self, request: Request, pk: str) -> Response:
        tutor = _tutor(pk)
        _submit(request, tutor)
        return _compliance(tutor, show_numbers=True)


class MyComplianceView(APIView):
    """The tutor's own checks: upload documents and see what's missing or expiring."""

    permission_classes = AUTH

    @extend_schema(responses=s.TutorComplianceSerializer)
    def get(self, request: Request) -> Response:
        return _compliance(_my_tutor(request), show_numbers=False)

    @extend_schema(request=s.SubmitRecordSerializer, responses=s.TutorComplianceSerializer)
    def post(self, request: Request) -> Response:
        tutor = _my_tutor(request)
        _submit(request, tutor)
        return _compliance(tutor, show_numbers=False)


class RecordVerifyView(APIView):
    permission_classes = perms({"POST": "compliance.verify"})

    @extend_schema(request=None, responses=s.ComplianceRecordSerializer)
    def post(self, request: Request, pk: str) -> Response:
        record = get_object_or_404(ComplianceRecord.objects.all(), pk=pk)
        return Response(
            s.ComplianceRecordSerializer(
                compliance.verify(record, user=request.user), context={"show_numbers": True}
            ).data
        )


class RecordRejectView(APIView):
    permission_classes = perms({"POST": "compliance.verify"})

    @extend_schema(request=s.RejectRecordSerializer, responses=s.ComplianceRecordSerializer)
    def post(self, request: Request, pk: str) -> Response:
        payload = s.RejectRecordSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        record = get_object_or_404(ComplianceRecord.objects.all(), pk=pk)
        record = compliance.reject(
            record, user=request.user, reason=payload.validated_data["reason"]
        )
        return Response(s.ComplianceRecordSerializer(record, context={"show_numbers": True}).data)


class DashboardView(APIView):
    permission_classes = perms({"GET": "compliance.view"})

    @extend_schema(responses=s.ComplianceDashboardSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.ComplianceDashboardSerializer(compliance.dashboard()).data)


class AssessSubjectView(APIView):
    """Subject competency (FR-18-3): claimed → assessed → approved, with evidence."""

    permission_classes = perms({"POST": "people.tutor.approve_subjects"})

    @extend_schema(request=s.AssessSubjectSerializer, responses=None)
    def post(self, request: Request, pk: str, subject_id: str) -> Response:
        from tutortrack.people.models import TutorSubject

        payload = s.AssessSubjectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        subject = get_object_or_404(TutorSubject.objects.filter(tutor_id=pk), pk=subject_id)
        services.assess_subject(subject, user=request.user, **payload.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- public ---------------------------------------------------------------------------------


def _org_name(request: Request) -> str:
    org = getattr(request, "organisation", None)
    if org is None:
        raise NotFound()
    return str(org.name)


class PublicOpeningsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=s.PublicOpeningSerializer(many=True))
    def get(self, request: Request) -> Response:
        _org_name(request)
        openings = JobOpening.objects.filter(published=True).order_by("title")
        today = compliance.today()
        return Response(
            [s.public_opening(o) for o in openings if not o.closes_on or o.closes_on >= today]
        )


class PublicOpeningView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_form"

    def _opening(self, slug: str) -> JobOpening:
        return get_object_or_404(
            JobOpening.objects.filter(published=True).select_related("form"), slug=slug
        )

    @extend_schema(responses=s.PublicOpeningDetailSerializer)
    def get(self, request: Request, slug: str) -> Response:
        opening = self._opening(slug)
        return Response(
            {
                **s.public_opening(opening),
                "schema": opening.form.schema,
                "turnstile_site_key": getattr(settings, "TURNSTILE_SITE_KEY", ""),
                "organisation": _org_name(request),
            }
        )

    @extend_schema(request=s.PublicApplySerializer, responses={201: None})
    def post(self, request: Request, slug: str) -> Response:
        opening = self._opening(slug)
        payload = s.PublicApplySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        if not verify_turnstile(d["captcha_token"], client_ip(request)):
            raise ValidationError({"captcha_token": ["Please complete the check."]})
        services.apply(
            opening,
            d["data"],
            ip=client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
            honeypot=d["website"],
        )
        return Response(status=status.HTTP_201_CREATED)


class PublicInterviewView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=s.PublicInterviewSerializer)
    def get(self, request: Request, token: str) -> Response:
        interview = services.interview_for_token(token)
        return Response(
            {
                "applicant": interview.application.first_name,
                "options": interview.options,
                "minutes": interview.minutes,
                "status": interview.status,
                "start": interview.start,
                "meeting_url": interview.meeting_url if interview.start else "",
                "organisation": _org_name(request),
            }
        )

    @extend_schema(request=s.BookInterviewSerializer, responses=s.PublicInterviewSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.BookInterviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.book_interview(token, payload.validated_data["start"])
        return self.get(request, token)


class PublicReferenceView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(responses=s.PublicReferenceSerializer)
    def get(self, request: Request, token: str) -> Response:
        reference = services.reference_for_token(token)
        return Response(
            {
                "applicant": reference.application.full_name,
                "status": reference.status,
                "questions": s.REFERENCE_QUESTIONS,
                "organisation": _org_name(request),
            }
        )

    @extend_schema(request=s.GiveReferenceSerializer, responses=s.PublicReferenceSerializer)
    def post(self, request: Request, token: str) -> Response:
        payload = s.GiveReferenceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.submit_reference(token, **payload.validated_data)
        return self.get(request, token)
