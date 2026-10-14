"""Serializers for the G4 communications endpoints."""

from __future__ import annotations

from rest_framework import serializers

from ..models import DigestPreference


class DigestPreferenceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DigestPreference.Kind.choices)
    label = serializers.CharField()  # type: ignore[assignment]
    enabled = serializers.BooleanField(help_text="The person wants it.")
    org_enabled = serializers.BooleanField(
        help_text="The organisation sends it (Settings → Notifications)."
    )
    send_time = serializers.TimeField(format="%H:%M")
    weekday = serializers.IntegerField(
        allow_null=True, help_text="Weekly digests: 0 = Monday … 6 = Sunday."
    )
    customised = serializers.BooleanField()


class DigestPreferenceWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=DigestPreference.Kind.choices)
    enabled = serializers.BooleanField(default=True)
    send_time = serializers.TimeField(required=False, allow_null=True, default=None)
    weekday = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0, max_value=6
    )
