"""Lesson delivery API (E09 §4). Completing, cancelling and attendance are lesson actions
in the scheduling API (``/lessons/{id}/complete|cancel|attendance``)."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    scope_queryset,
)
from tutortrack.people.models import Student, TutorProfile
from tutortrack.scheduling.api.serializers import LessonSerializer
from tutortrack.scheduling.models import Lesson

from .. import selectors, services
from ..models import CancellationPolicy, LessonReport, MakeupCredit, ReportTemplate
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


# --- cancellation policies ----------------------------------------------------------------------


class CancellationPolicyViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Cancellation policies (FR-09-3). Updating a policy creates a new version; deleting
    deactivates it (cancellations keep a snapshot of the rules they used)."""

    model = CancellationPolicy
    serializer_class = s.CancellationPolicySerializer
    pagination_class = None
    http_method_names = ["get", "post", "put", "delete", "head", "options"]
    permission_classes = perms(
        {
            "GET": "scheduling.lesson.view",
            "POST": "delivery.policy.manage",
            "PUT": "delivery.policy.manage",
            "DELETE": "delivery.policy.manage",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[CancellationPolicy]:
        return CancellationPolicy.objects.filter(active=True)

    def create(self, request: Request) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        policy = services.save_policy(**payload.validated_data)
        return Response(self.get_serializer(policy).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, pk: Any = None) -> Response:
        current = self.get_object()
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        policy = services.save_policy(policy=current, **payload.validated_data)
        return Response(self.get_serializer(policy).data)

    def perform_destroy(self, instance: CancellationPolicy) -> None:
        services.delete_policy(instance)


# --- report templates ---------------------------------------------------------------------------


class ReportTemplateViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Report templates (FR-09-4). Changing the fields creates a new version; deleting
    archives the template."""

    model = ReportTemplate
    serializer_class = s.ReportTemplateSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = perms(
        {
            "GET": "delivery.report.view",
            "POST": "delivery.template.manage",
            "PATCH": "delivery.template.manage",
            "DELETE": "delivery.template.manage",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[ReportTemplate]:
        qs = ReportTemplate.objects.select_related("current_version").prefetch_related(
            "services", "subjects", "jobs"
        )
        if self.action == "list" and self.request.query_params.get("archived") != "true":
            qs = qs.filter(archived_at__isnull=True)
        return qs

    @staticmethod
    def _data(validated: dict[str, Any]) -> dict[str, Any]:
        data = dict(validated)
        version = data.pop("current_version", None)
        if version is not None:
            data["fields"] = version["fields"]
        return data

    def create(self, request: Request) -> Response:
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        template = services.create_template(**self._data(payload.validated_data))
        return Response(self.get_serializer(template).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, pk: Any = None) -> Response:
        template = self.get_object()
        payload = self.get_serializer(template, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        template = services.update_template(template, **self._data(payload.validated_data))
        return Response(self.get_serializer(template).data)

    def perform_destroy(self, instance: ReportTemplate) -> None:
        services.archive_template(instance)


# --- lesson reports -----------------------------------------------------------------------------


class ReportFilter(filters.FilterSet):
    sla = filters.ChoiceFilter(
        choices=[
            ("due", "Due"),
            ("overdue", "Overdue"),
            ("submitted", "Submitted, not shared"),
            ("awaiting_approval", "Awaiting approval"),
            ("approved", "Approved, not shared"),
            ("shared", "Shared"),
        ],
        method="noop",
        label="SLA state",
    )
    status = filters.MultipleChoiceFilter(choices=LessonReport.Status.choices)
    tutor = filters.UUIDFilter()
    lesson = filters.UUIDFilter()
    student = filters.UUIDFilter(field_name="lesson__attendees__student", distinct=True)

    class Meta:
        model = LessonReport
        fields: list[str] = []

    def noop(self, queryset: QuerySet[Any], name: str, value: Any) -> QuerySet[Any]:
        return queryset  # applied by the selector


class LessonReportViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Lesson reports (FR-09-5..7). ``?sla=overdue`` lists overdue reports; tutors see
    their own. ``PUT`` saves a draft (autosave)."""

    model = LessonReport
    serializer_class = s.LessonReportSerializer
    filterset_class = ReportFilter
    http_method_names = ["get", "post", "put", "head", "options"]
    permission_classes = perms(
        {
            "GET": "delivery.report.view",
            "POST": "delivery.report.write",
            "PUT": "delivery.report.write",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[LessonReport]:
        sla = self.request.query_params.get("sla") if self.action == "list" else None
        return selectors.reports(self.request.user, sla=sla)

    def _writable(self, report: LessonReport) -> LessonReport:
        allowed = scope_queryset(
            self.request.user, LessonReport.objects.filter(pk=report.pk), "delivery.report.write"
        )
        if not allowed.exists():
            raise PermissionDenied()
        return report

    def _out(self, report: LessonReport) -> Response:
        report = self.get_tenant_queryset().get(pk=report.pk)
        return Response(self.get_serializer(report).data)

    @extend_schema(request=s.ReportAnswersSerializer, responses=s.LessonReportSerializer)
    def update(self, request: Request, pk: Any = None) -> Response:
        report = self._writable(self.get_object())
        payload = s.ReportAnswersSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.save_draft(
            report,
            payload.validated_data["answers"],
            user=request.user,
            can_edit_any=has_perm(request.user, "delivery.report.edit_any"),
        )
        return self._out(report)

    @extend_schema(request=s.ReportSubmitSerializer, responses=s.LessonReportSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: Any = None) -> Response:
        report = self._writable(self.get_object())
        payload = s.ReportSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        services.submit_report(
            report,
            user=request.user,
            answers=payload.validated_data.get("answers"),
            can_edit_any=has_perm(request.user, "delivery.report.edit_any"),
        )
        return self._out(report)

    @extend_schema(request=None, responses=s.LessonReportSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "delivery.report.approve"}),
    )
    def approve(self, request: Request, pk: Any = None) -> Response:
        report = services.approve_report(self.get_object(), user=request.user)
        return self._out(report)

    @extend_schema(request=s.ReportReturnSerializer, responses=s.LessonReportSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="return",
        permission_classes=perms({"POST": "delivery.report.approve"}),
    )
    def return_to_tutor(self, request: Request, pk: Any = None) -> Response:
        payload = s.ReportReturnSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        report = services.return_report(
            self.get_object(), user=request.user, note=payload.validated_data["note"]
        )
        return self._out(report)

    @extend_schema(request=None, responses=s.LessonReportSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "delivery.report.share"})
    )
    def share(self, request: Request, pk: Any = None) -> Response:
        report = services.share_report(self.get_object(), user=request.user)
        return self._out(report)

    @extend_schema(methods=["GET"], request=None, responses=s.ReportCommentSerializer(many=True))
    @extend_schema(
        methods=["POST"],
        request=s.ReportCommentSerializer,
        responses={201: s.ReportCommentSerializer},
    )
    @action(
        detail=True,
        methods=["get", "post"],
        pagination_class=None,
        permission_classes=perms({"GET": "delivery.report.view", "POST": "delivery.report.view"}),
    )
    def comments(self, request: Request, pk: Any = None) -> Response:
        report = self.get_object()
        if request.method == "GET":
            rows = report.comments.all()
            return Response(s.ReportCommentSerializer(rows, many=True).data)
        payload = s.ReportCommentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        comment = services.add_comment(report, user=request.user, **payload.validated_data)
        return Response(s.ReportCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class LessonReportsView(APIView):
    """A lesson's reports (one per tutor). ``POST`` opens the report for a tutor (you, if
    you are the lesson's tutor) so it can be written, even before completion."""

    permission_classes = perms({"GET": "delivery.report.view", "POST": "delivery.report.write"})

    def _lesson(self, request: Request, lesson_id: Any) -> Lesson:
        qs = scope_queryset(request.user, Lesson.objects.all(), "scheduling.lesson.view")
        return get_object_or_404(qs, pk=lesson_id)

    @extend_schema(responses=s.LessonReportSerializer(many=True))
    def get(self, request: Request, lesson_id: Any) -> Response:
        lesson = self._lesson(request, lesson_id)
        rows = selectors.reports(request.user).filter(lesson=lesson)
        return Response(s.LessonReportSerializer(rows, many=True).data)

    @extend_schema(request=s.ReportOpenSerializer, responses={201: s.LessonReportSerializer})
    def post(self, request: Request, lesson_id: Any) -> Response:
        lesson = self._lesson(request, lesson_id)
        payload = s.ReportOpenSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        tutor_id = payload.validated_data.get("tutor")
        tutors = scope_queryset(request.user, TutorProfile.objects.all(), "people.tutor.view")
        if tutor_id is None:
            tutor = TutorProfile.objects.filter(membership__user=request.user).first()
            if tutor is None:
                raise ValidationError({"tutor": ["Choose the tutor."]})
        else:
            tutor = get_object_or_404(tutors, pk=tutor_id)
        report = services.open_report(lesson, tutor)
        if not scope_queryset(
            request.user, LessonReport.objects.filter(pk=report.pk), "delivery.report.write"
        ).exists():
            raise PermissionDenied()
        report = selectors.reports(request.user).get(pk=report.pk)
        return Response(s.LessonReportSerializer(report).data, status=status.HTTP_201_CREATED)


# --- unconfirmed lessons ------------------------------------------------------------------------


class UnconfirmedLessonsView(APIView):
    """FR-09-8: past lessons still planned. Bulk complete or cancel them with
    ``POST /lessons/bulk``; ``POST`` here nudges their tutors."""

    permission_classes = perms(
        {"GET": "scheduling.lesson.view", "POST": "scheduling.lesson.complete"}
    )

    @extend_schema(responses=LessonSerializer(many=True))
    def get(self, request: Request) -> Response:
        lessons = selectors.unconfirmed_lessons(request.user)[:500]
        return Response(LessonSerializer(lessons, many=True, context={"request": request}).data)

    @extend_schema(request=s.NudgeSerializer, responses=s.NudgeResultSerializer)
    def post(self, request: Request) -> Response:
        payload = s.NudgeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        lessons = selectors.unconfirmed_lessons(request.user).filter(
            pk__in=payload.validated_data["ids"]
        )
        nudged = sum(services.nudge_unconfirmed(lesson) for lesson in lessons)
        return Response({"nudged": nudged})


# --- makeup credits -----------------------------------------------------------------------------


class MakeupCreditFilter(filters.FilterSet):
    student = filters.UUIDFilter()
    client = filters.UUIDFilter()

    class Meta:
        model = MakeupCredit
        fields: list[str] = []


class MakeupCreditViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    model = MakeupCredit
    serializer_class = s.MakeupCreditSerializer
    filterset_class = MakeupCreditFilter
    permission_classes = perms({"GET": "delivery.makeup.view", "POST": "delivery.makeup.manage"})

    def get_tenant_queryset(self) -> QuerySet[MakeupCredit]:
        return selectors.makeup_credits(self.request.user)

    @extend_schema(request=s.ConsumeSerializer, responses=s.MakeupCreditSerializer)
    @action(detail=True, methods=["post"])
    def consume(self, request: Request, pk: Any = None) -> Response:
        payload = s.ConsumeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        credit = services.consume_makeup_credit(self.get_object(), payload.validated_data["lesson"])
        return Response(self.get_serializer(credit).data)

    @extend_schema(request=s.ExtendSerializer, responses=s.MakeupCreditSerializer)
    @action(detail=True, methods=["post"])
    def extend(self, request: Request, pk: Any = None) -> Response:
        payload = s.ExtendSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        credit = services.extend_makeup_credit(
            self.get_object(), until=payload.validated_data["until"]
        )
        return Response(self.get_serializer(credit).data)

    @extend_schema(request=s.VoidSerializer, responses=s.MakeupCreditSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request: Request, pk: Any = None) -> Response:
        payload = s.VoidSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        credit = services.void_makeup_credit(self.get_object(), **payload.validated_data)
        return Response(self.get_serializer(credit).data)


# --- attendance stats ---------------------------------------------------------------------------


class AttendanceStatsView(APIView):
    permission_classes = perms({"GET": "people.student.view"})

    @extend_schema(
        responses=s.AttendanceStatsSerializer,
        parameters=[OpenApiParameter("student_id", str, OpenApiParameter.PATH)],
    )
    def get(self, request: Request, student_id: Any) -> Response:
        students = scope_queryset(request.user, Student.objects.all(), "people.student.view")
        student = get_object_or_404(students, pk=student_id)
        stats = selectors.attendance_stats(student.pk)
        return Response(s.AttendanceStatsSerializer(stats).data)
