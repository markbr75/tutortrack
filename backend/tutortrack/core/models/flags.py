from django.db import models

from ..ids import new_id
from .base import TimeStampedModel


class FeatureFlag(TimeStampedModel):
    """A platform feature flag. Resolution: org override > plan (E04) > percentage rollout
    (E30, stable per organisation) > global default."""

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    key = models.SlugField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    enabled_globally = models.BooleanField(default=False)
    # Plan keys (E04) for which the flag is on, e.g. ["agency", "enterprise"].
    plan_keys = models.JSONField(default=list, blank=True)
    # Turn the flag on for this share of organisations (E30); 0 = off, 100 = everyone.
    rollout_percent = models.PositiveSmallIntegerField(default=0)

    def __str__(self) -> str:
        return self.key


class FeatureFlagOverride(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    flag = models.ForeignKey(FeatureFlag, on_delete=models.CASCADE, related_name="overrides")
    organisation = models.ForeignKey(
        "tenancy.Organisation", on_delete=models.CASCADE, related_name="+"
    )
    enabled = models.BooleanField()
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["flag", "organisation"], name="flag_override_unique")
        ]

    def __str__(self) -> str:
        return f"{self.flag_id} @ {self.organisation_id} = {self.enabled}"


class PlatformNotice(TimeStampedModel):
    """A banner shown in every app during an incident or planned maintenance (E30 FR-30-3).
    Platform data: no tenant."""

    class Severity(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Degraded service"
        OUTAGE = "outage", "Outage"

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    message = models.CharField(max_length=500)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.INFO)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "identity.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self) -> str:
        return self.message[:50]
