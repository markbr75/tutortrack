"""Announcements (news posts) for the portals (E15-T07)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class Announcement(TenantModel):
    class Audience(models.TextChoices):
        CLIENTS = "clients", _("Families")
        TUTORS = "tutors", _("Tutors")
        EVERYONE = "everyone", _("Everyone")

    title = models.CharField(max_length=200)
    body = models.TextField()
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.EVERYONE)
    branch = models.ForeignKey(
        "tenancy.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    published_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-published_at"]
