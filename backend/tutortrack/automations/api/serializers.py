from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .. import builtin_workflows, services
from ..models import Automation, AutomationRun, AutomationRunStep


def builtin_default(builtin: builtin_workflows.BuiltinWorkflow) -> dict[str, Any]:
    return {
        "key": builtin.key,
        "version": builtin.version,
        "name": _(builtin.name),
        "description": _(builtin.description),
        "group": builtin.group,
        **builtin.definition(),
    }


class BuiltinInfoSerializer(serializers.Serializer):
    group = serializers.CharField(help_text="invoicing, lessons, sales or expiry.")
    group_label = serializers.CharField()
    latest_version = serializers.IntegerField(help_text="TutorTrack's current default version.")
    update_available = serializers.BooleanField(
        help_text="Edited, and TutorTrack has improved the default since."
    )
    can_switch_off = serializers.BooleanField()
    off_means = serializers.CharField(help_text="What happens instead while it's switched off.")


class AutomationSerializer(serializers.ModelSerializer):
    builtin = serializers.SerializerMethodField()
    runs_under_way = serializers.SerializerMethodField()

    @extend_schema_field(BuiltinInfoSerializer(allow_null=True))
    def get_builtin(self, obj: Automation) -> dict[str, Any] | None:
        found = builtin_workflows.builtin(obj.builtin_key) if obj.builtin_key else None
        if found is None:
            return None
        return {
            "group": found.group,
            "group_label": _(builtin_workflows.GROUPS[found.group]),
            "latest_version": found.version,
            "update_available": services.update_available(obj),
            "can_switch_off": found.can_switch_off,
            "off_means": _(found.off_means) if found.off_means else "",
        }

    def get_runs_under_way(self, obj: Automation) -> int:
        annotated = getattr(obj, "runs_under_way", None)
        if annotated is not None:
            return int(annotated)
        return obj.runs.filter(status__in=services.UNDER_WAY).count()

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
            "stop_when",
            "version",
            "enabled",
            "paused",
            "max_runs_per_record",
            "recipe_key",
            "kind",
            "builtin_key",
            "builtin_version",
            "edited",
            "builtin",
            "runs_under_way",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "subject_type", "version", "paused", "recipe_key", "kind", "builtin_key",
            "builtin_version", "edited", "created_at", "updated_at",
        ]  # fmt: skip


class BuiltinDefaultSerializer(serializers.Serializer):
    key = serializers.CharField()
    version = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField()
    group = serializers.CharField()
    trigger_type = serializers.CharField()
    trigger_config = serializers.DictField()
    conditions = serializers.DictField()
    steps = serializers.ListField(child=serializers.DictField())
    stop_when = serializers.ListField(child=serializers.CharField())


class BuiltinNoticeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    notice = serializers.ChoiceField(choices=["off", "update"])
    message = serializers.CharField(allow_blank=True, help_text="For off: what happens instead.")


class AutomationWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    trigger_type = serializers.ChoiceField(choices=Automation.Trigger.choices)
    trigger_config = serializers.DictField()
    conditions = serializers.DictField(required=False, default=dict)
    steps = serializers.ListField(child=serializers.DictField())
    stop_when = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        default=list,
        help_text="Events about the record that end a run early, e.g. invoice.paid.",
    )
    enabled = serializers.BooleanField(required=False, default=False)
    max_runs_per_record = serializers.IntegerField(min_value=1, max_value=50, default=1)


class AutomationPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    trigger_type = serializers.ChoiceField(choices=Automation.Trigger.choices, required=False)
    trigger_config = serializers.DictField(required=False)
    conditions = serializers.DictField(required=False)
    steps = serializers.ListField(child=serializers.DictField(), required=False)
    stop_when = serializers.ListField(child=serializers.CharField(max_length=80), required=False)
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
            "stop_reason",
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
    message = serializers.CharField(
        required=False, allow_blank=True,
        help_text="The notification it sends, whose wording is in Settings > Notifications.",
    )  # fmt: skip


class AutomationSchemaSerializer(serializers.Serializer):
    subjects = SchemaSubjectSerializer(many=True)
    triggers = SchemaTriggerSerializer(many=True)
    actions = SchemaActionSerializer(many=True)
    operators = serializers.ListField(child=serializers.CharField())
    predicates = serializers.DictField(child=serializers.CharField())


# --- E33 workflow schema ------------------------------------------------------------------------


class WorkflowQuestionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    subject = serializers.CharField()


class WorkflowDateFieldSerializer(serializers.Serializer):
    path = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.CharField()


class WorkflowStartDateSerializer(serializers.Serializer):
    field = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    type = serializers.CharField()


class WorkflowRecordTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    recipients = serializers.ListField(child=serializers.CharField())
    taggable = serializers.BooleanField()
    date_fields = WorkflowDateFieldSerializer(many=True)
    stop_when = serializers.ListField(
        child=serializers.CharField(), help_text="Events that can end a run for this record type."
    )
    start_dates = WorkflowStartDateSerializer(
        many=True, help_text="The record's dates a date start counts from."
    )


class WorkflowDateStartSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    subject = serializers.CharField()
    event = serializers.CharField(help_text="The event the run starts on.")
    date = serializers.CharField(help_text="The date its first wait counts from.")


class WorkflowScheduleStartSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    subject = serializers.CharField()
    config = serializers.DictField(help_text="The schedule's trigger_config.")


class WorkflowStartsSerializer(serializers.Serializer):
    events = SchemaTriggerSerializer(many=True)
    dates = WorkflowDateStartSerializer(many=True)
    schedules = WorkflowScheduleStartSerializer(many=True)
    frequencies = serializers.ListField(child=serializers.CharField())


class WorkflowSchemaSerializer(serializers.Serializer):
    record_types = WorkflowRecordTypeSerializer(many=True)
    starts = WorkflowStartsSerializer()
    questions = WorkflowQuestionSerializer(many=True)
    actions = SchemaActionSerializer(many=True)
