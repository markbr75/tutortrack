"""Organisation (the tenant). E01 ships the minimal model the core primitives need; E02
adds branches, settings, domains, onboarding and lifecycle."""

from django.db import models

from tutortrack.core.fields import CurrencyField
from tutortrack.core.ids import new_id
from tutortrack.core.models import TimeStampedModel


class Organisation(TimeStampedModel):
    class Status(models.TextChoices):
        TRIAL = "trial"
        ACTIVE = "active"
        PAST_DUE = "past_due"
        SUSPENDED = "suspended"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    default_currency = CurrencyField(default="GBP")
    timezone = models.CharField(max_length=64, default="Europe/London")
    locale = models.CharField(max_length=10, default="en-GB")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_operational(self) -> bool:
        """Whether background jobs should run for this organisation."""
        return self.status in {self.Status.TRIAL, self.Status.ACTIVE, self.Status.PAST_DUE}
