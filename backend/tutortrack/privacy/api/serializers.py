"""Serializers for E29 Part 2: data subject requests, erasure, legal holds, retention,
safeguarding, lone working and the DPA."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from .. import dsar
from ..models import (
    DataSubjectRequest,
    DPAAcceptance,
    ErasureRecord,
    LegalHold,
    LoneWorkingVisit,
    RetentionPolicy,
    RetentionRun,
    SafeguardingAction,
    SafeguardingConcern,
    SafeguardingFlag,
)

# --- data subject requests ----------------------------------------------------------------------


class CheckSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    is_required = serializers.BooleanField()
    done = serializers.BooleanField()


class DataRequestSerializer(BaseModelSerializer):
    checklist = serializers.SerializerMethodField()
    has_draft = serializers.SerializerMethodField()
    has_package = serializers.SerializerMethodField()

    class Meta:
        model = DataSubjectRequest
        fields = [
            "id",
            "reference",
            "kind",
            "status",
            "channel",
            "subject_type",
            "subject_id",
            "subject_label",
            "requester_name",
            "requester_email",
            "relationship",
            "details",
            "received_at",
            "due_at",
            "extended_at",
            "extension_reason",
            "checklist",
            "verified_at",
            "verification_note",
            "summary",
            "redactions",
            "redactions_approved_at",
            "delivered_at",
            "link_expires_at",
            "downloaded_at",
            "download_count",
            "erasure_approved_at",
            "closed_at",
            "close_reason",
            "workflow_id",
            "has_draft",
            "has_package",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(CheckSerializer(many=True))
    def get_checklist(self, obj: DataSubjectRequest) -> list[dict[str, Any]]:
        required = dsar.required_checks(obj)
        keys = [k for k in dsar.CHECKS if k in required or obj.checks.get(k)]
        return [
            {
                "key": k,
                "title": str(dsar.CHECKS[k]),
                "is_required": k in required,
                "done": bool(obj.checks.get(k)),
            }
            for k in keys
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_has_draft(self, obj: DataSubjectRequest) -> bool:
        return obj.draft_file_id is not None

    @extend_schema_field(serializers.BooleanField())
    def get_has_package(self, obj: DataSubjectRequest) -> bool:
        return obj.package_file_id is not None


class DataRequestCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DataSubjectRequest.Kind.choices)
    subject_type = serializers.CharField(max_length=60)
    subject_id = serializers.CharField(max_length=64)
    requester_name = serializers.CharField(max_length=200)
    requester_email = serializers.EmailField(required=False, allow_blank=True)
    relationship = serializers.ChoiceField(
        choices=DataSubjectRequest.Relationship.choices, default="self"
    )
    channel = serializers.ChoiceField(choices=DataSubjectRequest.Channel.choices, default="email")
    details = serializers.CharField(required=False, allow_blank=True)
    received_at = serializers.DateTimeField(required=False)


class VerifySerializer(serializers.Serializer):
    checks = serializers.DictField(child=serializers.BooleanField())
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class DataRequestExtendSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=60)
    reason = serializers.CharField(max_length=500)


class PrivacyReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class RedactionSerializer(serializers.Serializer):
    section = serializers.CharField(required=False, allow_blank=True)
    record_id = serializers.CharField(required=False, allow_blank=True)
    record_field = serializers.CharField(required=False, allow_blank=True, source="field")
    file_id = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class RedactionsSerializer(serializers.Serializer):
    redactions = RedactionSerializer(many=True)


class PreviewSectionSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    provider = serializers.CharField()
    records = serializers.ListField(child=serializers.DictField())


class PreviewFileSerializer(serializers.Serializer):
    id = serializers.CharField()
    section = serializers.CharField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()


class ExportPreviewSerializer(serializers.Serializer):
    sections = PreviewSectionSerializer(many=True)
    files = PreviewFileSerializer(many=True)


class ErasureRecordSerializer(BaseModelSerializer):
    area_labels = serializers.SerializerMethodField(
        help_text="A readable name for each key of ``report`` (the area that was erased)."
    )

    class Meta:
        model = ErasureRecord
        fields = [
            "id",
            "request",
            "reason",
            "subject_type",
            "subject_id",
            "status",
            "subjects",
            "labels",
            "steps_done",
            "report",
            "area_labels",
            "financial_retained_until",
            "financial_erased_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_area_labels(self, obj: ErasureRecord) -> dict[str, str]:
        from ..selectors import erasure_area_labels

        return erasure_area_labels(obj.report or {})


class ErasurePreviewSerializer(serializers.Serializer):
    subjects = serializers.DictField(child=serializers.IntegerField())
    holds = serializers.ListField(child=serializers.DictField())
    providers = serializers.ListField(child=serializers.CharField())
    financial_retention_years = serializers.IntegerField()


class MyDataRequestSerializer(BaseModelSerializer):
    class Meta:
        model = DataSubjectRequest
        fields = [
            "id",
            "reference",
            "kind",
            "status",
            "received_at",
            "due_at",
            "delivered_at",
            "link_expires_at",
            "closed_at",
            "close_reason",
        ]
        read_only_fields = fields


class MyDataRequestCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DataSubjectRequest.Kind.choices)
    details = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    student_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="A parent asking on behalf of their child."
    )


# --- legal holds and retention ------------------------------------------------------------------


class LegalHoldSerializer(BaseModelSerializer):
    active = serializers.BooleanField(read_only=True)

    class Meta:
        model = LegalHold
        fields = [
            "id",
            "subject_type",
            "subject_id",
            "subject_label",
            "reason",
            "placed_by",
            "placed_at",
            "released_at",
            "released_by",
            "release_reason",
            "active",
        ]
        read_only_fields = [
            "id",
            "subject_label",
            "placed_by",
            "placed_at",
            "released_at",
            "released_by",
            "release_reason",
            "active",
        ]


class RetentionPolicySerializer(BaseModelSerializer):
    category_label = serializers.SerializerMethodField()

    class Meta:
        model = RetentionPolicy
        fields = ["id", "category", "category_label", "period_days", "enabled", "updated_at"]
        read_only_fields = ["id", "category", "category_label", "updated_at"]

    @extend_schema_field(serializers.CharField())
    def get_category_label(self, obj: RetentionPolicy) -> str:
        from ..registry import retention_category

        category = retention_category(obj.category)
        return str(category.label) if category else obj.category


class RetentionRunSerializer(BaseModelSerializer):
    area_labels = serializers.SerializerMethodField(
        help_text="A readable name for each key of ``report`` (the retention category)."
    )

    class Meta:
        model = RetentionRun
        fields = [
            "id",
            "dry_run",
            "status",
            "trigger",
            "report",
            "area_labels",
            "started_at",
            "finished_at",
            "requested_by",
            "workflow_id",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_area_labels(self, obj: RetentionRun) -> dict[str, str]:
        from ..selectors import retention_area_labels

        return retention_area_labels(obj.report or {})


class RetentionRunCreateSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=True)


# --- safeguarding -------------------------------------------------------------------------------


class SafeguardingActionSerializer(BaseModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = SafeguardingAction
        fields = ["id", "kind", "note", "actor", "actor_name", "occurred_at"]
        read_only_fields = ["id", "actor", "actor_name", "occurred_at"]

    @extend_schema_field(serializers.CharField())
    def get_actor_name(self, obj: SafeguardingAction) -> str:
        return (obj.actor.get_full_name() or obj.actor.email) if obj.actor else ""


class ConcernSerializer(BaseModelSerializer):
    """The full case (DSLs only)."""

    student_name = serializers.SerializerMethodField()
    raised_by_name = serializers.SerializerMethodField()
    actions = SafeguardingActionSerializer(many=True, read_only=True)
    attachment_ids = serializers.SerializerMethodField()

    class Meta:
        model = SafeguardingConcern
        fields = [
            "id",
            "reference",
            "student",
            "student_name",
            "lesson",
            "tutor",
            "category",
            "description",
            "immediate_risk",
            "status",
            "raised_by",
            "raised_by_name",
            "raised_at",
            "assigned_to",
            "outcome",
            "closed_at",
            "attachment_ids",
            "actions",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_student_name(self, obj: SafeguardingConcern) -> str:
        return obj.student.full_name if obj.student else ""

    @extend_schema_field(serializers.CharField())
    def get_raised_by_name(self, obj: SafeguardingConcern) -> str:
        return (obj.raised_by.get_full_name() or obj.raised_by.email) if obj.raised_by else ""

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_attachment_ids(self, obj: SafeguardingConcern) -> list[str]:
        return [str(f.pk) for f in obj.attachments.all()]


class ConcernListSerializer(BaseModelSerializer):
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = SafeguardingConcern
        fields = [
            "id",
            "reference",
            "student",
            "student_name",
            "category",
            "immediate_risk",
            "status",
            "raised_at",
            "assigned_to",
            "closed_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_student_name(self, obj: SafeguardingConcern) -> str:
        return obj.student.full_name if obj.student else ""


class RaisedConcernSerializer(BaseModelSerializer):
    """What the person who raised a concern sees: the reference and progress, not the case."""

    class Meta:
        model = SafeguardingConcern
        fields = ["id", "reference", "category", "immediate_risk", "status", "raised_at"]
        read_only_fields = fields


class RaiseConcernSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=SafeguardingConcern.Category.choices)
    description = serializers.CharField(max_length=20000)
    immediate_risk = serializers.BooleanField(default=False)
    student = serializers.UUIDField(required=False, allow_null=True)
    lesson = serializers.UUIDField(required=False, allow_null=True)
    tutor = serializers.UUIDField(required=False, allow_null=True)
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, max_length=10
    )


class UpdateConcernSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=SafeguardingConcern.Status.choices, required=False)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)
    outcome = serializers.CharField(required=False, allow_blank=True, max_length=20000)


class AddActionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SafeguardingAction.Kind.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=20000)


class CaseHistorySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    action = serializers.CharField()
    actor = serializers.CharField()


class SafeguardingFlagSerializer(BaseModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = SafeguardingFlag
        fields = [
            "id",
            "source_type",
            "source_id",
            "sender",
            "sender_name",
            "reasons",
            "keywords",
            "excerpt",
            "blocked",
            "status",
            "reviewed_by",
            "reviewed_at",
            "concern",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_sender_name(self, obj: SafeguardingFlag) -> str:
        return (obj.sender.get_full_name() or obj.sender.email) if obj.sender else ""


class ReviewSafeguardingFlagSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("dismiss", "dismiss"), ("escalate", "escalate")])
    note = serializers.CharField(required=False, allow_blank=True, max_length=5000)


# --- lone working -------------------------------------------------------------------------------


class VisitSerializer(BaseModelSerializer):
    tutor_name = serializers.SerializerMethodField()
    lesson_title = serializers.SerializerMethodField()

    class Meta:
        model = LoneWorkingVisit
        fields = [
            "id",
            "lesson",
            "lesson_title",
            "tutor",
            "tutor_name",
            "status",
            "checked_in_at",
            "expected_end",
            "checked_out_at",
            "alerted_at",
            "escalated_at",
            "resolved_at",
            "note",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_tutor_name(self, obj: LoneWorkingVisit) -> str:
        return str(obj.tutor.full_name)

    @extend_schema_field(serializers.CharField())
    def get_lesson_title(self, obj: LoneWorkingVisit) -> str:
        return str(obj.lesson.title)


class CheckInSerializer(serializers.Serializer):
    lesson = serializers.UUIDField()


class ResolveVisitSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500)


class ChildPrivacySerializer(serializers.Serializer):
    age = serializers.IntegerField(allow_null=True)
    is_child = serializers.BooleanField()
    high_privacy_defaults = serializers.BooleanField()
    coppa_applies = serializers.BooleanField()
    parental_consent = serializers.BooleanField()


# --- DPA and sub-processors ---------------------------------------------------------------------


class DPAAcceptanceSerializer(BaseModelSerializer):
    class Meta:
        model = DPAAcceptance
        fields = [
            "id",
            "version",
            "accepted_by",
            "signer_name",
            "signer_title",
            "company_name",
            "accepted_at",
        ]
        read_only_fields = fields


class DPAStatusSerializer(serializers.Serializer):
    version = serializers.CharField()
    effective = serializers.CharField()
    url = serializers.CharField()
    accepted = serializers.BooleanField()
    acceptance = DPAAcceptanceSerializer(allow_null=True)
    history = DPAAcceptanceSerializer(many=True)


class AcceptDPASerializer(serializers.Serializer):
    version = serializers.CharField(max_length=20)
    signer_name = serializers.CharField(max_length=200)
    signer_title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=200)


class SubprocessorSerializer(serializers.Serializer):
    name = serializers.CharField()
    purpose = serializers.CharField()
    data_categories = serializers.CharField()
    location = serializers.CharField()
    regions = serializers.ListField(child=serializers.CharField())
    optional = serializers.BooleanField()


class SubprocessorListSerializer(serializers.Serializer):
    version = serializers.CharField()
    subprocessors = SubprocessorSerializer(many=True)
