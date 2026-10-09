"""Communications (E13): per-organisation notification settings and templates, the message
log with delivery events, recipient preferences, suppressions and in-app notifications."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class Channel(models.TextChoices):
    EMAIL = "email", _("Email")
    SMS = "sms", _("Text message")
    IN_APP = "in_app", _("In the app")


class OrgNotificationSetting(TenantModel):
    """An organisation's choice for one notification type (absent = the type's defaults)."""

    type_key = models.CharField(max_length=60)
    enabled = models.BooleanField(default=True)
    channels = models.JSONField(default=list)  # ["email", "sms"]
    timing = models.JSONField(default=list, blank=True)  # minutes before, for reminders

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "type_key"], name="notif_setting_unique"
            )
        ]


class MessageTemplate(TenantModel):
    """An organisation's override of a type's default template for one channel. Saving
    creates a new version; the previous one is kept (``is_active=False``) for revert."""

    type_key = models.CharField(max_length=60)
    channel = models.CharField(max_length=6, choices=Channel.choices)
    locale = models.CharField(max_length=10, default="en-GB")
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["type_key", "channel", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "type_key", "channel", "locale"],
                condition=Q(is_active=True),
                name="message_template_active_unique",
            )
        ]


class Message(TenantModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        DELIVERED = "delivered", _("Delivered")
        OPENED = "opened", _("Opened")
        CLICKED = "clicked", _("Clicked")
        BOUNCED = "bounced", _("Bounced")
        COMPLAINED = "complained", _("Marked as spam")
        FAILED = "failed", _("Failed")
        SUPPRESSED = "suppressed", _("Not sent (suppressed)")

    type_key = models.CharField(max_length=60)
    channel = models.CharField(max_length=6, choices=Channel.choices)
    recipient_type = models.CharField(max_length=10)  # contact | student | tutor | user
    recipient_id = models.CharField(max_length=64)
    recipient_name = models.CharField(max_length=200, blank=True, default="")
    to = models.CharField(max_length=254)  # email address, phone number or user id
    subject = models.CharField(max_length=300, blank=True, default="")
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    error = models.CharField(max_length=500, blank=True, default="")
    provider_ref = models.CharField(max_length=120, blank=True, default="")
    related_type = models.CharField(max_length=40, blank=True, default="")  # the subject record
    related_id = models.CharField(max_length=64, blank=True, default="")
    target_type = models.CharField(max_length=40, blank=True, default="")  # timeline record
    target_id = models.CharField(max_length=64, blank=True, default="")
    dedupe_key = models.CharField(max_length=255)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    segments = models.PositiveSmallIntegerField(default=0)  # SMS parts

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "dedupe_key"], name="message_dedupe")
        ]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="message_target_idx"),
            models.Index(fields=["related_type", "related_id"], name="message_related_idx"),
        ]


class MessageEvent(TenantModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    detail = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["occurred_at"]


class CommunicationPreference(TenantModel):
    """Which channels a person accepts for a category (no row = every channel)."""

    person_type = models.CharField(max_length=10)  # contact | student | tutor | user
    person_id = models.CharField(max_length=64)
    category = models.CharField(max_length=20)
    channels = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "person_type", "person_id", "category"],
                name="comm_preference_unique",
            )
        ]


class Suppression(TenantModel):
    """Addresses we must not send to (hard bounce, spam complaint, manual)."""

    channel = models.CharField(max_length=6, choices=Channel.choices)
    address = models.CharField(max_length=254)
    reason = models.CharField(max_length=40)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "channel", "address"], name="suppression_unique"
            )
        ]


class SmsOptOut(models.Model):
    """Numbers that replied STOP to the platform's shared sender (platform-level, like
    ``payments.AccountRoute``): honoured for every organisation."""

    phone = models.CharField(max_length=32, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.phone


class InAppNotification(TenantModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type_key = models.CharField(max_length=60)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True, default="")
    link = models.CharField(max_length=300, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"], name="inapp_user_unread_idx")]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(user=user)
