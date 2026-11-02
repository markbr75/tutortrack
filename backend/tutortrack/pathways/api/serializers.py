from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import PathwayRun, PathwayStep, PathwayTemplate
from ..pathway_steps import step_type


class PathwayTemplateSerializer(serializers.ModelSerializer):
    record_type = serializers.CharField(source="subject_type", max_length=40)
    version = serializers.SerializerMethodField()
    stages = serializers.JSONField()

    class Meta:
        model = PathwayTemplate
        fields = (
            "id", "key", "name", "description", "kind", "record_type", "active", "builtin_key",
            "edited", "version", "stages", "created_at", "updated_at",
        )  # fmt: skip
        read_only_fields = ("id", "key", "builtin_key", "edited", "created_at", "updated_at")

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_version(self, obj: PathwayTemplate) -> int | None:
        return obj.current_version.version if obj.current_version else None


class PathwayStepSerializer(serializers.ModelSerializer):
    step_type = serializers.CharField(source="type", read_only=True)
    completed_by = serializers.SerializerMethodField()
    config = serializers.JSONField(read_only=True)
    result = serializers.JSONField(read_only=True)

    class Meta:
        model = PathwayStep
        fields = (
            "id", "key", "stage", "name", "step_type", "assignee", "role", "status", "due_at",
            "opened_at", "submitted_at", "completed_at", "completed_by", "config", "result",
            "reason",
        )  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_completed_by(self, obj: PathwayStep) -> str | None:
        user = obj.completed_by
        return (user.get_full_name() or user.email) if user else None


class PathwayStageSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    gate = serializers.CharField()


class PathwayPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class PathwayRunSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)
    template_key = serializers.CharField(source="template.key", read_only=True)
    kind = serializers.CharField(source="template.kind", read_only=True)
    version = serializers.IntegerField(source="version.version", read_only=True)
    record_type = serializers.CharField(source="subject_type", read_only=True)
    record_id = serializers.CharField(source="subject_id", read_only=True)
    tutor = serializers.SerializerMethodField()
    stages = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    gates = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = PathwayRun
        fields: tuple[str, ...] = (
            "id", "template", "template_name", "template_key", "kind", "version", "record_type",
            "record_id", "tutor", "status", "stage", "stages", "gates", "progress", "started_at",
            "finished_at", "reason",
        )  # fmt: skip
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(PathwayPersonSerializer(allow_null=True))
    def get_tutor(self, obj: PathwayRun) -> dict[str, Any] | None:
        return {"id": obj.tutor.pk, "name": obj.tutor.full_name} if obj.tutor else None

    @extend_schema_field(PathwayStageSerializer(many=True))
    def get_stages(self, obj: PathwayRun) -> list[dict[str, Any]]:
        return [
            {"key": s["key"], "name": s["name"], "gate": s.get("gate", "")}
            for s in obj.version.stages
        ]

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_progress(self, obj: PathwayRun) -> dict[str, int]:
        steps = list(obj.steps.values_list("status", flat=True))
        finished = sum(1 for s in steps if s in ("done", "skipped"))
        return {"finished": finished, "total": len(steps)}


class PathwayRunDetailSerializer(PathwayRunSerializer):
    steps = PathwayStepSerializer(many=True, read_only=True)

    class Meta(PathwayRunSerializer.Meta):
        fields = (*PathwayRunSerializer.Meta.fields, "steps")
        read_only_fields = fields


class StartPathwaySerializer(serializers.Serializer):
    template = serializers.UUIDField()
    record_id = serializers.CharField(max_length=64)
    tutor = serializers.UUIDField()


class PathwayReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


class PathwayCompleteStepSerializer(serializers.Serializer):
    """What finishing a step sends; which fields apply depends on the step's type."""

    answers = serializers.DictField(required=False)  # questions
    files = serializers.ListField(child=serializers.UUIDField(), required=False)  # upload
    full_name = serializers.CharField(max_length=200, required=False)  # sign
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True)  # review

    def payload(self) -> dict[str, Any]:
        data = dict(self.validated_data)
        if "files" in data:
            data["files"] = [str(f) for f in data["files"]]
        return data


class MyPathwayTaskSerializer(serializers.ModelSerializer):
    run = serializers.UUIDField(source="run_id", read_only=True)
    pathway = serializers.CharField(source="run.template.name", read_only=True)
    step_type = serializers.CharField(source="type", read_only=True)
    view = serializers.SerializerMethodField()
    result = serializers.JSONField(read_only=True)

    class Meta:
        model = PathwayStep
        fields = (
            "id", "run", "pathway", "stage", "name", "step_type", "status", "due_at", "reason",
            "view", "result",
        )  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(serializers.DictField())
    def get_view(self, obj: PathwayStep) -> dict[str, Any]:
        kind = step_type(obj.type)
        return kind.view(obj) if kind else {}


class StepTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    assignees = serializers.ListField(child=serializers.CharField())


class RecordTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]


class PathwayQuestionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    record_type = serializers.CharField()


class PathwaySchemaSerializer(serializers.Serializer):
    step_types = StepTypeSerializer(many=True)
    record_types = RecordTypeSerializer(many=True)
    questions = PathwayQuestionSerializer(many=True)
    roles = serializers.ListField(child=serializers.CharField())
