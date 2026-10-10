from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import TenantRelatedField
from tutortrack.tenancy.models import Branch

from .. import scopes, tokens
from ..models import (
    ApiKey,
    OAuthApplication,
    OAuthGrant,
    Sandbox,
    WebhookAttempt,
    WebhookDelivery,
    WebhookEndpoint,
)

ENDPOINT_TOGGLE = [("active", "active"), ("paused", "paused")]
MARKETPLACE_STATUS = [
    ("connected", "connected"),
    ("available", "available"),
    ("coming_soon", "coming_soon"),
]
MARKETPLACE_KIND = [("native", "native"), ("partner", "partner")]
SCOPE_ACCESS = [("read", "read"), ("write", "write")]

# --- scopes -------------------------------------------------------------------------------------


class ScopeSerializer(serializers.Serializer):
    key = serializers.CharField()
    resource = serializers.CharField()
    access = serializers.ChoiceField(choices=SCOPE_ACCESS)
    description = serializers.CharField()
    permissions = serializers.ListField(child=serializers.CharField())


def scope_list(**kwargs: Any) -> serializers.ListField:
    return serializers.ListField(child=serializers.ChoiceField(choices=scopes.ALL_SCOPES), **kwargs)


# --- API keys -----------------------------------------------------------------------------------


class ApiKeySerializer(serializers.ModelSerializer):
    scopes = serializers.ListField(child=serializers.CharField(), read_only=True)
    ip_allowlist = serializers.ListField(child=serializers.CharField(), read_only=True)
    display = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    active = serializers.SerializerMethodField()

    class Meta:
        model = ApiKey
        fields = [
            "id", "name", "display", "prefix", "scopes", "branch", "branch_name",
            "ip_allowlist", "expires_at", "revoked_at", "last_used_at", "last_used_ip",
            "rate_limit_per_minute", "rotated_from", "user", "user_name", "active",
            "created_at",
        ]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_display(self, key: ApiKey) -> str:
        return tokens.display(str(tokens.CredentialKind.API_KEY), key.prefix)

    @extend_schema_field(serializers.CharField())
    def get_user_name(self, key: ApiKey) -> str:
        user = key.user
        return str(getattr(user, "get_full_name", lambda: "")() or user.email)

    @extend_schema_field(serializers.BooleanField())
    def get_active(self, key: ApiKey) -> bool:
        from tutortrack.core.time import now

        return key.revoked_at is None and (key.expires_at is None or key.expires_at > now())


class ApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    scopes = scope_list()
    branch = TenantRelatedField(Branch, required=False, allow_null=True)
    ip_allowlist = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, default=list
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    rate_limit_per_minute = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=6000
    )


class ApiKeyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=scopes.ALL_SCOPES), required=False
    )
    ip_allowlist = serializers.ListField(child=serializers.CharField(max_length=50), required=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    rate_limit_per_minute = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=6000
    )


class ApiKeySecretSerializer(ApiKeySerializer):
    """Returned once, on creation or rotation."""

    secret = serializers.SerializerMethodField()

    class Meta(ApiKeySerializer.Meta):
        fields = [*ApiKeySerializer.Meta.fields, "secret"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_secret(self, key: ApiKey) -> str:
        return str(self.context.get("secret", ""))


# --- OAuth applications -------------------------------------------------------------------------


class OAuthApplicationSerializer(serializers.ModelSerializer):
    redirect_uris = serializers.ListField(child=serializers.CharField(), read_only=True)
    allowed_scopes = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = OAuthApplication
        fields = [
            "id", "name", "description", "homepage_url", "logo_url", "client_id",
            "confidential", "redirect_uris", "allowed_scopes", "partner_key", "created_at",
        ]  # fmt: skip
        read_only_fields = fields


class OAuthApplicationWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    homepage_url = serializers.URLField(required=False, allow_blank=True, default="")
    logo_url = serializers.URLField(required=False, allow_blank=True, default="")
    confidential = serializers.BooleanField(default=True)
    redirect_uris = serializers.ListField(child=serializers.CharField(max_length=500))
    allowed_scopes = scope_list()


class OAuthApplicationPatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    homepage_url = serializers.URLField(required=False, allow_blank=True)
    logo_url = serializers.URLField(required=False, allow_blank=True)
    redirect_uris = serializers.ListField(
        child=serializers.CharField(max_length=500), required=False
    )
    allowed_scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=scopes.ALL_SCOPES), required=False
    )


class OAuthApplicationSecretSerializer(OAuthApplicationSerializer):
    client_secret = serializers.SerializerMethodField()

    class Meta(OAuthApplicationSerializer.Meta):
        fields = [*OAuthApplicationSerializer.Meta.fields, "client_secret"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_client_secret(self, app: OAuthApplication) -> str | None:
        secret = self.context.get("client_secret")
        return str(secret) if secret else None


class ConnectedAppSerializer(serializers.ModelSerializer):
    scopes = serializers.ListField(child=serializers.CharField(), read_only=True)
    application = OAuthApplicationSerializer(read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = OAuthGrant
        fields = ["id", "application", "user", "user_email", "scopes", "last_used_at", "created_at"]
        read_only_fields = fields


class AuthorizeQuerySerializer(serializers.Serializer):
    client_id = serializers.CharField(max_length=60)
    redirect_uri = serializers.CharField(max_length=500)
    response_type = serializers.CharField(max_length=20, default="code")
    scope = serializers.CharField(max_length=2000)
    state = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    code_challenge = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    code_challenge_method = serializers.CharField(
        max_length=8, required=False, allow_blank=True, default=""
    )


class AuthorizeDecisionSerializer(AuthorizeQuerySerializer):
    approve = serializers.BooleanField()


class ConsentScopeSerializer(serializers.Serializer):
    key = serializers.CharField()
    description = serializers.CharField()


class ConsentSerializer(serializers.Serializer):
    application = OAuthApplicationSerializer()
    scopes = ConsentScopeSerializer(many=True)
    redirect_uri = serializers.CharField()
    state = serializers.CharField()
    organisation_name = serializers.CharField()


class OAuthRedirectSerializer(serializers.Serializer):
    redirect_to = serializers.CharField()


class TokenRequestSerializer(serializers.Serializer):
    grant_type = serializers.ChoiceField(choices=["authorization_code", "refresh_token"])
    client_id = serializers.CharField(max_length=60)
    client_secret = serializers.CharField(required=False, allow_blank=True, default="")
    code = serializers.CharField(required=False, allow_blank=True, default="")
    redirect_uri = serializers.CharField(required=False, allow_blank=True, default="")
    code_verifier = serializers.CharField(required=False, allow_blank=True, default="")
    refresh_token = serializers.CharField(required=False, allow_blank=True, default="")


class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    refresh_token = serializers.CharField()
    scope = serializers.CharField()


class RevokeRequestSerializer(serializers.Serializer):
    token = serializers.CharField()
    client_id = serializers.CharField(max_length=60)
    client_secret = serializers.CharField(required=False, allow_blank=True, default="")


# --- webhooks -----------------------------------------------------------------------------------


class WebhookEndpointSerializer(serializers.ModelSerializer):
    events = serializers.ListField(child=serializers.CharField(), read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    secret_rotating = serializers.SerializerMethodField()

    class Meta:
        model = WebhookEndpoint
        fields = [
            "id", "url", "description", "events", "branch", "branch_name", "status", "source",
            "api_version", "failing_since", "disabled_at", "secret_rotating", "created_at",
        ]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_secret_rotating(self, endpoint: WebhookEndpoint) -> bool:
        from tutortrack.core.time import now

        expires = endpoint.previous_secret_expires_at
        return bool(endpoint.previous_secret and expires and expires > now())


class WebhookEndpointCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=500)
    events = serializers.ListField(child=serializers.CharField(max_length=80), min_length=1)
    description = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    branch = TenantRelatedField(Branch, required=False, allow_null=True)


class WebhookEndpointPatchSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=500, required=False)
    events = serializers.ListField(
        child=serializers.CharField(max_length=80), min_length=1, required=False
    )
    description = serializers.CharField(max_length=200, required=False, allow_blank=True)
    branch = TenantRelatedField(Branch, required=False, allow_null=True)
    status = serializers.ChoiceField(choices=ENDPOINT_TOGGLE, required=False)


class WebhookEndpointSecretSerializer(WebhookEndpointSerializer):
    secret = serializers.SerializerMethodField()

    class Meta(WebhookEndpointSerializer.Meta):
        fields = [*WebhookEndpointSerializer.Meta.fields, "secret"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_secret(self, endpoint: WebhookEndpoint) -> str:
        return str(self.context.get("secret", ""))


class SecretSerializer(serializers.Serializer):
    secret = serializers.CharField()


class WebhookAttemptSerializer(serializers.ModelSerializer):
    request_headers = serializers.DictField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = WebhookAttempt
        fields = [
            "number", "attempted_at", "status_code", "succeeded", "error", "request_headers",
            "response_snippet", "duration_ms",
        ]  # fmt: skip
        read_only_fields = fields


class WebhookDeliverySerializer(serializers.ModelSerializer):
    endpoint_url = serializers.CharField(source="endpoint.url", read_only=True)

    class Meta:
        model = WebhookDelivery
        fields = [
            "id", "endpoint", "endpoint_url", "event_id", "event_type", "status",
            "attempt_count", "last_status_code", "last_attempt_at", "delivered_at", "is_test",
            "redelivery_of", "created_at",
        ]  # fmt: skip
        read_only_fields = fields


class WebhookDeliveryDetailSerializer(WebhookDeliverySerializer):
    attempts = WebhookAttemptSerializer(many=True, read_only=True)
    body = serializers.JSONField(source="payload", read_only=True)

    class Meta(WebhookDeliverySerializer.Meta):
        fields = [*WebhookDeliverySerializer.Meta.fields, "attempts", "body"]
        read_only_fields = fields


class EventTypeSerializer(serializers.Serializer):
    key = serializers.CharField()
    aggregate = serializers.CharField()
    subject_type = serializers.CharField()
    description = serializers.CharField()
    version = serializers.IntegerField()


class EventSampleSerializer(serializers.Serializer):
    event_type = serializers.CharField()
    synthetic = serializers.BooleanField()
    body = serializers.JSONField()


# --- sandboxes, overview, marketplace -----------------------------------------------------------


class SandboxSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Sandbox
        fields = ["id", "sandbox_organisation_id", "name", "slug", "records", "url", "created_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_url(self, sandbox: Sandbox) -> str:
        from django.conf import settings

        return f"https://{sandbox.slug}.{settings.TENANT_BASE_DOMAIN}/"


class OverviewSerializer(serializers.Serializer):
    api_keys = serializers.IntegerField()
    connected_apps = serializers.IntegerField()
    webhook_endpoints = serializers.IntegerField()
    deliveries_24h = serializers.IntegerField()
    failed_24h = serializers.IntegerField()
    sandbox_of = serializers.CharField()
    rate_limit_per_minute = serializers.IntegerField()
    burst_per_second = serializers.IntegerField()


class MarketplaceEntrySerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    description = serializers.CharField()
    status = serializers.ChoiceField(choices=MARKETPLACE_STATUS)
    settings_path = serializers.CharField()
    kind = serializers.ChoiceField(choices=MARKETPLACE_KIND)
    client_id = serializers.CharField(allow_blank=True)
    homepage_url = serializers.CharField(allow_blank=True)


class ChangelogEntrySerializer(serializers.Serializer):
    released_on = serializers.DateField()
    title = serializers.CharField()
    change_kind = serializers.CharField()
    description = serializers.CharField()


def scope_rows() -> list[dict[str, Any]]:
    out = []
    for scope in scopes.ALL_SCOPES:
        resource, _sep, level = scope.partition(":")
        patterns = scopes.permission_patterns([scope])
        out.append(
            {
                "key": scope,
                "resource": resource,
                "access": level,
                "description": scopes.scope_label(scope),
                "permissions": sorted(patterns),
            }
        )
    return out
