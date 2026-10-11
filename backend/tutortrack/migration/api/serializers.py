from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import ExportJob, ImportBatch, ImportRow, MigrationProject, SavedImportMapping, Source

PROJECT_SOURCES = [
    (Source.TUTORCRUNCHER.value, Source.TUTORCRUNCHER.label),
    (Source.TUTORBIRD.value, Source.TUTORBIRD.label),
    (Source.TEACHWORKS.value, Source.TEACHWORKS.label),
    (Source.CSV.value, Source.CSV.label),
]


class UserRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


def _user(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.pk, "name": user.get_full_name() or user.email}


# --- entities -----------------------------------------------------------------------------------


class ImportFieldSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    field_type = serializers.CharField()
    required = serializers.BooleanField()  # type: ignore[assignment]
    choices = serializers.ListField(child=serializers.CharField())
    help = serializers.CharField(allow_blank=True)


class ImportEntitySerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    description = serializers.CharField(allow_blank=True)
    field_specs = ImportFieldSerializer(many=True)
    upsert_keys = serializers.ListField(child=serializers.CharField())
    default_upsert = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())
    allowed = serializers.BooleanField()


class ImportCatalogueSerializer(serializers.Serializer):
    entities = ImportEntitySerializer(many=True)
    presets = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))


# --- batches ------------------------------------------------------------------------------------


class ImportBatchSerializer(BaseModelSerializer):
    origin = serializers.ChoiceField(source="source", choices=Source.choices, read_only=True)
    requested_by = serializers.SerializerMethodField()
    can_rollback = serializers.BooleanField(read_only=True)

    class Meta:
        model = ImportBatch
        fields = [
            "id",
            "entity",
            "origin",
            "preset",
            "filename",
            "sheet",
            "status",
            "stats",
            "error",
            "error_file",
            "project",
            "project_step",
            "requested_by",
            "created_at",
            "validated_at",
            "confirmed_at",
            "completed_at",
            "rollback_until",
            "rolled_back_at",
            "finalised_at",
            "can_rollback",
            "options",
        ]
        read_only_fields = fields

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_requested_by(self, obj: ImportBatch) -> dict[str, Any] | None:
        return _user(obj.requested_by)


class CreateImportSerializer(serializers.Serializer):
    file = serializers.UUIDField()
    entity = serializers.CharField(max_length=30)
    preset = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    sheet = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    options = serializers.DictField(required=False, default=dict)
    saved_mapping = serializers.UUIDField(required=False, allow_null=True)
    project = serializers.UUIDField(required=False, allow_null=True)
    project_step = serializers.CharField(
        max_length=30, required=False, allow_blank=True, default=""
    )


class GoogleSheetImportSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    entity = serializers.CharField(max_length=30)
    sheet = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    options = serializers.DictField(required=False, default=dict)
    saved_mapping = serializers.UUIDField(required=False, allow_null=True)


class ImportPreviewSerializer(serializers.Serializer):
    headers = serializers.ListField(child=serializers.CharField())
    column_map = serializers.DictField(child=serializers.CharField(allow_blank=True))
    value_map = serializers.DictField(child=serializers.DictField(child=serializers.CharField()))
    options = serializers.DictField()
    sample = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True))
    )
    distinct = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))
    field_specs = ImportFieldSerializer(many=True)
    upsert_keys = serializers.ListField(child=serializers.CharField())
    missing_required = serializers.ListField(child=serializers.CharField())


class UpdateMappingSerializer(serializers.Serializer):
    column_map = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False
    )
    value_map = serializers.DictField(
        child=serializers.DictField(child=serializers.CharField(allow_blank=True)), required=False
    )
    options = serializers.DictField(required=False)


class RowIssueSerializer(serializers.Serializer):
    field = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


class ImportRowSerializer(serializers.ModelSerializer):
    row_errors = RowIssueSerializer(source="errors", many=True, read_only=True)
    row_warnings = RowIssueSerializer(source="warnings", many=True, read_only=True)

    class Meta:
        model = ImportRow
        fields = [
            "id",
            "row_number",
            "raw",
            "values",
            "status",
            "action",
            "row_errors",
            "row_warnings",
            "target_type",
            "target_id",
            "applied_at",
        ]
        read_only_fields = fields


class SaveMappingSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)


class SavedImportMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedImportMapping
        fields = ["id", "name", "entity", "mapping", "value_map", "options", "created_at"]
        read_only_fields = fields


class DownloadLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()


# --- migration projects -------------------------------------------------------------------------


class MigrationProjectSerializer(BaseModelSerializer):
    origin = serializers.ChoiceField(source="source", choices=Source.choices, read_only=True)
    connection_name = serializers.SerializerMethodField()
    batches = serializers.SerializerMethodField()

    class Meta:
        model = MigrationProject
        fields = [
            "id",
            "name",
            "origin",
            "cutover_date",
            "status",
            "current_step",
            "steps",
            "source_totals",
            "reconciliation",
            "connection_name",
            "created_at",
            "completed_at",
            "batches",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_connection_name(self, obj: MigrationProject) -> str:
        return obj.connection.account_name if obj.connection_id else ""  # type: ignore[union-attr]

    @extend_schema_field(ImportBatchSerializer(many=True))
    def get_batches(self, obj: MigrationProject) -> list[dict[str, Any]]:
        return ImportBatchSerializer(obj.batches.order_by("created_at"), many=True).data  # type: ignore[return-value]


class CreateMigrationProjectSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    origin = serializers.ChoiceField(choices=PROJECT_SOURCES)
    cutover_date = serializers.DateField()
    api_key = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CompleteStepSerializer(serializers.Serializer):
    skip = serializers.BooleanField(default=False)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class InvitedSerializer(serializers.Serializer):
    sent = serializers.IntegerField()


# --- exports ------------------------------------------------------------------------------------


class ExportJobSerializer(BaseModelSerializer):
    requested_by = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "kind",
            "status",
            "reason",
            "requested_by",
            "progress",
            "size_bytes",
            "error",
            "created_at",
            "ready_at",
            "expires_at",
            "downloaded_at",
            "download_count",
        ]
        read_only_fields = fields

    @extend_schema_field(UserRefSerializer(allow_null=True))
    def get_requested_by(self, obj: ExportJob) -> dict[str, Any] | None:
        return _user(obj.requested_by)


class RequestExportSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ExportDownloadSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=200, style={"input_type": "password"})
