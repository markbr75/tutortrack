"""AI API serializers (E31). Component names carry an ``AI`` prefix (no OpenAPI clashes)."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import (
    AIAssist,
    AIFeatureSetting,
    AIFeedback,
    AIProposal,
    AIRequestLog,
    Feature,
    ThreadInsight,
)
from ..prompts import INTENTS

# --- status, settings, usage --------------------------------------------------------------------


class AICreditsSerializer(serializers.Serializer):
    metered = serializers.BooleanField()
    used_this_month = serializers.IntegerField()
    monthly_cap = serializers.IntegerField(allow_null=True)
    balance = serializers.IntegerField(allow_null=True)
    allowance = serializers.IntegerField(allow_null=True)


class AIStatusSerializer(serializers.Serializer):
    available = serializers.BooleanField(help_text="The plan includes the AI assistant.")
    provider = serializers.CharField()
    features = serializers.DictField(child=serializers.BooleanField())
    credits_exhausted = serializers.BooleanField()
    credits = AICreditsSerializer(allow_null=True, help_text="Only for ai.usage.view.")


class AIFeatureSettingSerializer(serializers.Serializer):
    feature = serializers.ChoiceField(choices=Feature.choices)
    title = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField()
    tone = serializers.ChoiceField(choices=AIFeatureSetting.Tone.choices, allow_blank=True)
    language = serializers.ChoiceField(choices=AIFeatureSetting.Language.choices, allow_blank=True)


class AIFeatureUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    tone = serializers.ChoiceField(
        choices=AIFeatureSetting.Tone.choices, allow_blank=True, required=False
    )
    language = serializers.ChoiceField(
        choices=AIFeatureSetting.Language.choices, allow_blank=True, required=False
    )


class AIUsageFeatureSerializer(serializers.Serializer):
    feature = serializers.CharField()
    requests = serializers.IntegerField()
    credits = serializers.IntegerField()


class AIUsageUserSerializer(serializers.Serializer):
    user = serializers.UUIDField(allow_null=True)
    name = serializers.CharField()
    requests = serializers.IntegerField()
    credits = serializers.IntegerField()


class AIUsageSerializer(serializers.Serializer):
    period = serializers.DateField()
    totals = serializers.DictField(child=serializers.IntegerField())
    by_feature = AIUsageFeatureSerializer(many=True)
    by_user = AIUsageUserSerializer(many=True)
    feedback = serializers.DictField(child=serializers.IntegerField())
    credits = AICreditsSerializer()


class AIRequestLogSerializer(BaseModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AIRequestLog
        fields = [
            "id",
            "created_at",
            "user",
            "user_name",
            "feature",
            "prompt_key",
            "prompt_version",
            "provider",
            "model",
            "status",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "credits",
            "latency_ms",
            "tool_rounds",
            "fallback_used",
            "redacted_input_hash",
            "error_code",
        ]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_user_name(self, obj: AIRequestLog) -> str:
        if obj.user is None:
            return ""
        return obj.user.get_full_name() or obj.user.email


# --- feedback, assists, proposals, insights -----------------------------------------------------


class AIFeedbackInSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    rating = serializers.ChoiceField(
        choices=AIFeedback.Rating.choices, allow_blank=True, required=False, default=""
    )
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    draft_text = serializers.CharField(
        required=False, allow_blank=True, max_length=20_000, trim_whitespace=False
    )
    final_text = serializers.CharField(
        required=False, allow_blank=True, max_length=20_000, trim_whitespace=False
    )


class AIFeedbackOutSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    rating = serializers.CharField()
    similarity_percent = serializers.IntegerField(allow_null=True)


class AIAssistInSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    subject_type = serializers.CharField(max_length=40)
    subject_id = serializers.CharField(max_length=64)


class AIAssistSerializer(BaseModelSerializer):
    class Meta:
        model = AIAssist
        fields = ["id", "created_at", "request", "user", "feature", "subject_type", "subject_id"]
        read_only_fields = fields


class AIProposalSerializer(BaseModelSerializer):
    class Meta:
        model = AIProposal
        fields = [
            "id",
            "created_at",
            "feature",
            "action",
            "params",
            "summary",
            "status",
            "result",
            "error",
            "decided_at",
            "request",
        ]
        read_only_fields = fields


class AIThreadInsightSerializer(BaseModelSerializer):
    class Meta:
        model = ThreadInsight
        fields = ["id", "thread", "intent", "confidence", "message_count", "classified_at"]
        read_only_fields = fields


# --- feature requests and drafts ----------------------------------------------------------------


class AILessonReportDraftInSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=20_000)
    audio = serializers.FileField(required=False, allow_null=True)


class AITopicSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class AILessonReportDraftSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    answers = serializers.DictField(child=serializers.JSONField())
    suggested_topics = AITopicSerializer(many=True)
    homework = serializers.CharField(allow_blank=True)
    transcript = serializers.CharField(allow_blank=True)


class AIProgressDraftSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    summary = serializers.CharField(allow_blank=True)


class AIRewriteInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=20_000)
    language = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    contact = serializers.UUIDField(required=False, allow_null=True)
    student = serializers.UUIDField(required=False, allow_null=True)


class AIRewriteSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    text = serializers.CharField(allow_blank=True)
    language = serializers.CharField(allow_blank=True)


class AIExtractInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=20_000)


class AIExtractedContactSerializer(serializers.Serializer):
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    email = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)


class AIExtractedStudentSerializer(serializers.Serializer):
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    year_group = serializers.CharField(allow_blank=True)
    school = serializers.CharField(allow_blank=True)


class AIExtractedSubjectSerializer(serializers.Serializer):
    subject = serializers.CharField()
    level = serializers.CharField(allow_blank=True)


class AIExtractedLocationSerializer(serializers.Serializer):
    postcode = serializers.CharField(allow_blank=True)
    area = serializers.CharField(allow_blank=True)
    mode = serializers.CharField(allow_blank=True)


class AIExtractedEnquirySerializer(serializers.Serializer):
    contact = AIExtractedContactSerializer()
    students = AIExtractedStudentSerializer(many=True)
    subjects = AIExtractedSubjectSerializer(many=True)
    availability = serializers.ListField(child=serializers.CharField())
    location = AIExtractedLocationSerializer()
    urgency = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)


class AIExtractSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    extracted = AIExtractedEnquirySerializer()


class AITriageSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    extracted = AIExtractedEnquirySerializer()
    next_steps = serializers.ListField(child=serializers.CharField())
    priority = serializers.CharField(allow_blank=True)
    reply_subject = serializers.CharField(allow_blank=True)
    reply_body = serializers.CharField(allow_blank=True)
    proposal = AIProposalSerializer(allow_null=True)


class AIReplySerializer(serializers.Serializer):
    request = serializers.UUIDField()
    reply = serializers.CharField(allow_blank=True)


class AISummarySerializer(serializers.Serializer):
    request = serializers.UUIDField()
    summary = serializers.CharField(allow_blank=True)
    action_items = serializers.ListField(child=serializers.CharField())


class AIClassifySerializer(serializers.Serializer):
    request = serializers.UUIDField()
    intent = serializers.ChoiceField(choices=INTENTS)
    confidence = serializers.IntegerField()
    reason = serializers.CharField(allow_blank=True)
    proposal = AIProposalSerializer(allow_null=True)


class AICommandInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)


class AITutorSearchSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_null=True)
    subject_name = serializers.CharField(allow_blank=True)
    level = serializers.CharField(allow_null=True)
    level_name = serializers.CharField(allow_blank=True)
    mode = serializers.CharField()
    postcode = serializers.CharField(allow_blank=True)
    weekday = serializers.CharField(allow_blank=True)
    after_time = serializers.CharField(allow_blank=True)
    before_time = serializers.CharField(allow_blank=True)


class AICommandSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    message = serializers.CharField(allow_blank=True)
    proposals = AIProposalSerializer(many=True)
    searches = AITutorSearchSerializer(many=True)


class AICopilotTurnSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    answer = serializers.CharField(max_length=8000, allow_blank=True)


class AICopilotInSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    history = AICopilotTurnSerializer(many=True, required=False, default=list)


class AICitationSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    report = serializers.CharField()
    title = serializers.CharField()
    period = serializers.DictField(child=serializers.CharField())
    params = serializers.DictField(child=serializers.CharField())
    link = serializers.CharField()


class AICopilotSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    answer = serializers.CharField(allow_blank=True)
    citations = AICitationSerializer(many=True)


class AIContentInSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["broadcast", "bio", "page", "job_ad"])
    brief = serializers.CharField(max_length=4000, allow_blank=True)
    channel = serializers.ChoiceField(choices=["email", "sms"], required=False, default="email")
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    tutor = serializers.UUIDField(required=False, allow_null=True)
    subjects = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, default=list
    )
    location = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")


class AIContentSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    kind = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    meta_description = serializers.CharField(allow_blank=True)
    warnings = serializers.ListField(child=serializers.CharField())


class AIMatchExplainInSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    job = serializers.UUIDField(required=False, allow_null=True)
    criteria = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
        help_text="Ad hoc search criteria, as for the matching search.",
    )


class AIMatchExplainSerializer(serializers.Serializer):
    request = serializers.UUIDField()
    score = serializers.CharField()
    explanation = serializers.CharField(allow_blank=True)
    intro_message = serializers.CharField(allow_blank=True)
