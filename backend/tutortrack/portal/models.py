"""Announcements (news posts) for the portals (E15-T07) and guardian-managed student logins
(FR-15-1, gap batch G2)."""

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

    def __str__(self) -> str:
        return self.title


class StudentLogin(TenantModel):
    """A guardian-managed portal login for a student under 13 (FR-15-1): a username and a
    PIN or password set by the guardian, no email needed. The login is a ``User`` with an
    undeliverable placeholder address (``MANAGED_EMAIL_DOMAIN``); it signs in at
    ``/auth/student-login`` on the organisation's own address. COPPA/AADC: it exists only
    once parental consent is on record (``privacy.children``)."""

    student = models.OneToOneField(
        "people.Student", on_delete=models.CASCADE, related_name="managed_login"
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="managed_student_login"
    )
    username = models.CharField(max_length=40)
    managed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    pin_changed_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["username"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "username"], name="student_login_username_unique"
            )
        ]

    def __str__(self) -> str:
        return self.username
