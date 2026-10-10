"""The integration framework's persistence (E22 §2, shared with E23/E27)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class IntegrationConnection(TenantModel):
    """One connected external account: a user's (personal calendar, own Zoom) or the
    organisation's (shared Zoom, Lessonspace, later accounting). Tokens and secrets are
    encrypted at rest and never leave the backend."""

    class Level(models.TextChoices):
        USER = "user", _("Personal")
        ORGANISATION = "organisation", _("Organisation")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Connected")
        ERROR = "error", _("Error")
        NEEDS_RECONNECT = "needs_reconnect", _("Needs reconnecting")
        DISCONNECTED = "disconnected", _("Disconnected")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    level = models.CharField(max_length=12, choices=Level.choices, default=Level.USER)
    provider = models.CharField(max_length=30)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    scopes = models.JSONField(default=list, blank=True)
    access_token = EncryptedField(blank=True, default="")
    refresh_token = EncryptedField(blank=True, default="")
    secret = EncryptedField(blank=True, default="")  # app-specific password / API key
    expires_at = models.DateTimeField(null=True, blank=True)
    external_account_id = models.CharField(max_length=255, blank=True, default="")
    account_name = models.CharField(max_length=255, blank=True, default="")
    settings = models.JSONField(default=dict, blank=True)  # username, server_url, ...
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    error_at = models.DateTimeField(null=True, blank=True)
    error_count = models.PositiveIntegerField(default=0)
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    audit_sensitive_fields = frozenset({"access_token", "refresh_token", "secret"})

    class Meta(TenantModel.Meta):
        ordering = ["provider", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "user", "provider"],
                condition=Q(user__isnull=False) & ~Q(status="disconnected"),
                name="integration_user_provider_unique",
            ),
            models.UniqueConstraint(
                fields=["organisation", "provider"],
                condition=Q(user__isnull=True) & ~Q(status="disconnected"),
                name="integration_org_provider_unique",
            ),
        ]
        indexes = [models.Index(fields=["user", "provider", "status"])]

    def __str__(self) -> str:
        return f"{self.provider} ({self.account_name or self.external_account_id})"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user=user)

    @property
    def is_live(self) -> bool:
        return self.status in (self.Status.ACTIVE, self.Status.ERROR)
