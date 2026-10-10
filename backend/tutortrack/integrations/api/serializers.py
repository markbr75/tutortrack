from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer

from .. import providers
from ..models import IntegrationConnection


class ProviderSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())
    auth = serializers.ChoiceField(choices=["oauth2", "credentials", "platform"])
    levels = serializers.ListField(child=serializers.CharField())
    credential_fields = serializers.ListField(child=serializers.CharField())
    simulated = serializers.BooleanField(help_text="No platform keys: a fake stands in.")


class ConnectionUserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    email = serializers.EmailField()


class IntegrationConnectionSerializer(BaseModelSerializer):
    """Tokens and secrets are never serialised."""

    user = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationConnection
        fields = [
            "id",
            "provider",
            "provider_name",
            "level",
            "status",
            "user",
            "account_name",
            "capabilities",
            "scopes",
            "expires_at",
            "last_sync_at",
            "last_checked_at",
            "error",
            "error_at",
            "error_count",
            "connected_at",
            "disconnected_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(ConnectionUserSerializer(allow_null=True))
    def get_user(self, obj: IntegrationConnection) -> dict[str, str] | None:
        if obj.user is None:
            return None
        return {
            "id": str(obj.user.pk),
            "name": obj.user.get_full_name() or obj.user.email,
            "email": obj.user.email,
        }

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_capabilities(self, obj: IntegrationConnection) -> list[str]:
        return sorted(providers.get_spec(obj.provider).capabilities)

    @extend_schema_field(serializers.CharField())
    def get_provider_name(self, obj: IntegrationConnection) -> str:
        return providers.get_spec(obj.provider).label


LEVELS = IntegrationConnection.Level.choices


class OAuthStartSerializer(serializers.Serializer):
    provider = serializers.CharField()
    level = serializers.ChoiceField(choices=LEVELS, default="user")
    next = serializers.CharField(default="/settings/integrations", max_length=300)


class OAuthStartResultSerializer(serializers.Serializer):
    authorize_url = serializers.URLField()


class OAuthCompleteSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=4000)
    state = serializers.CharField(max_length=4000)


class CredentialConnectSerializer(serializers.Serializer):
    provider = serializers.CharField()
    level = serializers.ChoiceField(choices=LEVELS, default="user")
    username = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    password = serializers.CharField(
        required=False, allow_blank=True, default="", write_only=True, max_length=500
    )
    server_url = serializers.URLField(required=False, allow_blank=True, default="")
    api_key = serializers.CharField(
        required=False, allow_blank=True, default="", write_only=True, max_length=500
    )
