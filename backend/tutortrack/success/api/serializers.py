"""Serializers for help, guidance, the setup checklist, surveys, support chat and product
analytics (E30 Part 2)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import SupportConversation, SupportMessage, SurveyResponse


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.email


class HelpArticleRowSerializer(serializers.Serializer):
    slug = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()
    tour = serializers.CharField()


class HelpArticleSerializer(HelpArticleRowSerializer):
    body = serializers.CharField(help_text="Markdown (headings, lists, bold, links)")
    routes = serializers.ListField(child=serializers.CharField())
    tags = serializers.ListField(child=serializers.CharField())


class HelpChangelogEntrySerializer(serializers.Serializer):
    slug = serializers.CharField()
    title = serializers.CharField()
    summary = serializers.CharField()
    body = serializers.CharField()
    published_on = serializers.DateField()


class GuidanceSerializer(serializers.Serializer):
    completed_tours = serializers.ListField(child=serializers.CharField())
    dismissed_tours = serializers.ListField(child=serializers.CharField())
    changelog_unread = serializers.IntegerField()
    nps_due = serializers.BooleanField()
    support_unread = serializers.IntegerField()
    analytics_allowed = serializers.BooleanField(
        help_text="The organisation allows usage analytics for this member; the browser "
        "still needs the person's analytics consent."
    )


class TourStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["completed", "dismissed", "restart"])


class SetupStepSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    link = serializers.CharField()
    done = serializers.BooleanField()
    completed_at = serializers.DateTimeField(allow_null=True)


class SetupChecklistSerializer(serializers.Serializer):
    steps = SetupStepSerializer(many=True)
    done = serializers.IntegerField()
    total = serializers.IntegerField()
    completed_at = serializers.DateTimeField(allow_null=True)
    dismissed_at = serializers.DateTimeField(allow_null=True)


class SetupChecklistUpdateSerializer(serializers.Serializer):
    dismissed = serializers.BooleanField()


class SurveyAnswerSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SurveyResponse.Kind.choices)
    score = serializers.IntegerField(min_value=0, max_value=10, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    topic = serializers.CharField(
        required=False, allow_blank=True, max_length=80, help_text="e.g. support:<chat id>"
    )


class SurveyResponseSerializer(BaseModelSerializer):
    topic = serializers.CharField(source="context", read_only=True)

    class Meta:
        model = SurveyResponse
        fields = ["id", "kind", "score", "comment", "topic", "created_at"]
        read_only_fields = fields


class SupportMessageSerializer(BaseModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = SupportMessage
        fields = ["id", "from_support", "author_name", "body", "created_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_author_name(self, obj: SupportMessage) -> str:
        if obj.from_support:
            first = obj.author.first_name if obj.author else ""
            return f"{first} (TutorTrack)".strip() if first else "TutorTrack"
        return person_name(obj.author)


class SupportConversationSerializer(BaseModelSerializer):
    opened_by_name = serializers.SerializerMethodField()
    csat_score = serializers.SerializerMethodField()

    class Meta:
        model = SupportConversation
        fields = [
            "id", "subject", "status", "page", "opened_by_name", "last_message_at",
            "customer_unread", "closed_at", "created_at", "csat_score",
        ]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_opened_by_name(self, obj: SupportConversation) -> str:
        return person_name(obj.opened_by)

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_csat_score(self, obj: SupportConversation) -> int | None:
        row = SurveyResponse.objects.filter(
            kind=SurveyResponse.Kind.CSAT, context=f"support:{obj.pk}"
        ).first()
        return row.score if row else None


class SupportConversationDetailSerializer(SupportConversationSerializer):
    messages = SupportMessageSerializer(many=True, read_only=True)

    class Meta(SupportConversationSerializer.Meta):
        fields = [*SupportConversationSerializer.Meta.fields, "messages"]
        read_only_fields = fields


class SupportConversationCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True)
    body = serializers.CharField(max_length=5000)
    page = serializers.CharField(max_length=200, required=False, allow_blank=True)


class SupportMessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)


class ProductEventInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60, help_text="e.g. page.viewed, invoice.sent")
    route = serializers.CharField(max_length=200, required=False, allow_blank=True)
    properties = serializers.DictField(required=False)
    occurred_at = serializers.CharField(required=False, allow_blank=True)


class ProductEventBatchSerializer(serializers.Serializer):
    events = ProductEventInSerializer(many=True)


class AcceptedSerializer(serializers.Serializer):
    accepted = serializers.IntegerField()
