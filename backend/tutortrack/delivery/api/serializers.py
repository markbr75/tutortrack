from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.catalogue.models import Service, Subject
from tutortrack.core.api.serializers import BaseModelSerializer, TenantRelatedField
from tutortrack.core.time import now
from tutortrack.jobs.models import Job
from tutortrack.scheduling.models import Lesson

from .. import templates
from ..models import (
    CancellationPolicy,
    LessonReport,
    LessonReportComment,
    MakeupCredit,
    ReportTemplate,
)


class PercentPairSerializer(serializers.Serializer):
    charge_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )
    pay_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100
    )


class MakeupRulesSerializer(serializers.Serializer):
    on_free_cancellation = serializers.BooleanField()
    on_tutor_cancellation = serializers.BooleanField()
    valid_days = serializers.IntegerField(min_value=1, max_value=730)


class PolicyRulesSerializer(serializers.Serializer):
    """All keys optional on input (defaults fill the gaps); complete on output."""

    free_window_hours = serializers.IntegerField(min_value=0, max_value=720, required=False)
    late_cancellation = PercentPairSerializer(required=False)
    no_show = PercentPairSerializer(required=False)
    absent_notified = PercentPairSerializer(required=False)
    late = PercentPairSerializer(required=False)
    tutor_cancellation = PercentPairSerializer(required=False)
    admin_cancellation = PercentPairSerializer(required=False)
    max_free_per_month = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    makeup_credit = MakeupRulesSerializer(required=False)


class CancellationPolicySerializer(BaseModelSerializer):
    rules = PolicyRulesSerializer()

    class Meta:
        model = CancellationPolicy
        fields = ["id", "name", "scope_type", "scope_id", "rules", "version", "created_at"]
        read_only_fields = ["id", "version", "created_at"]

    def to_internal_value(self, data: Any) -> Any:
        value = super().to_internal_value(data)
        raw = data.get("rules") if isinstance(data, dict) else None
        value["rules"] = raw if isinstance(raw, dict) else {}
        return value


class TemplateFieldSerializer(serializers.Serializer):
    key = serializers.RegexField(r"^[a-z][a-z0-9_]{0,39}$")
    label = serializers.CharField(max_length=200)  # type: ignore[assignment]
    type = serializers.ChoiceField(choices=templates.FIELD_TYPES)
    required = serializers.BooleanField(default=False)  # type: ignore[assignment]
    visibility = serializers.ChoiceField(choices=templates.VISIBILITY, default="client")
    options = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, max_length=50
    )
    help_text = serializers.CharField(  # type: ignore[assignment]
        max_length=300, required=False, allow_blank=True
    )


class ReportTemplateSerializer(BaseModelSerializer):
    fields = TemplateFieldSerializer(  # type: ignore[assignment]
        many=True, source="current_version.fields"
    )
    version = serializers.IntegerField(source="current_version.version", read_only=True)
    services = TenantRelatedField(Service, many=True, required=False)
    subjects = TenantRelatedField(Subject, many=True, required=False)
    jobs = TenantRelatedField(Job, many=True, required=False)

    class Meta:
        model = ReportTemplate
        fields = [
            "id",
            "name",
            "description",
            "is_default",
            "fields",
            "version",
            "services",
            "subjects",
            "jobs",
            "archived_at",
        ]
        read_only_fields = ["id", "version", "archived_at"]


class StudentRef(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


SLA_STATES = ["due", "overdue", "submitted", "approved", "shared"]


class LessonReportSerializer(BaseModelSerializer):
    lesson_title = serializers.CharField(source="lesson.title", read_only=True)
    lesson_start = serializers.DateTimeField(source="lesson.start", read_only=True)
    lesson_end = serializers.DateTimeField(source="lesson.end", read_only=True)
    lesson_status = serializers.CharField(source="lesson.status", read_only=True)
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    template_name = serializers.CharField(source="template_version.template.name", read_only=True)
    template_version_number = serializers.IntegerField(
        source="template_version.version", read_only=True
    )
    template_fields = serializers.SerializerMethodField()
    answers = serializers.SerializerMethodField()
    sla_state = serializers.SerializerMethodField()
    students = serializers.SerializerMethodField()

    class Meta:
        model = LessonReport
        fields = [
            "id",
            "lesson",
            "lesson_title",
            "lesson_start",
            "lesson_end",
            "lesson_status",
            "tutor",
            "tutor_name",
            "students",
            "status",
            "sla_state",
            "due_at",
            "submitted_at",
            "approved_at",
            "shared_at",
            "overdue_at",
            "escalated_at",
            "pay_held",
            "returned_note",
            "template_name",
            "template_version_number",
            "template_fields",
            "answers",
            "updated_at",
        ]
        read_only_fields = fields

    def _audience(self) -> str:
        return str(self.context.get("audience", "staff"))

    @extend_schema_field(TemplateFieldSerializer(many=True))
    def get_template_fields(self, obj: LessonReport) -> list[dict[str, Any]]:
        allowed = templates.AUDIENCE_FIELDS[self._audience()]
        return [f for f in obj.template_version.fields if f.get("visibility") in allowed]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_answers(self, obj: LessonReport) -> dict[str, Any]:
        return templates.visible_answers(
            obj.template_version.fields, obj.answers or {}, self._audience()
        )

    @extend_schema_field(serializers.ChoiceField(choices=SLA_STATES))
    def get_sla_state(self, obj: LessonReport) -> str:
        return obj.sla_state(now())

    @extend_schema_field(StudentRef(many=True))
    def get_students(self, obj: LessonReport) -> list[dict[str, str]]:
        return [
            {"id": str(a.student_id), "name": a.student.full_name}
            for a in obj.lesson.attendees.all()
        ]


class ReportAnswersSerializer(serializers.Serializer):
    answers = serializers.DictField()


class ReportSubmitSerializer(serializers.Serializer):
    answers = serializers.DictField(required=False)


class ReportReturnSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class ReportOpenSerializer(serializers.Serializer):
    tutor = serializers.UUIDField(required=False, help_text="Defaults to you (tutors).")


class ReportCommentSerializer(BaseModelSerializer):
    class Meta:
        model = LessonReportComment
        fields = ["id", "author_name", "body", "visibility", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]


class MakeupCreditSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    source_lesson_title = serializers.CharField(source="source_lesson.title", read_only=True)
    source_lesson_start = serializers.DateTimeField(source="source_lesson.start", read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = MakeupCredit
        fields = [
            "id",
            "student",
            "student_name",
            "client",
            "source_lesson",
            "source_lesson_title",
            "source_lesson_start",
            "expires_at",
            "consumed_by_lesson",
            "consumed_at",
            "status",
            "note",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=MakeupCredit.Status.choices))
    def get_status(self, obj: MakeupCredit) -> str:
        return obj.status_at(now())


class ConsumeSerializer(serializers.Serializer):
    lesson = TenantRelatedField(Lesson)


class ExtendSerializer(serializers.Serializer):
    until = serializers.DateTimeField()


class VoidSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class NudgeSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=200)


class NudgeResultSerializer(serializers.Serializer):
    nudged = serializers.IntegerField()


class AttendanceStatsSerializer(serializers.Serializer):
    lessons = serializers.IntegerField()
    attended = serializers.IntegerField()
    rate_percent = serializers.DecimalField(max_digits=5, decimal_places=1)
    streak = serializers.IntegerField()
    by_outcome = serializers.DictField(child=serializers.IntegerField())
