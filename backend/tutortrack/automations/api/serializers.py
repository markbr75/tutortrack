from __future__ import annotations

from rest_framework import serializers

from ..models import Automation, AutomationRun, AutomationRunStep


class AutomationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Automation
        fields = [
            "id",
            "name",
            "description",
            "trigger_type",
            "trigger_config",
            "subject_type",
            "conditions",
            "steps",
            "version",
            "enabled",
            "max_runs_per_record",
            "recipe_key",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["subject_type", "version", "recipe_key", "created_at", "updated_at"]


class AutomationWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    trigger_type = serializers.ChoiceField(choices=Automation.Trigger.choices)
    trigger_config = serializers.DictField()
    conditions = serializers.DictField(required=False, default=dict)
    steps = serializers.ListField(child=serializers.DictField())
    enabled = serializers.BooleanField(required=False, default=False)
    max_runs_per_record = serializers.IntegerField(min_value=1, max_value=50, default=1)


class AutomationPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    trigger_type = serializers.ChoiceField(choices=Automation.Trigger.choices, required=False)
    trigger_config = serializers.DictField(required=False)
    conditions = serializers.DictField(required=False)
    steps = serializers.ListField(child=serializers.DictField(), required=False)
    max_runs_per_record = serializers.IntegerField(min_value=1, max_value=50, required=False)


class RunStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationRunStep
        fields = ["step_key", "step_type", "status", "resume_at", "result", "error", "updated_at"]


class AutomationRunSerializer(serializers.ModelSerializer):
    automation_name = serializers.CharField(source="automation.name", read_only=True)
    version = serializers.IntegerField(source="version.version", read_only=True)

    class Meta:
        model = AutomationRun
        fields = [
            "id",
            "automation",
            "automation_name",
            "version",
            "subject_type",
            "subject_id",
            "event_type",
            "status",
            "started_at",
            "finished_at",
            "causation_depth",
            "attempts",
            "error",
        ]


class AutomationRunDetailSerializer(AutomationRunSerializer):
    steps = RunStepSerializer(many=True, read_only=True)

    class Meta(AutomationRunSerializer.Meta):
        fields = [*AutomationRunSerializer.Meta.fields, "steps"]


class DryRunRequestSerializer(serializers.Serializer):
    subject_id = serializers.CharField(max_length=64)


class DryRunStepSerializer(serializers.Serializer):
    key = serializers.CharField()
    type = serializers.CharField()
    description = serializers.CharField()
    ok = serializers.BooleanField()


class DryRunSerializer(serializers.Serializer):
    matched = serializers.BooleanField()
    record = serializers.DictField()
    steps = DryRunStepSerializer(many=True)


class ManualRunSerializer(serializers.Serializer):
    subject_ids = serializers.ListField(
        child=serializers.CharField(max_length=64), min_length=1, max_length=200
    )


class StartedSerializer(serializers.Serializer):
    started = serializers.IntegerField()


class RecipeSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    trigger_type = serializers.CharField()
    trigger_config = serializers.DictField()
    installed = serializers.BooleanField()


class SchemaFieldSerializer(serializers.Serializer):
    path = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.CharField()
    choices = serializers.ListField(child=serializers.CharField())


class SchemaSubjectSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    fields = SchemaFieldSerializer(many=True)  # type: ignore[assignment]
    recipients = serializers.ListField(child=serializers.CharField())
    setters = serializers.ListField(child=serializers.CharField())
    date_fields = serializers.ListField(child=serializers.CharField())
    taggable = serializers.BooleanField()


class SchemaTriggerSerializer(serializers.Serializer):
    event = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    subject = serializers.CharField()


class SchemaActionFieldSerializer(serializers.Serializer):
    name = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.CharField()
    required = serializers.BooleanField()  # type: ignore[assignment]
    choices = serializers.ListField(child=serializers.CharField())


class SchemaActionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    fields = SchemaActionFieldSerializer(many=True)  # type: ignore[assignment]
    subjects = serializers.ListField(child=serializers.CharField())
    permission = serializers.CharField(allow_blank=True)
    allowed = serializers.BooleanField()


class AutomationSchemaSerializer(serializers.Serializer):
    subjects = SchemaSubjectSerializer(many=True)
    triggers = SchemaTriggerSerializer(many=True)
    actions = SchemaActionSerializer(many=True)
    operators = serializers.ListField(child=serializers.CharField())
    predicates = serializers.DictField(child=serializers.CharField())
