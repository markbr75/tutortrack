"""CRM API (E05 §4): custom fields, tags, notes, tasks, documents, saved views, timeline,
search and bulk actions."""

from __future__ import annotations

import dataclasses
from typing import Any

from django.db.models import Q, QuerySet
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import (
    HasMethodPermission,
    HasOrganisation,
    has_perm,
    scope_queryset,
)
from tutortrack.core.time import now

from .. import selectors, services, targets
from ..models import BulkJob, CustomFieldDefinition, Document, Note, SavedView, Tag, Task

AUTH = [IsAuthenticated, HasOrganisation]


def method_perms(mapping: dict[str, str]) -> list[Any]:
    return [*AUTH, HasMethodPermission.for_(mapping)]


def require_target(request: Request, target_type: str, target_id: str) -> None:
    if not targets.can_see(request.user, target_type, target_id):
        raise NotFound()


class TargetFilter(filters.FilterSet):
    target_type = filters.CharFilter()
    target_id = filters.CharFilter()


# --- custom fields ------------------------------------------------------------------------------


class CustomFieldSerializer(BaseModelSerializer):
    class Meta:
        model = CustomFieldDefinition
        fields = [
            "id",
            "entity_type",
            "key",
            "label",
            "type",
            "required",
            "options",
            "help_text",
            "visibility",
            "editable_by",
            "group",
            "order",
            "validation_regex",
            "active",
        ]
        read_only_fields = ["id"]


class CustomFieldFilter(filters.FilterSet):
    entity_type = filters.CharFilter()

    class Meta:
        model = CustomFieldDefinition
        fields: list[str] = []


class CustomFieldViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Custom field definitions per record type (FR-05-5). Deactivate instead of deleting."""

    model = CustomFieldDefinition
    serializer_class = CustomFieldSerializer
    filterset_class = CustomFieldFilter
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = method_perms({"GET": "org.settings.view", "*": "crm.customfield.manage"})

    def get_tenant_queryset(self) -> QuerySet[CustomFieldDefinition]:
        return CustomFieldDefinition.objects.all()

    def perform_create(self, serializer: Any) -> None:
        serializer.instance = services.save_custom_field(None, **serializer.validated_data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_custom_field(
            serializer.instance, **serializer.validated_data
        )


# --- tags ---------------------------------------------------------------------------------------


class TagSerializer(BaseModelSerializer):
    colour = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)

    class Meta:
        model = Tag
        fields = ["id", "name", "colour", "entity_types"]


class ApplyTagSerializer(serializers.Serializer):
    target_type = serializers.CharField()
    target_ids = serializers.ListField(child=serializers.CharField(), min_length=1, max_length=500)
    remove = serializers.BooleanField(default=False)


class ApplyTagResultSerializer(serializers.Serializer):
    changed = serializers.IntegerField()


class TagViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Organisation tags (FR-05-6). ``apply`` tags or untags many records at once."""

    model = Tag
    serializer_class = TagSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = method_perms({"GET": "crm.note.view", "*": "crm.tag.manage"})

    def get_tenant_queryset(self) -> QuerySet[Tag]:
        return Tag.objects.all()

    @extend_schema(request=ApplyTagSerializer, responses={200: ApplyTagResultSerializer})
    @action(
        detail=True, methods=["post"], permission_classes=method_perms({"POST": "crm.tag.apply"})
    )
    def apply(self, request: Request, pk: Any = None) -> Response:
        payload = ApplyTagSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        visible = targets.visible_ids(request.user, data["target_type"], data["target_ids"])
        count = services.apply_tag(
            self.get_object(), data["target_type"], sorted(visible), remove=data["remove"]
        )
        return Response({"changed": count})


# --- notes --------------------------------------------------------------------------------------


class NoteSerializer(BaseModelSerializer):
    class Meta:
        model = Note
        fields = [
            "id",
            "target_type",
            "target_id",
            "body",
            "pinned",
            "visibility",
            "mentions",
            "attachments",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "mentions", "created_by", "created_at", "updated_at"]


class NoteViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Notes on a record (``?target_type=&target_id=``). HTML is sanitised; mention staff with
    ``<span data-mention="<user id>">``. Visibility hides staff-only notes from tutors."""

    model = Note
    serializer_class = NoteSerializer
    filterset_class = type(
        "NoteFilter", (TargetFilter,), {"Meta": type("Meta", (), {"model": Note, "fields": []})}
    )
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = method_perms(
        {"GET": "crm.note.view", "POST": "crm.note.create", "*": "crm.note.edit"}
    )

    def get_tenant_queryset(self) -> QuerySet[Note]:
        qs = selectors.visible_notes(self.request.user)
        params = self.request.query_params
        if self.action == "list":
            if not params.get("target_type") or not params.get("target_id"):
                raise NotFound("Give target_type and target_id.")
            require_target(self.request, params["target_type"], params["target_id"])
        return qs

    def get_object(self) -> Note:
        note: Note = super().get_object()
        require_target(self.request, note.target_type, note.target_id)
        return note

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        require_target(self.request, data["target_type"], data["target_id"])
        if data.get("visibility") == Note.Visibility.STAFF and not has_perm(
            self.request.user, "crm.note.view_staff_only"
        ):
            data["visibility"] = Note.Visibility.TUTORS
        serializer.instance = services.create_note(**data)

    def perform_update(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        data.pop("target_type", None)
        data.pop("target_id", None)
        serializer.instance = services.update_note(serializer.instance, **data)

    def perform_destroy(self, instance: Note) -> None:
        from tutortrack.core import audit

        audit.record(instance, "delete")
        instance.delete()


# --- tasks --------------------------------------------------------------------------------------


class TaskSerializer(BaseModelSerializer):
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "due_at",
            "assignee",
            "priority",
            "status",
            "completed_at",
            "target_type",
            "target_id",
            "remind_at",
            "is_overdue",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "completed_at", "created_by", "created_at"]

    def get_is_overdue(self, obj: Task) -> bool:
        return obj.status == Task.Status.OPEN and obj.due_at is not None and obj.due_at < now()


class TaskFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=Task.Status.choices)
    target_type = filters.CharFilter()
    target_id = filters.CharFilter()
    mine = filters.BooleanFilter(method="only_mine", label="Only tasks assigned to me")
    overdue = filters.BooleanFilter(method="only_overdue")

    class Meta:
        model = Task
        fields: list[str] = []

    def only_mine(self, qs: QuerySet[Task], name: str, value: bool) -> QuerySet[Task]:
        return qs.filter(assignee=self.request.user) if value else qs

    def only_overdue(self, qs: QuerySet[Task], name: str, value: bool) -> QuerySet[Task]:
        return qs.filter(status=Task.Status.OPEN, due_at__lt=now()) if value else qs


class TaskViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Tasks (FR-05-8). ``?mine=true`` is "My tasks"; ``?overdue=true`` the overdue badge."""

    model = Task
    serializer_class = TaskSerializer
    filterset_class = TaskFilter
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_classes = method_perms(
        {"GET": "crm.task.view", "POST": "crm.task.create", "PATCH": "crm.task.edit"}
    )

    def get_tenant_queryset(self) -> QuerySet[Task]:
        return scope_queryset(self.request.user, Task.objects.all(), "crm.task.view")

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        if data.get("target_type"):
            require_target(self.request, data["target_type"], data.get("target_id", ""))
        serializer.instance = services.create_task(**data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.update_task(
            serializer.instance, **dict(serializer.validated_data)
        )


# --- documents ----------------------------------------------------------------------------------


class DocumentSerializer(BaseModelSerializer):
    filename = serializers.CharField(source="file.filename", read_only=True)

    class Meta:
        model = Document
        fields = [
            "id",
            "target_type",
            "target_id",
            "file",
            "filename",
            "title",
            "category",
            "visibility",
            "expires_on",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "filename", "created_by", "created_at"]
        extra_kwargs = {"title": {"required": False}}


class DocumentViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Documents on a record (FR-05-9): upload via ``/files/uploads``, then attach here.
    Download through ``/files/{id}/download``."""

    model = Document
    serializer_class = DocumentSerializer
    filterset_class = type(
        "DocumentFilter",
        (TargetFilter,),
        {"Meta": type("Meta", (), {"model": Document, "fields": []})},
    )
    permission_classes = method_perms(
        {"GET": "crm.document.view", "POST": "crm.document.create", "DELETE": "crm.document.delete"}
    )

    def get_tenant_queryset(self) -> QuerySet[Document]:
        qs = Document.objects.select_related("file")
        if not has_perm(self.request.user, "crm.note.view_staff_only"):
            qs = qs.exclude(visibility=Note.Visibility.STAFF)
        params = self.request.query_params
        if self.action == "list":
            if not params.get("target_type") or not params.get("target_id"):
                raise NotFound("Give target_type and target_id.")
            require_target(self.request, params["target_type"], params["target_id"])
        return qs

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        require_target(self.request, data["target_type"], data["target_id"])
        serializer.instance = services.attach_document(**data)


# --- saved views ----------------------------------------------------------------------------------


class SavedViewSerializer(BaseModelSerializer):
    class Meta:
        model = SavedView
        fields = [
            "id",
            "entity_type",
            "name",
            "shared",
            "filters",
            "columns",
            "ordering",
            "owner",
            "created_at",
        ]
        read_only_fields = ["id", "owner", "created_at"]


class SavedViewViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Your saved list views and the ones shared with the team (FR-05-11)."""

    model = SavedView
    serializer_class = SavedViewSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_class = type(
        "SavedViewFilter",
        (filters.FilterSet,),
        {
            "entity_type": filters.CharFilter(),
            "Meta": type("Meta", (), {"model": SavedView, "fields": []}),
        },
    )

    def get_tenant_queryset(self) -> QuerySet[SavedView]:
        qs = SavedView.objects.filter(Q(owner=self.request.user) | Q(shared=True))
        if self.action in {"partial_update", "destroy"}:
            qs = qs.filter(owner=self.request.user)
        return qs

    def perform_create(self, serializer: Any) -> None:
        data = dict(serializer.validated_data)
        if data.get("shared") and not has_perm(self.request.user, "crm.savedview.share"):
            data["shared"] = False
        serializer.instance = services.save_view(None, owner=self.request.user, **data)

    def perform_update(self, serializer: Any) -> None:
        serializer.instance = services.save_view(
            serializer.instance, owner=self.request.user, **dict(serializer.validated_data)
        )


# --- timeline, search, bulk ---------------------------------------------------------------------


class TimelineItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["note", "task", "document", "change"])
    id = serializers.CharField()
    at = serializers.DateTimeField()
    title = serializers.CharField()
    body = serializers.CharField()
    actor_id = serializers.CharField(allow_null=True)


class TimelineView(APIView):
    """Activity feed for one record (FR-05-10), newest first. ``?kinds=note,task``."""

    permission_classes = AUTH

    @extend_schema(
        parameters=[
            OpenApiParameter("target_type", str, required=True),
            OpenApiParameter("target_id", str, required=True),
            OpenApiParameter("kinds", str),
        ],
        responses=TimelineItemSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        target_type = request.query_params.get("target_type", "")
        target_id = request.query_params.get("target_id", "")
        require_target(request, target_type, target_id)
        kinds = {k for k in request.query_params.get("kinds", "").split(",") if k} or None
        items = selectors.timeline(request.user, target_type, target_id, kinds)
        return Response(
            TimelineItemSerializer([dataclasses.asdict(i) for i in items], many=True).data
        )


class SearchHitSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    score = serializers.FloatField()
    client_id = serializers.CharField(allow_null=True)


class SearchView(APIView):
    """Global search (⌘K) across people; results respect your permissions."""

    permission_classes = AUTH

    @extend_schema(
        parameters=[OpenApiParameter("q", str, required=True)],
        responses=SearchHitSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        hits = selectors.search(request.user, request.query_params.get("q", ""))
        return Response(SearchHitSerializer([dataclasses.asdict(h) for h in hits], many=True).data)


class BulkJobSerializer(BaseModelSerializer):
    class Meta:
        model = BulkJob
        fields = [
            "id",
            "entity_type",
            "action",
            "params",
            "status",
            "total",
            "processed",
            "succeeded",
            "errors",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields


class StartBulkSerializer(serializers.Serializer):
    target_ids = serializers.ListField(child=serializers.CharField(), min_length=1, max_length=5000)
    params = serializers.DictField(required=False, default=dict)


class BulkView(APIView):
    """Run a bulk action in the background: ``POST /bulk/{entity}/{action}``; poll
    ``/bulk-jobs/{id}`` for progress and the per-record report (FR-05-12)."""

    permission_classes = method_perms({"POST": "crm.bulk.run"})

    @extend_schema(request=StartBulkSerializer, responses={202: BulkJobSerializer})
    def post(self, request: Request, entity: str, bulk_action: str) -> Response:
        payload = StartBulkSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        entity_type = f"people.{entity}"
        edit_perm = f"people.{entity}.{'archive' if bulk_action == 'archive' else 'edit'}"
        if bulk_action in {"tag", "untag"}:
            edit_perm = "crm.tag.apply"
        if not has_perm(request.user, edit_perm):
            from tutortrack.core.exceptions import PermissionDenied

            raise PermissionDenied()
        job = services.start_bulk_job(
            entity_type=entity_type,
            action=bulk_action,
            user=request.user,
            target_ids=payload.validated_data["target_ids"],
            params=payload.validated_data["params"],
        )
        return Response(BulkJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


class BulkJobViewSet(
    TenantScopedViewMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    model = BulkJob
    serializer_class = BulkJobSerializer
    permission_classes = method_perms({"GET": "crm.bulk.run"})

    def get_tenant_queryset(self) -> QuerySet[BulkJob]:
        return BulkJob.objects.filter(requested_by=self.request.user)
