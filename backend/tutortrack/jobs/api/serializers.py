from __future__ import annotations

from rest_framework import serializers

from tutortrack.catalogue.models import Service
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.people.models import Client, Student, TutorProfile

from ..models import Job, JobStatusHistory, JobStudent, JobTutor

RATE = {"decimal_places": 4, "required": False, "allow_null": True}


class JobStudentSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = JobStudent
        fields = [
            "id",
            "student",
            "student_name",
            "charge_rate_override",
            "active_from",
            "active_to",
        ]
        read_only_fields = ["id", "student", "active_from", "active_to"]
        field_permissions = {"charge_rate_override": "billing.rates.view_charge"}


class JobTutorSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)

    class Meta:
        model = JobTutor
        fields = [
            "id", "tutor", "tutor_name", "role", "status", "pay_rate_override", "start_date",
            "end_date", "responded_at",
        ]  # fmt: skip
        read_only_fields = ["id", "tutor", "status", "start_date", "end_date", "responded_at"]
        field_permissions = {"pay_rate_override": "billing.rates.view_pay"}


class StudentInput(serializers.Serializer):
    student = TenantRelatedField(Student)
    charge_rate_override = MoneySerializerField(**RATE)


class TutorInput(serializers.Serializer):
    tutor = TenantRelatedField(TutorProfile)
    role = serializers.ChoiceField(choices=JobTutor.Role.choices, default=JobTutor.Role.LEAD)
    pay_rate_override = MoneySerializerField(**RATE)
    start_date = serializers.DateField(required=False, allow_null=True)
    offer = serializers.BooleanField(default=False, help_text="Offer the job; the tutor accepts.")


class ScheduleSlot(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6, help_text="Monday is 0.")
    time = serializers.RegexField(r"^([01]\d|2[0-3]):[0-5]\d$")
    duration_minutes = serializers.IntegerField(min_value=5, max_value=600, required=False)


class JobSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    students = JobStudentSerializer(many=True, read_only=True)
    tutors = JobTutorSerializer(many=True, read_only=True)
    default_schedule = ScheduleSlot(many=True, required=False)

    class Meta:
        model = Job
        fields = [
            "id", "reference", "name", "client", "client_name", "bill_to", "service",
            "service_name", "subject", "level", "branch", "status", "status_changed_at",
            "currency", "charge_rate", "billing_method", "package_template", "po_number",
            "default_duration_minutes", "location", "online", "meeting_provider",
            "default_schedule", "start_date", "expected_end_date", "lessons_per_week",
            "expected_total_hours", "goals", "notes_internal", "notes_for_tutor",
            "notes_for_client", "account_manager", "hours_cap", "hours_cap_period",
            "policy_overrides", "custom_fields", "students", "tutors", "created_at",
        ]  # fmt: skip
        read_only_fields = [
            "id", "reference", "client", "service", "status", "status_changed_at", "currency",
            "created_at",
        ]  # fmt: skip
        field_permissions = {
            "charge_rate": "billing.rates.view_charge",
            "notes_internal": "jobs.job.edit",
            "bill_to": "jobs.job.edit",
            "po_number": "jobs.job.edit",
            "policy_overrides": "jobs.job.edit",
        }
        extra_kwargs = {"name": {"required": False}, "branch": {"required": False}}


class JobCreateSerializer(JobSerializer):
    student_inputs = StudentInput(many=True, write_only=True, source="students_in")
    tutor_inputs = TutorInput(many=True, write_only=True, required=False, source="tutors_in")
    client = TenantRelatedField(Client)
    service = TenantRelatedField(Service, filter={"active": True})
    status = serializers.ChoiceField(
        choices=[Job.Status.DRAFT, Job.Status.SEEKING_TUTOR, Job.Status.ACTIVE],
        default=Job.Status.DRAFT,
    )

    class Meta(JobSerializer.Meta):
        fields = [*JobSerializer.Meta.fields, "student_inputs", "tutor_inputs"]
        read_only_fields = ["id", "reference", "status_changed_at", "currency", "created_at"]


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Job.Status.choices)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    future_lessons = serializers.ChoiceField(choices=["keep", "cancel"], default="keep")


class StatusHistorySerializer(BaseModelSerializer):
    class Meta:
        model = JobStatusHistory
        fields = ["from_status", "to_status", "reason", "created_by", "created_at"]


class StudentRateSerializer(serializers.Serializer):
    charge_rate_override = MoneySerializerField(decimal_places=4, allow_null=True)


class TutorRateSerializer(serializers.Serializer):
    pay_rate_override = MoneySerializerField(decimal_places=4, allow_null=True)


class EndSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class ReplaceSerializer(serializers.Serializer):
    tutor = TenantRelatedField(TutorProfile)
    effective_date = serializers.DateField()
    pay_rate_override = MoneySerializerField(**RATE)
    dry_run = serializers.BooleanField(default=False)


class AffectedLessonSerializer(serializers.Serializer):
    id = serializers.CharField()
    starts_at = serializers.DateTimeField()
    conflict = serializers.CharField(allow_blank=True)


class ReplacementSerializer(serializers.Serializer):
    lessons = AffectedLessonSerializer(many=True)
    conflicts = serializers.IntegerField()
    new_assignment = JobTutorSerializer(allow_null=True)


class EconomicsSerializer(serializers.Serializer):
    charge = MoneyOut()
    pay = MoneyOut(required=False)
    margin = MoneyOut(required=False)
    margin_percent = serializers.CharField(allow_null=True, required=False)


class JobSummarySerializer(serializers.Serializer):
    per_lesson = EconomicsSerializer(allow_null=True)
    trace = serializers.ListField(child=serializers.CharField())
    lessons_planned = serializers.IntegerField()
    lessons_completed = serializers.IntegerField()
    hours_delivered = serializers.CharField()
    delivered = EconomicsSerializer(allow_null=True)
    next_lesson_at = serializers.DateTimeField(allow_null=True)
    last_lesson_at = serializers.DateTimeField(allow_null=True)


class HoursCheckSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=["none", "ok", "warning", "blocked"])
    used = serializers.CharField()
    cap = serializers.CharField(allow_null=True)
    period_start = serializers.DateField(allow_null=True)
    period_end = serializers.DateField(allow_null=True)


class QuickSetupSerializer(serializers.Serializer):
    student = TenantRelatedField(Student)
    service = TenantRelatedField(Service, filter={"active": True})
    tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    charge_rate = MoneySerializerField(**RATE)
    pay_rate = MoneySerializerField(**RATE)
    schedule = ScheduleSlot(many=True, required=False)
    start_date = serializers.DateField(required=False)
    default_duration_minutes = serializers.IntegerField(min_value=5, max_value=600, required=False)
