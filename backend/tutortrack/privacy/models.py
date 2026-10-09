"""Consent management (E29 FR-29-3)."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class ConsentType(TenantModel):
    """Something an organisation asks consent for (configurable per org, versioned)."""

    class Category(models.TextChoices):
        DATA_PROCESSING = "data_processing", _("Data processing")
        PHOTO_VIDEO = "photo_video", _("Photos and video")
        MARKETING_EMAIL = "marketing_email", _("Marketing email")
        MARKETING_SMS = "marketing_sms", _("Marketing SMS")
        LESSON_RECORDING = "lesson_recording", _("Lesson recording")
        TERMS = "terms_of_service", _("Terms of service")
        PRIVACY_POLICY = "privacy_policy", _("Privacy policy")
        OTHER = "other", _("Other")

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=30, choices=Category.choices)
    version = models.PositiveIntegerField(default=1)
    document_url = models.URLField(blank=True, default="")
    required = models.BooleanField(default=False)
    # Subject types it applies to, e.g. ["people.contact", "people.student", "identity.user"].
    applies_to = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="consent_type_key_unique")
        ]

    def __str__(self) -> str:
        return self.name


class ConsentRecord(TenantModel):
    """One grant or withdrawal. Append-only: the latest record per (subject, type) is the
    current state, and the history is the evidence."""

    class Method(models.TextChoices):
        FORM = "form", _("Public form")
        PORTAL = "portal", _("Portal")
        IMPORT = "import", _("Import")
        STAFF = "staff", _("Recorded by staff")
        SIGNUP = "signup", _("Signup")

    consent_type = models.ForeignKey(ConsentType, on_delete=models.PROTECT, related_name="records")
    version = models.PositiveIntegerField()
    subject_type = models.CharField(max_length=60)
    subject_id = models.CharField(max_length=64)
    granted = models.BooleanField()
    method = models.CharField(max_length=10, choices=Method.choices)
    given_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    given_by_name = models.CharField(max_length=200, blank=True, default="")
    on_behalf_of_child = models.BooleanField(default=False)  # a guardian consenting for a child
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    recorded_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["-recorded_at", "-id"]
        indexes = [
            models.Index(
                fields=[
                    "organisation",
                    "subject_type",
                    "subject_id",
                    "consent_type",
                    "-recorded_at",
                ],
                name="consent_record_subject",
            )
        ]

    def __str__(self) -> str:
        return f"{self.consent_type_id} {'granted' if self.granted else 'withdrawn'}"
