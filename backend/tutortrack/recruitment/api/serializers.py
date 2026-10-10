from __future__ import annotations

from typing import Any

from rest_framework import serializers

from ..models import (
    ApplicationStage,
    ChecklistTemplate,
    ComplianceRecord,
    Interview,
    JobOpening,
    ReferenceRequest,
    RequirementType,
    Scorecard,
    TutorApplication,
)


class JobOpeningSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOpening
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "subjects",
            "location",
            "branch",
            "form",
            "published",
            "closes_on",
        ]


class ApplicationStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationStage
        fields = ["id", "name", "order", "kind", "criteria", "reminder_days"]


class ScorecardSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField()
    stage_name = serializers.CharField(source="stage.name", read_only=True)

    class Meta:
        model = Scorecard
        fields = [
            "id",
            "stage",
            "stage_name",
            "reviewer_name",
            "scores",
            "recommendation",
            "notes",
            "created_at",
        ]

    def get_reviewer_name(self, obj: Scorecard) -> str:
        return obj.reviewer.get_full_name() or obj.reviewer.email


class ReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferenceRequest
        fields = [
            "id",
            "referee_name",
            "referee_email",
            "relationship",
            "status",
            "responses",
            "rating",
            "concerns",
            "received_at",
            "created_at",
        ]


class InterviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Interview
        fields = ["id", "interviewer", "options", "minutes", "meeting_url", "start", "status"]


class ApplicationSerializer(serializers.ModelSerializer):
    stage_name = serializers.CharField(source="stage.name", read_only=True)
    opening_title = serializers.CharField(source="opening.title", read_only=True, default="")
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = TutorApplication
        fields = [
            "id",
            "opening",
            "opening_title",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "postcode",
            "subjects",
            "qualifications",
            "experience",
            "right_to_work",
            "video_url",
            "cv",
            "answers",
            "stage",
            "stage_name",
            "stage_entered_at",
            "status",
            "owner",
            "decision_reason",
            "decided_at",
            "tutor",
            "created_at",
        ]
        read_only_fields = fields


class ApplicationDetailSerializer(ApplicationSerializer):
    scorecards = ScorecardSerializer(many=True, read_only=True)
    references = ReferenceSerializer(many=True, read_only=True)
    interviews = InterviewSerializer(many=True, read_only=True)

    class Meta(ApplicationSerializer.Meta):
        fields = [*ApplicationSerializer.Meta.fields, "scorecards", "references", "interviews"]
        read_only_fields = fields


class StageMoveSerializer(serializers.Serializer):
    stage = serializers.UUIDField()


class ScoreSerializer(serializers.Serializer):
    scores = serializers.DictField(child=serializers.IntegerField(min_value=1, max_value=5))
    recommendation = serializers.ChoiceField(choices=Scorecard.Recommendation.choices)
    notes = serializers.CharField(required=False, allow_blank=True)


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
    talent_pool = serializers.BooleanField(default=False)
    notify = serializers.BooleanField(default=True)


class BulkRejectSerializer(serializers.Serializer):
    applications = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    reason = serializers.CharField(max_length=500)


class ApproveSerializer(serializers.Serializer):
    employment_type = serializers.ChoiceField(
        choices=["self_employed", "employee", "other"], default="self_employed"
    )


class ProposeInterviewSerializer(serializers.Serializer):
    options = serializers.ListField(child=serializers.DateTimeField(), min_length=1, max_length=10)
    minutes = serializers.IntegerField(min_value=10, max_value=180, default=30)
    meeting_url = serializers.URLField(required=False, allow_blank=True, default="")


class RequestReferenceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    relationship = serializers.CharField(required=False, allow_blank=True, max_length=150)


class CountResultSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class ChecklistTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistTemplate
        fields = ["id", "name", "employment_type", "items", "is_default"]


class ChecklistItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    kind = serializers.CharField()
    mandatory = serializers.BooleanField()
    link = serializers.CharField(required=False, allow_blank=True)
    done = serializers.BooleanField()
    done_at = serializers.CharField(allow_null=True)


class TutorOnboardingStateSerializer(serializers.Serializer):
    items = ChecklistItemSerializer(many=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class RequirementTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequirementType
        fields = [
            "id",
            "key",
            "name",
            "description",
            "has_number",
            "has_expiry",
            "renewal_months",
            "mandatory",
            "blocking",
            "applies_to",
            "active",
        ]


class ComplianceRecordSerializer(serializers.ModelSerializer):
    requirement_key = serializers.CharField(source="requirement.key", read_only=True)
    requirement_name = serializers.CharField(source="requirement.name", read_only=True)
    number = serializers.SerializerMethodField()
    valid = serializers.SerializerMethodField()

    class Meta:
        model = ComplianceRecord
        fields = [
            "id",
            "tutor",
            "requirement",
            "requirement_key",
            "requirement_name",
            "status",
            "number",
            "issue_date",
            "expiry_date",
            "files",
            "verified_at",
            "rejection_reason",
            "notes",
            "valid",
        ]
        read_only_fields = fields

    def get_number(self, obj: ComplianceRecord) -> str:
        if self.context.get("show_numbers"):
            return obj.number
        return ("•" * max(len(obj.number) - 4, 0) + obj.number[-4:]) if obj.number else ""

    def get_valid(self, obj: ComplianceRecord) -> bool:
        from .. import compliance

        return compliance.is_valid(obj, compliance.today())


class TutorComplianceSerializer(serializers.Serializer):
    restricted = serializers.BooleanField()
    problems = serializers.ListField(child=serializers.CharField())
    requirements = RequirementTypeSerializer(many=True)
    records = ComplianceRecordSerializer(many=True)


class SubmitRecordSerializer(serializers.Serializer):
    requirement = serializers.UUIDField()
    number = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    issue_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    files = serializers.ListField(child=serializers.UUIDField(), required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RejectRecordSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class DashboardCellSerializer(serializers.Serializer):
    status = serializers.CharField()
    expiry_date = serializers.DateField(allow_null=True)


class DashboardRowSerializer(serializers.Serializer):
    tutor = serializers.UUIDField(source="tutor.pk")
    name = serializers.CharField(source="tutor.full_name")
    status = serializers.CharField()
    cells = serializers.DictField(child=DashboardCellSerializer())


class ComplianceDashboardSerializer(serializers.Serializer):
    requirements = RequirementTypeSerializer(many=True)
    rows = DashboardRowSerializer(many=True)


class AssessSubjectSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["claimed", "assessed", "approved", "rejected"])
    evidence = serializers.CharField(required=False, allow_blank=True, default="")


class PublicOpeningSerializer(serializers.Serializer):
    title = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField()
    location = serializers.CharField()
    subjects = serializers.ListField(child=serializers.DictField())
    closes_on = serializers.DateField(allow_null=True)


class PublicOpeningDetailSerializer(PublicOpeningSerializer):
    schema = serializers.DictField()
    turnstile_site_key = serializers.CharField(allow_blank=True)
    organisation = serializers.CharField()


class PublicApplySerializer(serializers.Serializer):
    data = serializers.DictField()  # type: ignore[assignment]
    captcha_token = serializers.CharField(required=False, allow_blank=True, default="")
    website = serializers.CharField(required=False, allow_blank=True, default="")


class PublicInterviewSerializer(serializers.Serializer):
    applicant = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField())
    minutes = serializers.IntegerField()
    status = serializers.CharField()
    start = serializers.DateTimeField(allow_null=True)
    meeting_url = serializers.CharField(allow_blank=True)
    organisation = serializers.CharField()


class BookInterviewSerializer(serializers.Serializer):
    start = serializers.CharField()


class PublicReferenceSerializer(serializers.Serializer):
    applicant = serializers.CharField()
    status = serializers.CharField()
    questions = serializers.ListField(child=serializers.CharField())
    organisation = serializers.CharField()


class GiveReferenceSerializer(serializers.Serializer):
    responses = serializers.DictField(child=serializers.CharField(allow_blank=True))
    rating = serializers.IntegerField(min_value=1, max_value=5)
    concerns = serializers.BooleanField(default=False)


REFERENCE_QUESTIONS = [
    "How do you know the applicant, and for how long?",
    "How reliable and punctual are they?",
    "How well do they work with children or young people?",
    "Do you know of any reason they shouldn't work with children?",
]


def public_opening(opening: JobOpening) -> dict[str, Any]:
    return {
        "title": opening.title,
        "slug": opening.slug,
        "description": opening.description,
        "location": opening.location,
        "subjects": opening.subjects,
        "closes_on": opening.closes_on,
    }
