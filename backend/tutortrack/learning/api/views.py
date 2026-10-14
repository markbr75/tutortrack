"""Learning API (E21) for staff and tutors: resources and sharing, homework, curricula
and topic mastery, goals, assessments and trends, progress reports, the lending library
and quizzes. Tutors use the same endpoints with their ``own`` scope."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, has_perm
from tutortrack.core.permissions import permission_scope as scope_of
from tutortrack.core.time import now
from tutortrack.people.models import Student

from .. import curricula, progress, selectors, services
from ..models import (
    Assessment,
    AssessmentResult,
    Curriculum,
    CurriculumNode,
    Goal,
    GradeScale,
    Homework,
    HomeworkAssignment,
    LessonTopic,
    LibraryItem,
    Loan,
    ProgressReport,
    Quiz,
    QuizAttempt,
    Resource,
    ResourceFolder,
    ResourceShare,
    TopicMastery,
)
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def crud(view: str, manage: str) -> dict[str, str]:
    return {"GET": view, "POST": manage, "PATCH": manage, "PUT": manage, "DELETE": manage}


def org_wide(user: Any, codename: str) -> None:
    """Organisation-wide settings (grade scales) need more than an ``own`` grant."""
    if scope_of(user, codename) in (None, "own"):
        raise PermissionDenied()


# --- resources (T01) ----------------------------------------------------------------------------

RESOURCE = crud("learning.resource.view", "learning.resource.manage")


class FolderViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = ResourceFolder
    serializer_class = s.ResourceFolderSerializer
    permission_classes = perms(RESOURCE)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None

    def get_tenant_queryset(self) -> QuerySet[ResourceFolder]:
        return selectors.folders(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_folder(
            None, user=self.request.user, **serializer.validated_data
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_folder(
            serializer.instance, user=self.request.user, **serializer.validated_data
        )

    def perform_destroy(self, instance: ResourceFolder) -> None:
        services.delete_folder(instance, user=self.request.user)


class ResourceFilter(filters.FilterSet):
    folder = filters.UUIDFilter()
    kind = filters.ChoiceFilter(choices=Resource.Kind.choices)
    media_type = filters.ChoiceFilter(choices=Resource.MediaType.choices)
    subject = filters.UUIDFilter()
    level = filters.UUIDFilter()
    topic = filters.UUIDFilter(field_name="topics")
    owner = filters.UUIDFilter()
    library = filters.ChoiceFilter(
        choices=[("organisation", "organisation"), ("personal", "personal")], method="by_library"
    )
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)
    q = filters.CharFilter(method="search")

    class Meta:
        model = Resource
        fields: list[str] = []

    def by_library(self, qs: QuerySet[Resource], name: str, value: str) -> QuerySet[Resource]:
        return qs.filter(owner__isnull=value == "organisation")

    def search(self, qs: QuerySet[Resource], name: str, value: str) -> QuerySet[Resource]:
        return qs.filter(
            Q(title__icontains=value) | Q(description__icontains=value) | Q(tags__icontains=value)
        )


class ResourceViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """The resource library: organisation library and tutors' personal libraries; files
    (uploaded through ``/files/uploads``, counted against the plan's storage) and links
    (YouTube, Google Docs, any web page)."""

    model = Resource
    serializer_class = s.ResourceSerializer
    filterset_class = ResourceFilter
    permission_classes = perms(RESOURCE)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Resource]:
        return selectors.resources(self.request.user).prefetch_related("topics")

    @extend_schema(
        examples=[
            OpenApiExample(
                "A YouTube link",
                request_only=True,
                value={
                    "title": "Equivalent fractions explained",
                    "kind": "link",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "tags": ["fractions", "year 6"],
                    "visibility": "tutors",
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_resource(
            None, user=self.request.user, **serializer.validated_data
        )

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_resource(
            serializer.instance, user=self.request.user, **serializer.validated_data
        )

    @extend_schema(request=s.LearningArchiveSerializer, responses=s.ResourceSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        payload = s.LearningArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        resource = services.set_resource_archived(
            self.get_object(), payload.validated_data["archived"], user=request.user
        )
        return Response(self.get_serializer(resource).data)

    @extend_schema(
        request=s.ShareRequestSerializer,
        responses={201: s.ResourceShareSerializer(many=True)},
        examples=[
            OpenApiExample(
                "Share with a class",
                request_only=True,
                value={"classes": ["0192f0c4-0000-7000-8000-000000000001"], "message": "Revise"},
            )
        ],
    )
    @action(
        detail=True,
        methods=["post"],
        pagination_class=None,
        permission_classes=perms({"POST": "learning.resource.share"}),
    )
    def share(self, request: Request, pk: Any = None) -> Response:
        """Share with students, every student of a job, a lesson's attendees or a class.
        Families see it in the portal (and are told)."""
        payload = s.ShareRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        shares = services.share_resource(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return Response(
            s.ResourceShareSerializer(shares, many=True).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(responses=s.ResourceShareSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def shares(self, request: Request, pk: Any = None) -> Response:
        resource = self.get_object()
        qs = resource.shares.select_related("student", "job", "lesson", "group_class")
        return Response(s.ResourceShareSerializer(qs, many=True).data)

    @extend_schema(responses=s.ResourceActivitySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def activity(self, request: Request, pk: Any = None) -> Response:
        """Who viewed or downloaded the resource."""
        qs = self.get_object().activity.select_related("user", "student")
        return Response(s.ResourceActivitySerializer(qs, many=True).data)

    @extend_schema(request=None, responses=s.OpenResourceSerializer)
    @action(
        detail=True, methods=["post"], permission_classes=perms({"POST": "learning.resource.view"})
    )
    def open(self, request: Request, pk: Any = None) -> Response:
        """A short-lived download link (files) or the link itself; records the view."""
        return Response(services.open_resource(self.get_object(), request.user))


class ShareViewSet(
    TenantScopedViewMixin, mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    model = ResourceShare
    serializer_class = s.ResourceShareSerializer
    permission_classes = perms(
        {"GET": "learning.resource.view", "DELETE": "learning.resource.share"}
    )

    def get_tenant_queryset(self) -> QuerySet[ResourceShare]:
        qs = selectors.resource_shares(self.request.user)
        for key in ("student", "lesson", "job", "group_class", "resource"):
            value = self.request.query_params.get(key)
            if value:
                qs = qs.filter(**{f"{key}_id": value})
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter(k, OpenApiTypes.UUID)
            for k in ("student", "lesson", "job", "group_class", "resource")
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance: ResourceShare) -> None:
        services.unshare(instance, user=self.request.user)


class StorageView(APIView):
    permission_classes = perms({"GET": "learning.resource.view"})

    @extend_schema(responses=s.StorageUsageSerializer)
    def get(self, request: Request) -> Response:
        """Storage used against the plan's allowance (E04 ``storage_gb``)."""
        return Response(s.StorageUsageSerializer(selectors.storage_usage()).data)


# --- homework (T02) -----------------------------------------------------------------------------

HOMEWORK = crud("learning.homework.view", "learning.homework.manage")


class GradeScaleViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = GradeScale
    serializer_class = s.GradeScaleSerializer
    permission_classes = perms(HOMEWORK)
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None

    def get_tenant_queryset(self) -> QuerySet[GradeScale]:
        if not GradeScale.objects.exists():
            services.ensure_default_scales()
        return selectors.grade_scales()

    def perform_create(self, serializer: Any) -> None:
        org_wide(self.request.user, "learning.homework.manage")
        serializer.instance = services.save_grade_scale(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        org_wide(self.request.user, "learning.homework.manage")
        serializer.instance = services.save_grade_scale(
            serializer.instance, **serializer.validated_data
        )


class HomeworkFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Homework.Status.choices)
    student = filters.UUIDFilter(field_name="assignments__student", distinct=True)
    group_class = filters.UUIDFilter()
    lesson = filters.UUIDFilter()
    job = filters.UUIDFilter()
    set_by = filters.UUIDFilter()

    class Meta:
        model = Homework
        fields: list[str] = []


class HomeworkViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Homework set from a lesson, report, class, job or standalone. Each student gets an
    assignment with its own reminder workflow."""

    model = Homework
    serializer_class = s.HomeworkSerializer
    filterset_class = HomeworkFilter
    permission_classes = perms(HOMEWORK)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Homework]:
        return selectors.homework(self.request.user).prefetch_related("attachments")

    @extend_schema(
        request=s.HomeworkCreateSerializer,
        responses={201: s.HomeworkSerializer},
        examples=[
            OpenApiExample(
                "Worksheet for a class",
                request_only=True,
                value={
                    "title": "Fractions worksheet",
                    "instructions": "Questions 1-10. Show your working.",
                    "due_at": "2026-11-03T18:00:00Z",
                    "submission_type": "file",
                    "group_class": "0192f0c4-0000-7000-8000-000000000001",
                    "expected_minutes": 30,
                },
            )
        ],
    )
    def create(self, request: Request) -> Response:
        payload = s.HomeworkCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        homework = services.assign_homework(user=request.user, **payload.validated_data)
        return Response(self.get_serializer(homework).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.HomeworkUpdateSerializer, responses=s.HomeworkSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.HomeworkUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        homework = services.update_homework(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return Response(self.get_serializer(homework).data)

    @extend_schema(request=None, responses=s.HomeworkSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: Any = None) -> Response:
        homework = services.cancel_homework(self.get_object(), user=request.user)
        return Response(self.get_serializer(homework).data)


class AssignmentFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=HomeworkAssignment.Status.choices)
    student = filters.UUIDFilter()
    homework = filters.UUIDFilter()
    overdue = filters.BooleanFilter(method="by_overdue")

    class Meta:
        model = HomeworkAssignment
        fields: list[str] = []

    def by_overdue(
        self, qs: QuerySet[HomeworkAssignment], name: str, value: bool
    ) -> QuerySet[HomeworkAssignment]:
        overdue = Q(status__in=HomeworkAssignment.OPEN, due_at__lt=now())
        return qs.filter(overdue) if value else qs.exclude(overdue)


class AssignmentViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """One student's homework: submissions, review (grade and feedback, or back for
    resubmission) and completion stats."""

    model = HomeworkAssignment
    serializer_class = s.AssignmentSerializer
    filterset_class = AssignmentFilter
    permission_classes = perms(
        {"GET": "learning.homework.view", "POST": "learning.homework.review"}
    )

    def get_tenant_queryset(self) -> QuerySet[HomeworkAssignment]:
        return selectors.assignments(self.request.user).prefetch_related("submissions__files")

    @extend_schema(
        request=s.ReviewSerializer,
        responses=s.AssignmentSerializer,
        examples=[
            OpenApiExample(
                "Mark complete",
                request_only=True,
                value={"outcome": "complete", "grade": "7", "feedback": "Well done."},
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def review(self, request: Request, pk: Any = None) -> Response:
        payload = s.ReviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        assignment = services.review_homework(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=assignment.pk)).data)

    @extend_schema(request=None, responses=s.AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def excuse(self, request: Request, pk: Any = None) -> Response:
        assignment = services.excuse_homework(self.get_object(), user=request.user)
        return Response(self.get_serializer(assignment).data)

    @extend_schema(
        responses=s.HomeworkStatsSerializer,
        parameters=[OpenApiParameter("student", OpenApiTypes.UUID)],
    )
    @action(detail=False, methods=["get"], pagination_class=None)
    def stats(self, request: Request) -> Response:
        """Completion stats (optionally for one student)."""
        qs = self.get_queryset()
        student = request.query_params.get("student")
        if student:
            qs = qs.filter(student_id=student)
        return Response(s.HomeworkStatsSerializer(selectors.homework_stats(qs)).data)


# --- curriculum and topics (T03) ----------------------------------------------------------------

CURRICULUM = crud("learning.curriculum.view", "learning.curriculum.manage")


class CurriculumViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = Curriculum
    serializer_class = s.CurriculumSerializer
    permission_classes = perms(CURRICULUM)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Curriculum]:
        qs = selectors.curricula(self.request.user)
        if self.request.query_params.get("archived") not in {"1", "true"}:
            qs = qs.filter(archived_at__isnull=True)
        return qs

    @extend_schema(parameters=[OpenApiParameter("archived", OpenApiTypes.BOOL)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_curriculum(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_curriculum(
            serializer.instance, **serializer.validated_data
        )

    @extend_schema(request=s.LearningArchiveSerializer, responses=s.CurriculumSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        payload = s.LearningArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        curriculum = services.set_curriculum_archived(
            self.get_object(), payload.validated_data["archived"]
        )
        return Response(self.get_serializer(curriculum).data)

    @extend_schema(responses=s.TreeUnitSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def tree(self, request: Request, pk: Any = None) -> Response:
        """Units in order with their topics."""
        nodes = list(self.get_object().nodes.all())
        units = sorted((n for n in nodes if n.parent_id is None), key=lambda n: n.position)
        rows = [
            {
                "id": u.pk,
                "name": u.name,
                "code": u.code,
                "position": u.position,
                "topics": sorted(
                    (n for n in nodes if n.parent_id == u.pk), key=lambda n: n.position
                ),
            }
            for u in units
        ]
        return Response(s.TreeUnitSerializer(rows, many=True).data)

    @extend_schema(
        request=s.CsvImportSerializer,
        responses=s.CsvImportResultSerializer,
        examples=[
            OpenApiExample(
                "Two topics",
                request_only=True,
                value={"content": "unit,topic,code\nNumber,Fractions,N1\nNumber,Percentages,N2"},
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="import")
    def import_csv(self, request: Request, pk: Any = None) -> Response:
        """Add units and topics from CSV (``unit,topic,code``); existing ones are kept."""
        payload = s.CsvImportSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.import_csv(self.get_object(), payload.validated_data["content"])
        return Response(s.CsvImportResultSerializer(result).data)

    @extend_schema(responses=s.BuiltinCurriculumSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def builtins(self, request: Request) -> Response:
        """Specifications that can be installed (GCSE Maths, KS2 English, SAT Math)."""
        installed = set(
            Curriculum.objects.filter(archived_at__isnull=True)
            .exclude(source_key="")
            .values_list("source_key", flat=True)
        )
        rows = [
            {
                "key": c.key,
                "name": c.name,
                "subject": c.subject,
                "level": c.level,
                "exam_board": c.exam_board,
                "units": len(c.units),
                "topics": sum(len(t) for _u, t in c.units),
                "installed": c.key in installed,
            }
            for c in curricula.BUILTINS.values()
        ]
        return Response(s.BuiltinCurriculumSerializer(rows, many=True).data)

    @extend_schema(request=s.InstallBuiltinSerializer, responses={201: s.CurriculumSerializer})
    @action(detail=False, methods=["post"])
    def install(self, request: Request) -> Response:
        payload = s.InstallBuiltinSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        curriculum = services.install_builtin(data.pop("key"), **data)
        return Response(self.get_serializer(curriculum).data, status=status.HTTP_201_CREATED)


class NodeViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = CurriculumNode
    serializer_class = s.CurriculumNodeSerializer
    permission_classes = perms(CURRICULUM)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[CurriculumNode]:
        qs = CurriculumNode.objects.filter(
            curriculum__in=selectors.curricula(self.request.user).values("pk")
        )
        curriculum = self.request.query_params.get("curriculum")
        return qs.filter(curriculum_id=curriculum) if curriculum else qs

    @extend_schema(parameters=[OpenApiParameter("curriculum", OpenApiTypes.UUID)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_node(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_node(serializer.instance, **serializer.validated_data)

    def perform_destroy(self, instance: CurriculumNode) -> None:
        services.delete_node(instance)


class TopicSuggestionsView(APIView):
    permission_classes = perms({"GET": "learning.curriculum.view"})

    @extend_schema(
        responses=s.TopicSuggestionSerializer(many=True),
        parameters=[
            OpenApiParameter("lesson", OpenApiTypes.UUID),
            OpenApiParameter("q", str),
        ],
    )
    def get(self, request: Request) -> Response:
        """Topics for the lesson report "topics covered" picker (the lesson's subject
        first)."""
        from tutortrack.scheduling.models import Lesson

        lesson_id = request.query_params.get("lesson")
        lesson = (
            Lesson.objects.select_related("service").filter(pk=lesson_id).first()
            if lesson_id
            else None
        )
        rows = [
            {
                "id": n.pk,
                "name": n.name,
                "code": n.code,
                "unit": n.parent.name if n.parent else "",
                "curriculum": n.curriculum.name,
                "curriculum_id": n.curriculum_id,
            }
            for n in selectors.topic_suggestions(
                lesson=lesson, q=request.query_params.get("q", "")[:100]
            )
        ]
        return Response(s.TopicSuggestionSerializer(rows, many=True).data)


class LessonTopicViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Topics covered in lessons. POST tags a lesson (students' mastery moves on)."""

    model = LessonTopic
    serializer_class = s.LessonTopicSerializer
    permission_classes = perms(
        {
            "GET": "learning.curriculum.view",
            "POST": "learning.mastery.edit",
            "DELETE": "learning.mastery.edit",
        }
    )

    def get_tenant_queryset(self) -> QuerySet[LessonTopic]:
        from tutortrack.scheduling.models import LessonAttendee

        qs = selectors.lesson_topics(self.request.user)
        lesson = self.request.query_params.get("lesson")
        student = self.request.query_params.get("student")
        if lesson:
            qs = qs.filter(lesson_id=lesson)
        if student:
            qs = qs.filter(
                lesson_id__in=LessonAttendee.objects.filter(student_id=student).values("lesson_id")
            )
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("lesson", OpenApiTypes.UUID),
            OpenApiParameter("student", OpenApiTypes.UUID),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.TagLessonSerializer, responses={201: s.LessonTopicSerializer(many=True)}
    )
    def create(self, request: Request) -> Response:
        payload = s.TagLessonSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        rows = services.tag_lesson(
            payload.validated_data["lesson"], payload.validated_data["nodes"], user=request.user
        )
        return Response(
            s.LessonTopicSerializer(rows, many=True).data, status=status.HTTP_201_CREATED
        )

    def perform_destroy(self, instance: LessonTopic) -> None:
        services.untag_lesson(instance, user=self.request.user)


class MasteryViewSet(TenantScopedViewMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    model = TopicMastery
    serializer_class = s.MasterySerializer
    permission_classes = perms({"GET": "learning.curriculum.view", "POST": "learning.mastery.edit"})

    def get_tenant_queryset(self) -> QuerySet[TopicMastery]:
        qs = selectors.mastery(self.request.user)
        for key, field in (("student", "student_id"), ("curriculum", "node__curriculum_id")):
            value = self.request.query_params.get(key)
            if value:
                qs = qs.filter(**{field: value})
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("student", OpenApiTypes.UUID),
            OpenApiParameter("curriculum", OpenApiTypes.UUID),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.SetMasterySerializer,
        responses=s.MasterySerializer,
        examples=[
            OpenApiExample(
                "Secure",
                request_only=True,
                value={
                    "student": "0192f0c4-0000-7000-8000-000000000001",
                    "node": "0192f0c4-0000-7000-8000-000000000002",
                    "level": "secure",
                },
            )
        ],
    )
    def create(self, request: Request) -> Response:
        """Set a student's mastery of a topic (not started, learning, secure, mastered)."""
        payload = s.SetMasterySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        row = services.set_mastery(
            data["student"], data["node"], data["level"], user=request.user, notes=data.get("notes")
        )
        return Response(s.MasterySerializer(row).data)


def _student(request: Request, student_id: Any, codename: str) -> Student:
    student = get_object_or_404(Student.objects.all(), pk=student_id)
    if not selectors.can_see_student(request.user, student, codename):
        from tutortrack.core.exceptions import NotFound

        raise NotFound()
    return student


class CoverageView(APIView):
    permission_classes = perms({"GET": "learning.curriculum.view"})

    @extend_schema(
        responses=s.CoverageSerializer(many=True),
        parameters=[OpenApiParameter("curriculum", OpenApiTypes.UUID, many=True)],
    )
    def get(self, request: Request, student_id: Any) -> Response:
        """The student's topic heatmap: every curriculum they've covered (plus any asked
        for), units and topics with mastery and lessons covered."""
        student = _student(request, student_id, "learning.curriculum.view")
        ids = request.query_params.getlist("curriculum")
        return Response(s.CoverageSerializer(selectors.coverage(student, ids), many=True).data)


# --- goals and assessments (T04, T05) -----------------------------------------------------------


class GoalFilter(filters.FilterSet):
    student = filters.UUIDFilter()
    status = filters.ChoiceFilter(choices=Goal.Status.choices)

    class Meta:
        model = Goal
        fields: list[str] = []


class GoalViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Student goals (target grade, exam, SMART) with milestones; progress follows the
    milestones done, or the tutor sets it."""

    model = Goal
    serializer_class = s.GoalSerializer
    filterset_class = GoalFilter
    permission_classes = perms(crud("learning.goal.view", "learning.goal.manage"))
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Goal]:
        return selectors.goals(self.request.user)

    def _save(self, serializer: Any, goal: Goal | None) -> None:
        data = dict(serializer.validated_data)
        milestones = data.pop("milestones", None)
        serializer.instance = services.save_goal(
            goal,
            user=self.request.user,
            milestones=[dict(m) for m in milestones] if milestones is not None else None,
            **data,
        )

    @extend_schema(
        examples=[
            OpenApiExample(
                "Target grade",
                request_only=True,
                value={
                    "student": "0192f0c4-0000-7000-8000-000000000001",
                    "kind": "target_grade",
                    "title": "Grade 7 in GCSE Maths",
                    "target_grade": "7",
                    "exam_date": "2027-06-01",
                    "milestones": [{"title": "Grade 6 in the mock"}, {"title": "Algebra secure"}],
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        self._save(serializer, None)

    def perform_update(self, serializer: Any) -> None:
        self._save(serializer, serializer.instance)

    @extend_schema(request=s.GoalStatusSerializer, responses=s.GoalSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request: Request, pk: Any = None) -> Response:
        payload = s.GoalStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        goal = services.set_goal_status(
            self.get_object(), payload.validated_data["status"], user=request.user
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=goal.pk)).data)

    @extend_schema(request=s.MilestoneDoneSerializer, responses=s.GoalSerializer)
    @action(detail=True, methods=["post"])
    def milestone(self, request: Request, pk: Any = None) -> Response:
        payload = s.MilestoneDoneSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        goal = services.set_milestone_done(
            self.get_object(),
            payload.validated_data["milestone"],
            payload.validated_data["done"],
            user=request.user,
        )
        return Response(self.get_serializer(self.get_queryset().get(pk=goal.pk)).data)


ASSESSMENT = crud("learning.assessment.view", "learning.assessment.manage")


class AssessmentFilter(filters.FilterSet):
    kind = filters.ChoiceFilter(choices=Assessment.Kind.choices)
    subject = filters.UUIDFilter()

    class Meta:
        model = Assessment
        fields: list[str] = []


class AssessmentViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = Assessment
    serializer_class = s.AssessmentSerializer
    filterset_class = AssessmentFilter
    permission_classes = perms(ASSESSMENT)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Assessment]:
        return selectors.assessments(self.request.user).select_related("subject")

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_assessment(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_assessment(
            serializer.instance, **serializer.validated_data
        )


class ResultFilter(filters.FilterSet):
    student = filters.UUIDFilter()
    assessment = filters.UUIDFilter()

    class Meta:
        model = AssessmentResult
        fields: list[str] = []


class ResultViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Assessment results (score/max, grade, notes, attachment); the percentage is
    calculated."""

    model = AssessmentResult
    serializer_class = s.ResultSerializer
    filterset_class = ResultFilter
    permission_classes = perms(ASSESSMENT)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[AssessmentResult]:
        return selectors.results(self.request.user)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Mock exam result",
                request_only=True,
                value={
                    "assessment": "0192f0c4-0000-7000-8000-000000000001",
                    "student": "0192f0c4-0000-7000-8000-000000000002",
                    "score": "54",
                    "max_score": "80",
                    "grade": "6",
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.record_result(
            user=self.request.user, **serializer.validated_data
        )

    def perform_update(self, serializer: Any) -> None:
        current: AssessmentResult = serializer.instance
        data = {
            "assessment": current.assessment,
            "student": current.student,
            "score": current.score,
            "max_score": current.max_score,
            "grade": current.grade,
            "taken_on": current.taken_on,
            **serializer.validated_data,
        }
        serializer.instance = services.record_result(user=self.request.user, **data)

    def perform_destroy(self, instance: AssessmentResult) -> None:
        services.delete_result(instance, user=self.request.user)


class TrendView(APIView):
    permission_classes = perms({"GET": "learning.assessment.view"})

    @extend_schema(
        responses=s.TrendPointSerializer(many=True),
        parameters=[OpenApiParameter("subject", OpenApiTypes.UUID)],
    )
    def get(self, request: Request, student_id: Any) -> Response:
        """Score trend over time (results with a percentage), oldest first."""
        student = _student(request, student_id, "learning.assessment.view")
        qs = selectors.results(request.user).filter(student=student)
        rows = selectors.trend(qs, request.query_params.get("subject"))
        return Response(s.TrendPointSerializer(rows, many=True).data)


# --- progress reports (T06) ---------------------------------------------------------------------


class ProgressFilter(filters.FilterSet):
    student = filters.UUIDFilter()
    status = filters.MultipleChoiceFilter(choices=ProgressReport.Status.choices)
    period_end_after = filters.DateFilter(field_name="period_end", lookup_expr="gte")

    class Meta:
        model = ProgressReport
        fields: list[str] = []


class ProgressReportViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Progress reports: generated from attendance, lesson report highlights, topics,
    goals, assessments and homework; the tutor writes the summary; approval shares them
    with the family (portal and PDF by email)."""

    model = ProgressReport
    serializer_class = s.ProgressReportSerializer
    filterset_class = ProgressFilter
    permission_classes = perms(
        {
            "GET": "learning.progress.view",
            "POST": "learning.progress.write",
            "PATCH": "learning.progress.write",
        }
    )
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[ProgressReport]:
        return selectors.progress_reports(self.request.user)

    def _out(self, report: ProgressReport, code: int = status.HTTP_200_OK) -> Response:
        return Response(self.get_serializer(report).data, status=code)

    @extend_schema(request=s.ProgressCreateSerializer, responses={201: s.ProgressReportSerializer})
    def create(self, request: Request) -> Response:
        """Generate (or refresh the draft of) one student's report for a period."""
        payload = s.ProgressCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        report = services.generate_progress_report(data.pop("student"), user=request.user, **data)
        return self._out(report, status.HTTP_201_CREATED)

    @extend_schema(request=s.ProgressUpdateSerializer, responses=s.ProgressReportSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.ProgressUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        report = services.update_progress_report(
            self.get_object(), user=request.user, **payload.validated_data
        )
        return self._out(report)

    @extend_schema(
        request=s.ProgressGenerateSerializer,
        responses=s.ProgressGenerateResultSerializer,
        examples=[
            OpenApiExample(
                "Autumn term",
                request_only=True,
                value={
                    "period": "termly",
                    "period_start": "2026-09-01",
                    "period_end": "2026-12-18",
                },
            )
        ],
    )
    @action(detail=False, methods=["post"])
    def generate(self, request: Request) -> Response:
        """Draft reports for everyone with lessons in the period (or the students given)."""
        payload = s.ProgressGenerateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        result = services.generate_for_period(
            students=data.pop("students", None), user=request.user, **data
        )
        return Response(s.ProgressGenerateResultSerializer(result).data)

    @extend_schema(request=None, responses=s.ProgressReportSerializer)
    @action(detail=True, methods=["post"])
    def regenerate(self, request: Request, pk: Any = None) -> Response:
        report = self.get_object()
        report = services.generate_progress_report(
            report.student,
            period_start=report.period_start,
            period_end=report.period_end,
            period=report.period,
            user=request.user,
        )
        return self._out(report)

    @extend_schema(request=None, responses=s.ProgressReportSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.submit_progress_report(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.ProgressReportSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "learning.progress.approve"}),
    )
    def approve(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.approve_progress_report(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.ProgressReportSerializer)
    @action(
        detail=True,
        methods=["post"],
        permission_classes=perms({"POST": "learning.progress.approve"}),
    )
    def share(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.share_progress_report(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.ProgressReportSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request: Request, pk: Any = None) -> Response:
        return self._out(services.reopen_progress_report(self.get_object(), user=request.user))

    @extend_schema(request=None, responses=s.DraftSummarySerializer)
    @action(detail=True, methods=["post"], url_path="draft-summary")
    def draft_summary(self, request: Request, pk: Any = None) -> Response:
        """An AI draft of the summary comments (E31; 403 ``feature-disabled`` until it
        ships). The draft is returned, not saved."""
        return Response({"summary": progress.draft_summary(self.get_object())})

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, pk: Any = None) -> HttpResponse:
        report = self.get_object()
        return pdf_response(report)


def pdf_response(report: ProgressReport) -> HttpResponse:
    response = HttpResponse(progress.pdf(report), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="progress-report-{report.period_end.isoformat()}.pdf"'
    )
    return response


# --- library (T07) ------------------------------------------------------------------------------

LIBRARY = crud("learning.library.view", "learning.library.manage")


class ItemFilter(filters.FilterSet):
    kind = filters.ChoiceFilter(choices=LibraryItem.Kind.choices)
    archived = filters.BooleanFilter(field_name="archived_at", lookup_expr="isnull", exclude=True)
    q = filters.CharFilter(method="search")

    class Meta:
        model = LibraryItem
        fields: list[str] = []

    def search(self, qs: QuerySet[LibraryItem], name: str, value: str) -> QuerySet[LibraryItem]:
        return qs.filter(Q(name__icontains=value) | Q(identifier__icontains=value))


class LibraryItemViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    model = LibraryItem
    serializer_class = s.LibraryItemSerializer
    filterset_class = ItemFilter
    permission_classes = perms(LIBRARY)
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[LibraryItem]:
        return selectors.library_items(self.request.user)

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_item(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_item(serializer.instance, **serializer.validated_data)

    @extend_schema(request=s.LearningArchiveSerializer, responses=s.LibraryItemSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        payload = s.LearningArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        item = services.set_item_archived(self.get_object(), payload.validated_data["archived"])
        return Response(self.get_serializer(item).data)


class LoanFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Loan.Status.choices)
    student = filters.UUIDFilter()
    item = filters.UUIDFilter()
    overdue = filters.BooleanFilter(method="by_overdue")

    class Meta:
        model = Loan
        fields: list[str] = []

    def by_overdue(self, qs: QuerySet[Loan], name: str, value: bool) -> QuerySet[Loan]:
        late = Q(status=Loan.Status.OUT, due_date__lt=services.org_today())
        return qs.filter(late) if value else qs.exclude(late)


class LoanViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Loans: lend, return, extend, and lost (optionally charging the replacement cost
    as an ad hoc charge: send ``Idempotency-Key``)."""

    model = Loan
    serializer_class = s.LoanSerializer
    filterset_class = LoanFilter
    permission_classes = perms({"GET": "learning.library.view", "POST": "learning.library.manage"})

    def get_tenant_queryset(self) -> QuerySet[Loan]:
        return selectors.loans(self.request.user)

    @extend_schema(request=s.LoanCreateSerializer, responses={201: s.LoanSerializer})
    def create(self, request: Request) -> Response:
        payload = s.LoanCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        loan = services.lend(data.pop("item"), data.pop("student"), user=request.user, **data)
        return Response(self.get_serializer(loan).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.LoanReturnSerializer, responses=s.LoanSerializer)
    @action(detail=True, methods=["post"], url_path="return")
    def return_item(self, request: Request, pk: Any = None) -> Response:
        payload = s.LoanReturnSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        loan = services.return_loan(self.get_object(), **payload.validated_data)
        return Response(self.get_serializer(loan).data)

    @extend_schema(request=s.LoanExtendSerializer, responses=s.LoanSerializer)
    @action(detail=True, methods=["post"])
    def extend(self, request: Request, pk: Any = None) -> Response:
        payload = s.LoanExtendSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        loan = services.extend_loan(self.get_object(), payload.validated_data["due_date"])
        return Response(self.get_serializer(loan).data)

    @extend_schema(
        request=s.LoanLostSerializer,
        responses=s.LoanSerializer,
        examples=[
            OpenApiExample(
                "Lost, charge the replacement cost",
                request_only=True,
                value={"charge": True, "amount": {"amount": "12.99", "currency": "GBP"}},
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def lost(self, request: Request, pk: Any = None) -> Response:
        """Mark lost; with ``charge`` the family is billed (E10 ad hoc charge, once)."""
        payload = s.LoanLostSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if data["charge"] and not has_perm(request.user, "learning.library.charge"):
            raise PermissionDenied()
        loan = services.mark_lost(
            self.get_object(), charge=data["charge"], amount=data.get("amount"), user=request.user
        )
        return Response(self.get_serializer(loan).data)


# --- quizzes (T08) ------------------------------------------------------------------------------


class QuizViewSet(TenantScopedViewMixin, viewsets.ModelViewSet):
    """Built-in quizzes (multiple choice and short answer, auto-marked), set as homework
    (``submission_type=quiz``)."""

    model = Quiz
    serializer_class = s.QuizSerializer
    permission_classes = perms(crud("learning.quiz.view", "learning.quiz.manage"))
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_tenant_queryset(self) -> QuerySet[Quiz]:
        qs = selectors.quizzes(self.request.user)
        if self.request.query_params.get("archived") not in {"1", "true"}:
            qs = qs.filter(archived_at__isnull=True)
        return qs

    def _save(self, serializer: Any, quiz: Quiz | None) -> None:
        data = dict(serializer.validated_data)
        questions = data.pop("questions", None)
        serializer.instance = services.save_quiz(
            quiz,
            user=self.request.user,
            questions=[
                {**dict(q), "choices": [dict(c) for c in q.get("choices", [])]} for q in questions
            ]
            if questions is not None
            else None,
            **data,
        )

    @extend_schema(
        parameters=[OpenApiParameter("archived", OpenApiTypes.BOOL)],
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        examples=[
            OpenApiExample(
                "Two questions",
                request_only=True,
                value={
                    "title": "Fractions check",
                    "pass_percent": 60,
                    "questions": [
                        {
                            "kind": "single",
                            "prompt": "Which is equal to 1/2?",
                            "choices": [{"id": "a", "text": "2/4"}, {"id": "b", "text": "2/3"}],
                            "answer": ["a"],
                        },
                        {"kind": "short", "prompt": "Simplify 4/8", "answer": ["1/2"]},
                    ],
                },
            )
        ]
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer: Any) -> None:
        self._save(serializer, None)

    def perform_update(self, serializer: Any) -> None:
        self._save(serializer, serializer.instance)

    @extend_schema(request=s.LearningArchiveSerializer, responses=s.QuizSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        payload = s.LearningArchiveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        quiz = services.set_quiz_archived(self.get_object(), payload.validated_data["archived"])
        return Response(self.get_serializer(quiz).data)


class AttemptFilter(filters.FilterSet):
    quiz = filters.UUIDFilter()
    student = filters.UUIDFilter()

    class Meta:
        model = QuizAttempt
        fields: list[str] = []


class QuizAttemptViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    model = QuizAttempt
    serializer_class = s.QuizAttemptSerializer
    filterset_class = AttemptFilter
    permission_classes = perms({"GET": "learning.quiz.view"})

    def get_tenant_queryset(self) -> QuerySet[QuizAttempt]:
        return selectors.quiz_attempts(self.request.user)
