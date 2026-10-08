from django.db import models

from ..ids import new_id
from .base import TimeStampedModel


class FeatureFlag(TimeStampedModel):
    """A platform feature flag. Resolution: org override > plan (E04) > global default."""

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    key = models.SlugField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    enabled_globally = models.BooleanField(default=False)
    # Plan keys (E04) for which the flag is on, e.g. ["agency", "enterprise"].
    plan_keys = models.JSONField(default=list, blank=True)

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
