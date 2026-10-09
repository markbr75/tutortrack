from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpResponse
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import flags
from ..context import require_organisation_id
from ..models import AuditEntry, StoredFile
from ..permissions import HasOrganisation, HasPermission
from ..storage import services as storage
from .serializers import BaseModelSerializer
from .viewsets import TenantScopedViewMixin

# --- audit --------------------------------------------------------------------------------------


class AuditEntrySerializer(BaseModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "changes",
            "actor",
            "actor_email",
            "impersonator",
            "ip",
            "request_id",
            "created_at",
        ]
        read_only_fields = fields


class AuditEntryFilter(filters.FilterSet):
    """Global audit search (FR-29-2): by user, record, action, date and free text."""

    created_after = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lt")
    actor_email = filters.CharFilter(field_name="actor__email", lookup_expr="iexact")
    q = filters.CharFilter(method="search", label="Search the record description")

    class Meta:
        model = AuditEntry
        fields = ["object_type", "object_id", "actor", "action"]

    def search(self, queryset: QuerySet[AuditEntry], name: str, value: str) -> QuerySet[AuditEntry]:
        return queryset.filter(object_repr__icontains=value.strip()[:100])


EXPORT_LIMIT = 50_000
EXPORT_COLUMNS = [
    "created_at", "action", "object_type", "object_id", "object_repr", "actor_email",
    "impersonator", "ip", "request_id", "changes",
]  # fmt: skip


class AuditEntryViewSet(TenantScopedViewMixin, viewsets.ReadOnlyModelViewSet):
    """Audit history for the current organisation (append-only)."""

    model = AuditEntry
    serializer_class = AuditEntrySerializer
    permission_classes = [IsAuthenticated, HasOrganisation, HasPermission.for_("audit.view")]
    filterset_class = AuditEntryFilter

    def get_tenant_queryset(self) -> QuerySet[AuditEntry]:
        return AuditEntry.objects.filter(organisation_id=require_organisation_id()).select_related(
            "actor"
        )

    @extend_schema(
        parameters=[OpenApiParameter("q", str), OpenApiParameter("actor_email", str)],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsAuthenticated, HasOrganisation, HasPermission.for_("audit.export")],
    )
    def export(self, request: Request) -> HttpResponse:
        """CSV of the filtered audit log (max 50,000 rows). The export itself is audited and
        repeated exports alert the owners (FR-29-2)."""
        import csv
        import io
        import json

        from .. import audit as audit_log
        from ..security_alerts import check_mass_export

        rows = self.filter_queryset(self.get_queryset()).order_by("-created_at")[:EXPORT_LIMIT]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(EXPORT_COLUMNS)
        count = 0
        for entry in rows:
            count += 1
            writer.writerow(
                [
                    entry.created_at.isoformat(),
                    entry.action,
                    entry.object_type,
                    entry.object_id,
                    _csv_safe(entry.object_repr),
                    entry.actor.email if entry.actor else "",
                    entry.impersonator_id or "",
                    entry.ip or "",
                    entry.request_id,
                    json.dumps(entry.changes),
                ]
            )
        with transaction.atomic():
            organisation = request.organisation  # type: ignore[attr-defined]
            audit_log.record(
                organisation,
                "export",
                {"rows": [None, count], "filters": [None, dict(request.query_params)]},
                object_repr="audit log",
            )
            check_mass_export(request.user, organisation.pk)
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
        return response


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    return "'" + value if value[:1] in {"=", "+", "-", "@", "\t"} else value


# --- files --------------------------------------------------------------------------------------


class StoredFileSerializer(BaseModelSerializer):
    is_downloadable = serializers.BooleanField(read_only=True)

    class Meta:
        model = StoredFile
        fields = [
            "id",
            "filename",
            "content_type",
            "size_bytes",
            "status",
            "scan_status",
            "visibility",
            "is_downloadable",
            "created_at",
        ]
        read_only_fields = fields


class UploadRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
    visibility = serializers.ChoiceField(
        choices=StoredFile.Visibility.choices, default=StoredFile.Visibility.PRIVATE
    )


class PresignedUploadSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
    expires_in = serializers.IntegerField()


class DownloadSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_in = serializers.IntegerField()


class StoredFileViewSet(TenantScopedViewMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Direct-to-storage uploads: create -> PUT to ``upload.url`` -> complete -> download."""

    model = StoredFile
    serializer_class = StoredFileSerializer

    def get_tenant_queryset(self) -> QuerySet[StoredFile]:
        return StoredFile.objects.all()

    def get_object(self) -> StoredFile:
        stored: StoredFile = super().get_object()
        if not storage.can_access(self.request.user, stored):
            raise NotFound()  # don't reveal that the file exists
        return stored

    @extend_schema(
        request=UploadRequestSerializer,
        responses={
            201: inline_serializer(
                "FileUploadCreated",
                {"file": StoredFileSerializer(), "upload": PresignedUploadSerializer()},
            )
        },
    )
    @action(detail=False, methods=["post"], url_path="uploads")
    def create_upload(self, request: Request) -> Response:
        payload = UploadRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        stored, upload = storage.create_upload(**payload.validated_data)
        return Response(
            {
                "file": StoredFileSerializer(stored, context=self.get_serializer_context()).data,
                "upload": PresignedUploadSerializer(upload.__dict__).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=StoredFileSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk: Any = None) -> Response:
        stored = storage.complete_upload(self.get_object())
        return Response(self.get_serializer(stored).data)

    @extend_schema(responses=DownloadSerializer)
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: Any = None) -> Response:
        inline = request.query_params.get("inline") in {"1", "true"}
        url, expires = storage.download_url(request.user, self.get_object(), inline=inline)
        return Response({"url": url, "expires_in": expires})


# --- feature flags ------------------------------------------------------------------------------


class FeaturesView(APIView):
    """Feature flags as resolved for the current organisation (drives ``useFeature()``)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=inline_serializer(
            "Features", {"features": serializers.DictField(child=serializers.BooleanField())}
        )
    )
    def get(self, request: Request) -> Response:
        return Response({"features": flags.enabled_flags()})
