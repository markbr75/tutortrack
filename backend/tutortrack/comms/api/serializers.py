from __future__ import annotations

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import Channel, InAppNotification, Message, MessageEvent, PushSubscription
from ..registry import CATEGORIES

CHANNELS = Channel.choices


class NotificationSettingSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    category = serializers.CharField()
    audience = serializers.CharField()
    channels = serializers.ListField(child=serializers.ChoiceField(choices=CHANNELS))
    available_channels = serializers.ListField(child=serializers.ChoiceField(choices=CHANNELS))
    enabled = serializers.BooleanField()
    timing = serializers.ListField(child=serializers.IntegerField())
    has_timing = serializers.BooleanField()
    transactional = serializers.BooleanField()
    customised = serializers.BooleanField()


class NotificationSettingUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    channels = serializers.ListField(child=serializers.ChoiceField(choices=CHANNELS))
    timing = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True, default=None
    )


class TemplateSerializer(serializers.Serializer):
    type_key = serializers.CharField()
    channel = serializers.ChoiceField(choices=CHANNELS)
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField()
    customised = serializers.BooleanField()
    version = serializers.IntegerField()
    variables = serializers.ListField(child=serializers.CharField())


class TemplateWriteSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=300, allow_blank=True, default="")
    body = serializers.CharField(max_length=20000)


class PreviewRequestSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True, required=False, allow_null=True)
    body = serializers.CharField(required=False, allow_null=True)


class PreviewSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    segments = serializers.IntegerField()


class MessageEventSerializer(BaseModelSerializer):
    class Meta:
        model = MessageEvent
        fields = ["type", "occurred_at", "detail"]
        read_only_fields = fields


class MessageSerializer(BaseModelSerializer):
    events = MessageEventSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "type_key",
            "channel",
            "recipient_type",
            "recipient_id",
            "recipient_name",
            "to",
            "subject",
            "body",
            "status",
            "error",
            "related_type",
            "related_id",
            "target_type",
            "target_id",
            "scheduled_for",
            "sent_at",
            "segments",
            "created_at",
            "events",
        ]
        read_only_fields = fields


class InAppSerializer(BaseModelSerializer):
    class Meta:
        model = InAppNotification
        fields = ["id", "type_key", "title", "body", "link", "read_at", "created_at"]
        read_only_fields = fields


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), required=False, allow_null=True)


class PreferenceRowSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        choices=["scheduling", "reports", "billing", "account", "staff"]
    )
    channels = serializers.ListField(child=serializers.ChoiceField(choices=CHANNELS))


class PreferencesSerializer(serializers.Serializer):
    person_type = serializers.ChoiceField(choices=["contact", "tutor", "user"])
    person_id = serializers.CharField(max_length=64)
    preferences = PreferenceRowSerializer(many=True)


class UnsubscribeSerializer(serializers.Serializer):
    category = serializers.CharField()
    done = serializers.BooleanField()


# --- Web Push and my preferences (E16-T09) ------------------------------------------------------


class PushConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    vapid_public_key = serializers.CharField(allow_blank=True)


class PushSubscriptionSerializer(BaseModelSerializer):
    """A device with push switched on. The endpoint and keys are write-only secrets."""

    class Meta:
        model = PushSubscription
        fields = ["id", "device", "push_service", "last_sent_at", "created_at"]
        read_only_fields = fields


class PushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)


class PushSubscribeSerializer(serializers.Serializer):
    """``PushSubscription.toJSON()`` from the browser, plus a device name."""

    endpoint = serializers.URLField(max_length=2000)
    keys = PushKeysSerializer()
    device = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class PushTestSerializer(serializers.Serializer):
    delivered = serializers.IntegerField()


class MyPreferenceSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=[(c, c) for c in CATEGORIES])
    channels = serializers.ListField(child=serializers.ChoiceField(choices=CHANNELS))
    available = serializers.ListField(
        child=serializers.ChoiceField(choices=CHANNELS), read_only=True
    )


class MyPreferencesSerializer(serializers.Serializer):
    preferences = MyPreferenceSerializer(many=True)
