from __future__ import annotations

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from ..models import CalendarSyncSettings, ExternalBusyBlock, MeetingPreference, OnlineMeeting

VIDEO_CHOICES = ["none", "builtin", "zoom", "teams", "google_meet", "lessonspace"]


class CalendarOptionSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    primary = serializers.BooleanField()
    writable = serializers.BooleanField()


class CalendarSyncSettingsSerializer(BaseModelSerializer):
    class Meta:
        model = CalendarSyncSettings
        fields = [
            "id",
            "connection",
            "read_calendar_ids",
            "write_enabled",
            "write_calendar_id",
            "two_way",
            "title_format",
            "updated_at",
        ]
        read_only_fields = ["id", "connection", "updated_at"]


class CalendarSyncSettingsUpdateSerializer(serializers.Serializer):
    read_calendar_ids = serializers.ListField(
        child=serializers.CharField(max_length=500), required=False, max_length=20
    )
    write_enabled = serializers.BooleanField(required=False)
    write_calendar_id = serializers.CharField(required=False, allow_blank=True, max_length=500)
    two_way = serializers.BooleanField(required=False)
    title_format = serializers.CharField(required=False, allow_blank=True, max_length=120)


class CalendarSyncPageSerializer(serializers.Serializer):
    settings = CalendarSyncSettingsSerializer()
    calendars = CalendarOptionSerializer(many=True)
    calendars_error = serializers.CharField(allow_blank=True)
    two_way_allowed = serializers.BooleanField()


class ExternalBusyBlockSerializer(BaseModelSerializer):
    class Meta:
        model = ExternalBusyBlock
        fields = ["id", "user", "source", "start", "end", "all_day"]
        read_only_fields = fields


class OnlineMeetingSerializer(BaseModelSerializer):
    """Staff view: no passcode or host link (those reach tutors through join links)."""

    class Meta:
        model = OnlineMeeting
        fields = [
            "id",
            "lesson",
            "provider",
            "status",
            "join_url",
            "provisioned_start",
            "provisioned_end",
            "last_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProvisionSerializer(serializers.Serializer):
    lesson = serializers.UUIDField()


class ProvisionResultSerializer(serializers.Serializer):
    started = serializers.BooleanField()


class MeetingPreferenceSerializer(BaseModelSerializer):
    provider = serializers.ChoiceField(choices=VIDEO_CHOICES, required=False, allow_blank=True)

    class Meta:
        model = MeetingPreference
        fields = ["provider", "use_personal_room"]


class JoinLinkSerializer(serializers.Serializer):
    url = serializers.URLField()
    opens_at = serializers.DateTimeField(allow_null=True)
    provider = serializers.CharField(allow_blank=True)
    role = serializers.ChoiceField(choices=["host", "participant"])
    open = serializers.BooleanField(help_text="Whether the join button is enabled now.")
