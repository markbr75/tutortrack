"""Jobs API (E07 §4)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import Prefetch, Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    scope_queryset,
)
from tutortrack.crm.listing import apply_crm_filters
from tutortrack.people.models import Student

from .. import selectors, services
from ..models import Job, JobStudent, JobTutor
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def needs(codename: str) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_({"*": codename, "GET": "jobs.job.view"})]


class JobFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Job.Status.choices)
    client = filters.UUIDFilter()
    service = filters.UUIDFilter()
    branch = filters.UUIDFilter()
    student = filters.UUIDFilter(field_name="students__student", distinct=True)
    tutor = filters.UUIDFilter(method="by_tutor")
    q = filters.CharFilter(method="search", label="Search reference and name")
    attention = filters.BooleanFilter(method="needs_attention", label="Jobs needing attention")

    class Meta:
        model = Job
        fields: list[str] = []

    def by_tutor(self, qs: QuerySet[Job], name: str, value: Any) -> QuerySet[Job]:
        return qs.filter(tutors__tutor=value, tutors__status__in=services.CURRENT).distinct()

    def search(self, qs: QuerySet[Job], name: str, value: str) -> QuerySet[Job]:
        return qs.filter(Q(reference__icontains=value) | Q(name__icontains=value))

    def needs_attention(self, qs: QuerySet[Job], name: str, value: bool) -> QuerySet[Job]:
        return selectors.needing_attention(qs) if value else qs


class JobViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Jobs (E07). Tutors see the jobs they're on, without charge rates or margins."""

    model = Job
    filterset_class = JobFilter
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = [
        *AUTH,
        HasMethodPermission.for_(
            {"GET": "jobs.job.view", "POST": "jobs.job.create", "PATCH": "jobs.job.edit"}
        ),
    ]

    def get_serializer_class(self) -> Any:
        return s.JobCreateSerializer if self.action == "create" else s.JobSerializer

    def get_tenant_queryset(self) -> QuerySet[Job]:
        qs = scope_queryset(self.request.user, Job.objects.all(), "jobs.job.view")
        qs = qs.select_related("client", "service").prefetch_related(
            Prefetch("students", queryset=JobStudent.objects.select_related("student")),
            Prefetch("tutors", queryset=JobTutor.objects.select_related("tutor")),
        )
        if self.action == "list":
            qs = apply_crm_filters(qs, self.request.query_params, "jobs.job")
        return qs

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        students = data.pop("students_in")
        tutors = data.pop("tutors_in", [])
        sets_rates = data.get("charge_rate") or any(
            row.get("charge_rate_override") for row in students
        )
        if sets_rates and not has_perm(self.request.user, "billing.rates.view_charge"):
            raise PermissionDenied()
        if tutors and not has_perm(self.request.user, "jobs.job.manage_tutors"):
            raise PermissionDenied()
        visible = scope_queryset(self.request.user, Student.objects.all(), "people.student.view")
        if visible.filter(pk__in=[row["student"].pk for row in students]).count() != len(students):
            raise NotFound()
        serializer.instance = services.create_job(
            client=data.pop("client"), service=data.pop("service"), students=students,
            tutors=tutors, status=data.pop("status"), **data,
        )  # fmt: skip

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_job(serializer.instance, **serializer.validated_data)

    # --- status ------------------------------------------------------------------------------

    @extend_schema(request=s.StatusChangeSerializer, responses=s.JobSerializer)
    @action(detail=True, methods=["post"], permission_classes=needs("jobs.job.change_status"))
    def status(self, request: Request, pk: Any = None) -> Response:
        payload = s.StatusChangeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        job = services.change_status(self.get_object(), **payload.validated_data)
        return Response(s.JobSerializer(job, context=self.get_serializer_context()).data)

    @extend_schema(responses=s.StatusHistorySerializer(many=True))
    @action(detail=True, methods=["get"], url_path="status-history", pagination_class=None)
    def status_history(self, request: Request, pk: Any = None) -> Response:
        rows = self.get_object().status_history.all()
        return Response(s.StatusHistorySerializer(rows, many=True).data)

    # --- students ----------------------------------------------------------------------------

    @extend_schema(request=s.StudentInput, responses={201: s.JobStudentSerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path="students",
        permission_classes=needs("jobs.job.edit"),
    )
    def add_student(self, request: Request, pk: Any = None) -> Response:
        payload = s.StudentInput(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.add_student(self.get_object(), **payload.validated_data)
        return Response(
            s.JobStudentSerializer(link, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def _student_link(self, link_id: str) -> JobStudent:
        return get_object_or_404(JobStudent, pk=link_id, job=self.get_object())

    @extend_schema(request=s.StudentRateSerializer, responses=s.JobStudentSerializer)
    @action(
        detail=True, methods=["patch"], url_path=r"students/(?P<link_id>[0-9a-f-]+)",
        permission_classes=needs("jobs.job.edit"),
    )  # fmt: skip
    def student_rate(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        if not has_perm(request.user, "billing.rates.view_charge"):
            raise PermissionDenied()
        payload = s.StudentRateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.set_student_rate(
            self._student_link(link_id), payload.validated_data["charge_rate_override"]
        )
        return Response(s.JobStudentSerializer(link, context=self.get_serializer_context()).data)

    @extend_schema(request=s.EndSerializer, responses=s.JobStudentSerializer)
    @action(
        detail=True, methods=["post"], url_path=r"students/(?P<link_id>[0-9a-f-]+)/end",
        permission_classes=needs("jobs.job.edit"),
    )  # fmt: skip
    def end_student(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        payload = s.EndSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.end_student(
            self._student_link(link_id), active_to=payload.validated_data.get("end_date")
        )
        return Response(s.JobStudentSerializer(link, context=self.get_serializer_context()).data)

    # --- tutors ------------------------------------------------------------------------------

    def _tutor_link(self, link_id: str) -> JobTutor:
        return get_object_or_404(JobTutor, pk=link_id, job=self.get_object())

    @extend_schema(request=s.TutorInput, responses={201: s.JobTutorSerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path="tutors",
        permission_classes=needs("jobs.job.manage_tutors"),
    )
    def add_tutor(self, request: Request, pk: Any = None) -> Response:
        payload = s.TutorInput(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.add_tutor(self.get_object(), **payload.validated_data)
        return Response(
            s.JobTutorSerializer(link, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.TutorRateSerializer, responses=s.JobTutorSerializer)
    @action(
        detail=True, methods=["patch"], url_path=r"tutors/(?P<link_id>[0-9a-f-]+)",
        permission_classes=needs("jobs.job.manage_tutors"),
    )  # fmt: skip
    def tutor_rate(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        if not has_perm(request.user, "billing.rates.view_pay"):
            raise PermissionDenied()
        payload = s.TutorRateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.set_tutor_rate(
            self._tutor_link(link_id), payload.validated_data["pay_rate_override"]
        )
        return Response(s.JobTutorSerializer(link, context=self.get_serializer_context()).data)

    @extend_schema(request=s.EndSerializer, responses=s.JobTutorSerializer)
    @action(
        detail=True, methods=["post"], url_path=r"tutors/(?P<link_id>[0-9a-f-]+)/remove",
        permission_classes=needs("jobs.job.manage_tutors"),
    )  # fmt: skip
    def remove_tutor(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        payload = s.EndSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.remove_tutor(
            self._tutor_link(link_id),
            end_date=payload.validated_data.get("end_date"),
            reason=payload.validated_data["reason"],
        )
        return Response(s.JobTutorSerializer(link, context=self.get_serializer_context()).data)

    @extend_schema(request=s.ReplaceSerializer, responses=s.ReplacementSerializer)
    @action(
        detail=True, methods=["post"], url_path=r"tutors/(?P<link_id>[0-9a-f-]+)/replace",
        permission_classes=needs("jobs.job.manage_tutors"),
    )  # fmt: skip
    def replace_tutor(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        """Replace a tutor from a date. ``dry_run: true`` previews the future lessons that
        would move and any clashes for the new tutor."""
        payload = s.ReplaceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        result = services.replace_tutor(
            self._tutor_link(link_id),
            new_tutor=data["tutor"],
            effective_date=data["effective_date"],
            pay_rate_override=data.get("pay_rate_override"),
            dry_run=data["dry_run"],
        )
        return Response(
            {
                "lessons": [dataclasses.asdict(lesson) for lesson in result.preview.lessons],
                "conflicts": len(result.preview.conflicts),
                "new_assignment": s.JobTutorSerializer(
                    result.new_link, context=self.get_serializer_context()
                ).data
                if result.new_link
                else None,
            }
        )

    @extend_schema(request=s.RespondSerializer, responses=s.JobTutorSerializer)
    @action(
        detail=True, methods=["post"], url_path=r"tutors/(?P<link_id>[0-9a-f-]+)/respond",
        permission_classes=[*AUTH, HasMethodPermission.for_({"*": "jobs.job.view"})],
    )  # fmt: skip
    def respond(self, request: Request, pk: Any = None, link_id: str = "") -> Response:
        """The offered tutor (or a coordinator) accepts or declines the job."""
        link = self._tutor_link(link_id)
        membership = link.tutor.membership
        is_tutor = membership is not None and membership.user_id == request.user.pk
        if not is_tutor and not has_perm(request.user, "jobs.job.manage_tutors"):
            raise PermissionDenied()
        payload = s.RespondSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        link = services.respond_to_offer(link, accept=payload.validated_data["accept"])
        return Response(s.JobTutorSerializer(link, context=self.get_serializer_context()).data)

    # --- summary, hours, duplicate, quick setup ------------------------------------------------

    @extend_schema(responses=s.JobSummarySerializer)
    @action(detail=True, methods=["get"])
    def summary(self, request: Request, pk: Any = None) -> Response:
        """Expected per-lesson economics and delivered totals. Charges need
        ``billing.rates.view_charge``; pay and margin also need ``billing.rates.view_pay``."""
        if not has_perm(request.user, "billing.rates.view_charge"):
            raise PermissionDenied()
        summary = selectors.summary(self.get_object())
        with_pay = has_perm(request.user, "billing.rates.view_pay")

        def economics(e: selectors.Economics | None) -> dict[str, Any] | None:
            if e is None:
                return None
            out: dict[str, Any] = {"charge": e.charge.to_dict()}
            if with_pay:
                out["pay"] = e.pay.to_dict()
                out["margin"] = e.margin.to_dict()
                out["margin_percent"] = (
                    str(e.margin_percent) if e.margin_percent is not None else None
                )
            return out

        result = {
            "per_lesson": economics(summary.per_lesson),
            "trace": summary.trace,
            "lessons_planned": summary.lessons_planned,
            "lessons_completed": summary.lessons_completed,
            "hours_delivered": str(summary.hours_delivered),
            "delivered": economics(summary.delivered),
            "next_lesson_at": summary.next_lesson_at,
            "last_lesson_at": summary.last_lesson_at,
        }
        return Response(result)  # pay/margin keys are omitted, not null, without view_pay

    @extend_schema(
        parameters=[OpenApiParameter("extra_hours", str), OpenApiParameter("on", str)],
        responses=s.HoursCheckSerializer,
    )
    @action(detail=True, methods=["get"], url_path="hours-check")
    def hours_check(self, request: Request, pk: Any = None) -> Response:
        """Whether more hours fit within the job's cap (warn at 80%, block at 100%)."""
        try:
            extra = Decimal(request.query_params.get("extra_hours", "0"))
        except InvalidOperation as exc:
            raise ValidationError({"extra_hours": ["Enter a number."]}) from exc
        on = (
            parse_date(request.query_params.get("on", ""))
            if request.query_params.get("on")
            else None
        )
        check = services.check_hours(self.get_object(), extra_hours=extra, on=on)
        return Response(s.HoursCheckSerializer(dataclasses.asdict(check)).data)

    @extend_schema(request=None, responses={201: s.JobSerializer})
    @action(detail=True, methods=["post"], permission_classes=needs("jobs.job.create"))
    def duplicate(self, request: Request, pk: Any = None) -> Response:
        raw = request.data.get("start_date") if isinstance(request.data, dict) else None
        start = parse_date(str(raw)) if raw else None
        job = services.duplicate_job(self.get_object(), start_date=start)
        return Response(
            s.JobSerializer(job, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=s.QuickSetupSerializer, responses={201: s.JobSerializer})
    @action(
        detail=False,
        methods=["post"],
        url_path="quick-setup",
        permission_classes=needs("jobs.job.create"),
    )
    def quick_setup(self, request: Request) -> Response:
        """ "Set up lessons" for a student: service, rate, tutor and weekly times in one step."""
        payload = s.QuickSetupSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        visible = scope_queryset(request.user, Student.objects.all(), "people.student.view")
        if not visible.filter(pk=data["student"].pk).exists():
            raise NotFound()
        if data.get("tutor") and not has_perm(request.user, "jobs.job.manage_tutors"):
            raise PermissionDenied()
        if data.get("pay_rate") and not has_perm(request.user, "billing.rates.view_pay"):
            raise PermissionDenied()
        if data.get("charge_rate") and not has_perm(request.user, "billing.rates.view_charge"):
            raise PermissionDenied()
        job = services.quick_setup(**data)
        return Response(
            s.JobSerializer(job, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )
