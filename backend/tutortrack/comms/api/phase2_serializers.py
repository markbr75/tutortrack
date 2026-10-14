"""Serializers for broadcasts, the inbox, channels and marketing sync (E13 Phase 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, TenantRelatedField
from tutortrack.core.time import now

from .. import broadcasts, selectors
from ..models import (
    Audience,
    Broadcast,
    BroadcastRecipient,
    CannedReply,
    Channel,
    PhoneNumber,
    Segment,
    SenderDomain,
    Thread,
    ThreadMessage,
    ThreadParticipant,
    WhatsAppTemplate,
)

BROADCAST_CHANNELS = [(c, label) for c, label in Channel.choices if c in broadcasts.CHANNELS]
REPLY_CHANNELS = [
    (c, label) for c, label in ThreadMessage.Via.choices if c != ThreadMessage.Via.NOTE
]
NUMBER_CHANNELS = [(c, label) for c, label in Channel.choices if c in ("sms", "whatsapp")]


# --- segments and broadcasts --------------------------------------------------------------------


class SegmentDefinitionSerializer(serializers.Serializer):
    branches = serializers.ListField(child=serializers.UUIDField(), required=False)
    tags = serializers.ListField(child=serializers.UUIDField(), required=False)
    saved_view = serializers.UUIDField(required=False, allow_null=True)
    client_statuses = serializers.ListField(child=serializers.CharField(), required=False)
    student_statuses = serializers.ListField(child=serializers.CharField(), required=False)
    tutor_statuses = serializers.ListField(child=serializers.CharField(), required=False)
    group_class = serializers.UUIDField(required=False, allow_null=True)
    job = serializers.UUIDField(required=False, allow_null=True)
    pipeline_stage = serializers.UUIDField(required=False, allow_null=True)
    contacts = serializers.ChoiceField(choices=["all", "primary"], required=False)
    subject = serializers.CharField(required=False, allow_blank=True)


def _definition(value: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe definition (ids as strings)."""
    out: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, list):
            out[key] = [str(v) for v in item]
        elif item is not None:
            out[key] = str(item) if not isinstance(item, str) else item
    return out


@extend_schema_field(SegmentDefinitionSerializer)
class DefinitionOut(serializers.JSONField):
    """Only the filters that are set (the schema documents every possible key)."""


class SegmentSerializer(BaseModelSerializer):
    definition = DefinitionOut(read_only=True)

    class Meta:
        model = Segment
        fields = ["id", "name", "description", "audience", "definition", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SegmentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )
    audience = serializers.ChoiceField(choices=Audience.choices)
    definition = SegmentDefinitionSerializer(required=False, default=dict)

    def validate_definition(self, value: dict[str, Any]) -> dict[str, Any]:
        return _definition(value)


class AudiencePreviewRequestSerializer(serializers.Serializer):
    audience = serializers.ChoiceField(choices=Audience.choices)
    definition = SegmentDefinitionSerializer(required=False, default=dict)
    channel = serializers.ChoiceField(choices=BROADCAST_CHANNELS, default=Channel.EMAIL)
    purpose = serializers.ChoiceField(
        choices=Broadcast.Purpose.choices, default=Broadcast.Purpose.OPERATIONAL
    )

    def validate_definition(self, value: dict[str, Any]) -> dict[str, Any]:
        return _definition(value)


class AudienceSampleSerializer(serializers.Serializer):
    name = serializers.CharField()
    address = serializers.CharField()
    kind = serializers.CharField()


class AudiencePreviewSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    sendable = serializers.IntegerField()
    skipped = serializers.DictField(child=serializers.IntegerField())
    sample = AudienceSampleSerializer(many=True)


class SegmentOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    name = serializers.CharField()


class SegmentOptionsSerializer(serializers.Serializer):
    branches = SegmentOptionSerializer(many=True)
    tags = SegmentOptionSerializer(many=True)
    saved_views = SegmentOptionSerializer(many=True)
    group_classes = SegmentOptionSerializer(many=True)
    pipeline_stages = SegmentOptionSerializer(many=True)
    client_statuses = SegmentOptionSerializer(many=True)
    student_statuses = SegmentOptionSerializer(many=True)
    tutor_statuses = SegmentOptionSerializer(many=True)


class BroadcastStatsSerializer(serializers.Serializer):
    recipients = serializers.IntegerField()
    pending = serializers.IntegerField()
    queued = serializers.IntegerField()
    skipped = serializers.IntegerField()
    sent = serializers.IntegerField()
    delivered = serializers.IntegerField()
    opened = serializers.IntegerField()
    clicked = serializers.IntegerField()
    bounced = serializers.IntegerField()
    failed = serializers.IntegerField()
    unsubscribed = serializers.IntegerField()


class BroadcastSerializer(BaseModelSerializer):
    definition = DefinitionOut(read_only=True)
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), read_only=True)
    segment_name = serializers.CharField(source="segment.name", read_only=True, default="")
    stats = serializers.SerializerMethodField()

    class Meta:
        model = Broadcast
        fields = [
            "id",
            "name",
            "channel",
            "purpose",
            "subject",
            "body",
            "whatsapp_template",
            "segment",
            "segment_name",
            "audience",
            "definition",
            "attachment_ids",
            "status",
            "scheduled_for",
            "started_at",
            "finished_at",
            "cancelled_at",
            "stats",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(BroadcastStatsSerializer)
    def get_stats(self, obj: Broadcast) -> dict[str, int]:
        if obj.status in (Broadcast.Status.DRAFT,):
            return dict.fromkeys(BroadcastStatsSerializer().fields, 0)
        return broadcasts.stats(obj)


class BroadcastWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    channel = serializers.ChoiceField(choices=BROADCAST_CHANNELS, default=Channel.EMAIL)
    purpose = serializers.ChoiceField(
        choices=Broadcast.Purpose.choices, default=Broadcast.Purpose.OPERATIONAL
    )
    subject = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=20000, required=False, allow_blank=True, default="")
    whatsapp_template = TenantRelatedField(WhatsAppTemplate, required=False, allow_null=True)
    segment = TenantRelatedField(Segment, required=False, allow_null=True)
    audience = serializers.ChoiceField(choices=Audience.choices, default=Audience.CONTACTS)
    definition = SegmentDefinitionSerializer(required=False, default=dict)
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=10
    )

    def validate_definition(self, value: dict[str, Any]) -> dict[str, Any]:
        return _definition(value)

    def validate_attachment_ids(self, value: list[Any]) -> list[str]:
        return [str(v) for v in value]


class ScheduleSerializer(serializers.Serializer):
    scheduled_for = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ContentPreviewSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    segments = serializers.IntegerField()


class BroadcastRecipientSerializer(BaseModelSerializer):
    message_status = serializers.CharField(source="message.status", read_only=True, default="")

    class Meta:
        model = BroadcastRecipient
        fields = [
            "id",
            "recipient_type",
            "recipient_id",
            "name",
            "address",
            "status",
            "skip_reason",
            "message",
            "message_status",
            "batch",
        ]
        read_only_fields = fields


# --- the inbox ----------------------------------------------------------------------------------


class ThreadParticipantSerializer(BaseModelSerializer):
    class Meta:
        model = ThreadParticipant
        fields = ["id", "role", "person_type", "person_id", "name", "email", "phone"]
        read_only_fields = fields


def _party(thread: Thread) -> str:
    if thread.kind == Thread.Kind.TUTOR_FAMILY and thread.client and thread.tutor:
        return f"{thread.client.display_name} · {thread.tutor.full_name}"
    if thread.client_id and thread.client:
        return str(thread.client.display_name)
    if thread.tutor_id and thread.tutor:
        return str(thread.tutor.full_name)
    return thread.contact_name or thread.contact_email or thread.contact_phone


class ThreadSerializer(BaseModelSerializer):
    status = serializers.SerializerMethodField()
    party = serializers.SerializerMethodField()
    assignee_name = serializers.SerializerMethodField()
    sla_due_at = serializers.SerializerMethodField()
    sla_breached = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = [
            "id",
            "subject",
            "kind",
            "client",
            "tutor",
            "party",
            "contact_name",
            "contact_email",
            "contact_phone",
            "status",
            "snoozed_until",
            "assignee",
            "assignee_name",
            "channel",
            "last_message_at",
            "last_message_preview",
            "awaiting_reply_since",
            "sla_due_at",
            "sla_breached",
            "flagged",
            "unread",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ChoiceField(choices=Thread.Status.choices))
    def get_status(self, obj: Thread) -> str:
        return selectors.effective_status(obj)

    @extend_schema_field(OpenApiTypes.STR)
    def get_party(self, obj: Thread) -> str:
        return _party(obj)

    @extend_schema_field(OpenApiTypes.STR)
    def get_assignee_name(self, obj: Thread) -> str:
        return (obj.assignee.get_full_name() or obj.assignee.email) if obj.assignee else ""

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_sla_due_at(self, obj: Thread) -> datetime | None:
        return selectors.sla_due_at(obj)

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_sla_breached(self, obj: Thread) -> bool:
        due = selectors.sla_due_at(obj)
        return bool(due and due <= now())

    @extend_schema_field(OpenApiTypes.INT)
    def get_unread(self, obj: Thread) -> int:
        request = self.context.get("request")
        if request is None:
            return 0
        return selectors.unread_count(obj, request.user)


class ThreadDetailSerializer(ThreadSerializer):
    participants = ThreadParticipantSerializer(many=True, read_only=True)
    reply_address = serializers.SerializerMethodField()

    class Meta(ThreadSerializer.Meta):
        fields = [*ThreadSerializer.Meta.fields, "participants", "reply_address"]
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.STR)
    def get_reply_address(self, obj: Thread) -> str:
        from ..senders import thread_reply_address

        return thread_reply_address(obj)


class AttachmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()


class ThreadMessageSerializer(BaseModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    flags = serializers.ListField(child=serializers.CharField(), read_only=True)
    delivery_status = serializers.CharField(source="message.status", read_only=True, default="")

    class Meta:
        model = ThreadMessage
        fields = [
            "id",
            "thread",
            "direction",
            "channel",
            "author_type",
            "author_id",
            "author_name",
            "subject",
            "body",
            "attachments",
            "flags",
            "delivery_status",
            "created_at",
        ]
        read_only_fields = fields


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    channel = serializers.ChoiceField(choices=REPLY_CHANNELS, required=False, allow_null=True)
    subject = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    attachments = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list, max_length=10
    )


class ThreadNoteSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)


class StartThreadSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=[c for c in Thread.Kind.choices if c[0] != Thread.Kind.OTHER]
    )
    client = serializers.UUIDField(required=False, allow_null=True)
    tutor = serializers.UUIDField(required=False, allow_null=True)
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    body = serializers.CharField(max_length=20000)
    channel = serializers.ChoiceField(choices=REPLY_CHANNELS, default=ThreadMessage.Via.CHAT)


class AssignSerializer(serializers.Serializer):
    assignee = serializers.UUIDField(allow_null=True)


class SnoozeSerializer(serializers.Serializer):
    until = serializers.DateTimeField()


class BoxCountsSerializer(serializers.Serializer):
    open = serializers.IntegerField()
    mine = serializers.IntegerField()
    unassigned = serializers.IntegerField()
    snoozed = serializers.IntegerField()
    flagged = serializers.IntegerField()


class AssigneeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class CannedReplySerializer(BaseModelSerializer):
    class Meta:
        model = CannedReply
        fields = ["id", "title", "body", "shortcut", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


# --- channels and senders -----------------------------------------------------------------------


class SenderDnsRecordSerializer(serializers.Serializer):
    purpose = serializers.CharField()
    record_type = serializers.CharField(source="type")
    host = serializers.CharField()
    value = serializers.CharField()
    verified = serializers.BooleanField()


class SenderDomainSerializer(BaseModelSerializer):
    dns_records = SenderDnsRecordSerializer(many=True, read_only=True)
    from_address = serializers.CharField(read_only=True)

    class Meta:
        model = SenderDomain
        fields = [
            "id",
            "domain",
            "local_part",
            "from_address",
            "status",
            "dns_records",
            "verified_at",
            "last_checked_at",
            "error",
            "is_default",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "dns_records",
            "verified_at",
            "last_checked_at",
            "error",
            "created_at",
            "from_address",
        ]


class SenderDomainUpdateSerializer(serializers.Serializer):
    local_part = serializers.CharField(max_length=64, required=False)
    is_default = serializers.BooleanField(required=False)


class PhoneNumberSerializer(BaseModelSerializer):
    channel = serializers.ChoiceField(choices=NUMBER_CHANNELS, default=Channel.SMS)

    class Meta:
        model = PhoneNumber
        fields = [
            "id",
            "channel",
            "number",
            "label",
            "branch",
            "is_default",
            "active",
            "created_at",
        ]
        read_only_fields = ["id", "active", "created_at"]


class WhatsAppTemplateSerializer(BaseModelSerializer):
    variables = serializers.ListField(child=serializers.CharField(max_length=500), required=False)

    class Meta:
        model = WhatsAppTemplate
        fields = [
            "id",
            "name",
            "language",
            "category",
            "content_sid",
            "body",
            "variables",
            "type_key",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MarketingConnectionSerializer(serializers.Serializer):
    provider = serializers.CharField()
    name = serializers.CharField()
    connection = serializers.UUIDField(allow_null=True)
    account_name = serializers.CharField(allow_blank=True)
    status = serializers.CharField(allow_blank=True)
    audience_id = serializers.CharField(allow_blank=True)
    audience_name = serializers.CharField(allow_blank=True)
    last_sync_at = serializers.DateTimeField(allow_null=True)
    error = serializers.CharField(allow_blank=True)
    webhook_url = serializers.CharField(
        allow_blank=True, help_text="Paste into Mailchimp/Brevo webhooks (unsubscribes)."
    )


class MarketingAudienceSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    members = serializers.IntegerField()


class ChooseAudienceSerializer(serializers.Serializer):
    audience_id = serializers.CharField(max_length=64)


class MarketingSyncResultSerializer(serializers.Serializer):
    upserted = serializers.IntegerField()
    unsubscribed = serializers.IntegerField()
    failed = serializers.IntegerField()
    opted_out = serializers.IntegerField(
        required=False, help_text="Contacts who had unsubscribed at the provider (G4)."
    )
