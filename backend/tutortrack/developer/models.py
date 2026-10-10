"""Developer platform (E27): API keys, OAuth2 apps and tokens, outbound webhooks, sandboxes.

Two tables are platform-level (no ``organisation`` column, no RLS), like
``payments.AccountRoute``: they are read *before* a tenant is known.

* ``CredentialRoute``: which organisation a token prefix belongs to. The bearer token's
  prefix is looked up here, then the credential itself is read inside that tenant.
* ``OAuthApplication``: a client is identified by ``client_id`` on the token endpoint and
  the consent screen; partner apps (Zapier, Make) serve every organisation. Apps a tenant
  registers carry ``owner_organisation_id`` and are filtered to it in the selectors.

Everything else is tenant data with row-level security.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel, TimeStampedModel, UUIDModel


class CredentialKind(models.TextChoices):
    API_KEY = "api_key", _("API key")
    ACCESS_TOKEN = "access", _("OAuth access token")
    REFRESH_TOKEN = "refresh", _("OAuth refresh token")
    AUTH_CODE = "code", _("OAuth authorisation code")


class CredentialRoute(models.Model):
    """Platform-level routing: token prefix → organisation (read before any tenant)."""

    prefix = models.CharField(max_length=24, unique=True)
    kind = models.CharField(max_length=8, choices=CredentialKind.choices)
    organisation_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.kind}:{self.prefix}"


class ApiKey(TenantModel):
    """An organisation API key (FR-27-2). Requests act as ``user`` (who created it) with
    permissions narrowed to ``scopes``; optionally restricted to one branch."""

    name = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    prefix = models.CharField(max_length=24, unique=True)
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    ip_allowlist = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)
    rate_limit_per_minute = models.PositiveIntegerField(null=True, blank=True)
    rotated_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    audit_sensitive_fields = frozenset({"secret_hash"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class OAuthApplication(UUIDModel, TimeStampedModel):
    """An OAuth2 client (authorisation code + PKCE). Platform-level; see module docstring."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    homepage_url = models.URLField(blank=True, default="")
    logo_url = models.URLField(blank=True, default="")
    client_id = models.CharField(max_length=40, unique=True)
    client_secret_hash = models.CharField(max_length=64, blank=True, default="")
    confidential = models.BooleanField(default=True)
    redirect_uris = models.JSONField(default=list)
    allowed_scopes = models.JSONField(default=list)
    # None: a partner app (any organisation may connect it); else the owning tenant.
    owner_organisation_id = models.UUIDField(null=True, blank=True, db_index=True)
    partner_key = models.CharField(max_length=30, blank=True, default="")  # zapier, make
    published = models.BooleanField(default=False)  # listed in the marketplace
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    revoked_at = models.DateTimeField(null=True, blank=True)

    audit_sensitive_fields = frozenset({"client_secret_hash"})

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OAuthGrant(TenantModel):
    """A connected app: a user's consent for an application in this organisation."""

    application = models.ForeignKey(
        OAuthApplication, on_delete=models.CASCADE, related_name="grants"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    scopes = models.JSONField(default=list)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class OAuthToken(TenantModel):
    """Authorisation codes, access tokens and refresh tokens (hashed)."""

    grant = models.ForeignKey(OAuthGrant, on_delete=models.CASCADE, related_name="tokens")
    kind = models.CharField(max_length=8, choices=CredentialKind.choices)
    prefix = models.CharField(max_length=24, unique=True)
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)  # codes and rotated refresh tokens
    redirect_uri = models.URLField(max_length=500, blank=True, default="")
    code_challenge = models.CharField(max_length=128, blank=True, default="")
    code_challenge_method = models.CharField(max_length=8, blank=True, default="")

    audit_sensitive_fields = frozenset({"secret_hash", "code_challenge"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class WebhookEndpoint(TenantModel):
    """Where to POST signed event notifications (FR-27-3)."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused")
        DISABLED = "disabled", _("Disabled after failures")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Added by hand")
        API = "api", _("Added through the API")
        ZAPIER = "zapier", _("Zapier")
        MAKE = "make", _("Make")

    url = models.URLField(max_length=500)
    description = models.CharField(max_length=200, blank=True, default="")
    events = models.JSONField(default=list)  # event types or "<aggregate>.*"
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    api_version = models.CharField(max_length=20)
    secret = EncryptedField()
    previous_secret = EncryptedField(blank=True, default="")
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)
    failing_since = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    audit_sensitive_fields = frozenset({"secret", "previous_secret"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.url


class WebhookDelivery(TenantModel):
    """One event for one endpoint; retried by ``WebhookDeliveryWorkflow`` (FR-27-3)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        RETRYING = "retrying", _("Retrying")
        SUCCEEDED = "succeeded", _("Delivered")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_id = models.UUIDField()
    event_type = models.CharField(max_length=80)
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=False)
    redelivery_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "event_id"],
                condition=models.Q(redelivery_of__isnull=True, is_test=False),
                name="webhook_delivery_once_per_event",
            )
        ]
        indexes = [models.Index(fields=["endpoint", "created_at"], name="webhook_delivery_log_idx")]


class WebhookAttempt(TenantModel):
    """One HTTP attempt of a delivery (the delivery log)."""

    delivery = models.ForeignKey(WebhookDelivery, on_delete=models.CASCADE, related_name="attempts")
    number = models.PositiveSmallIntegerField()
    attempted_at = models.DateTimeField()
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    error = models.CharField(max_length=500, blank=True, default="")
    request_headers = models.JSONField(default=dict)
    response_snippet = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["delivery", "number"], name="webhook_attempt_unique")
        ]


class Sandbox(TenantModel):
    """A sandbox organisation created from this one (FR-27-6)."""

    sandbox_organisation_id = models.UUIDField(unique=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63)
    records = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
