"""Customer success data owned by each organisation (E30 Part 2).

* ``GuidanceState``: per member: finished/dismissed product tours, when they last read
  "What's new", and until when the NPS prompt is snoozed.
* ``SetupChecklist`` / ``SetupChecklistItem``: the dashboard's first-steps checklist
  (FR-30-5), ticked by domain events.
* ``SurveyResponse``: NPS and CSAT answers (FR-30-6).
* ``SupportConversation`` / ``SupportMessage``: built-in chat between the organisation's
  staff and TutorTrack support (FR-30-5); platform staff answer from the console.
* ``ProductEvent``: consent-gated, pseudonymous feature-usage events (FR-30-6). No PII:
  the actor is a keyed hash, properties are filtered (``analytics.clean_properties``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class GuidanceState(TenantModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    completed_tours = models.JSONField(default=list, blank=True)
    dismissed_tours = models.JSONField(default=list, blank=True)
    changelog_seen_at = models.DateTimeField(null=True, blank=True)
    nps_snoozed_until = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "user"], name="guidance_one_per_user")
        ]


class SetupChecklist(TenantModel):
    dismissed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation"], name="setup_checklist_one_per_org")
        ]

    def __str__(self) -> str:
        return "Setup checklist"


class SetupChecklistItem(TenantModel):
    class Key(models.TextChoices):
        SERVICE = "service", _("Set up a service")
        STUDENT = "student", _("Add a student")
        LESSON = "lesson", _("Schedule a lesson")
        PAYMENTS = "payments", _("Connect Stripe")
        INVOICE = "invoice", _("Send your first invoice")

    class Source(models.TextChoices):
        EVENT = "event", _("Done in the app")
        EXISTING = "existing", _("Found existing data")

    key = models.CharField(max_length=20, choices=Key.choices)
    completed_at = models.DateTimeField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.EVENT)

    class Meta(TenantModel.Meta):
        ordering = ["completed_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="setup_item_unique")
        ]

    def __str__(self) -> str:
        return f"Setup step: {self.get_key_display()}"


class SurveyResponse(TenantModel):
    class Kind(models.TextChoices):
        NPS = "nps", _("Net Promoter Score")
        CSAT = "csat", _("Customer satisfaction")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField(max_length=4, choices=Kind.choices)
    score = models.PositiveSmallIntegerField(null=True, blank=True)  # None: dismissed
    comment = models.TextField(blank=True, default="", max_length=2000)
    context = models.CharField(max_length=80, blank=True, default="")  # e.g. "support:<id>"
    role = models.CharField(max_length=20, blank=True, default="")  # role when answering

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "created_at"], name="survey_kind_created")]
        constraints = [
            models.CheckConstraint(
                condition=Q(score__isnull=True) | Q(score__lte=10), name="survey_score_range"
            )
        ]


class SupportConversation(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Waiting for TutorTrack")
        ANSWERED = "answered", _("Answered")
        CLOSED = "closed", _("Closed")

    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    page = models.CharField(max_length=200, blank=True, default="")  # where it was opened
    last_message_at = models.DateTimeField()
    customer_unread = models.BooleanField(default=False)
    support_unread = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-last_message_at", "-id"]
        indexes = [models.Index(fields=["status", "last_message_at"], name="support_conv_status")]

    def __str__(self) -> str:
        return self.subject[:50]

    @staticmethod
    def own_scope_q(user: Any) -> Q:
        return Q(opened_by=user)


class SupportMessage(TenantModel):
    conversation = models.ForeignKey(
        SupportConversation, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    from_support = models.BooleanField(default=False)
    body = models.TextField(max_length=5000)

    class Meta(TenantModel.Meta):
        ordering = ["created_at", "id"]


class ProductEvent(TenantModel):
    """A pseudonymous usage event. Never holds names, emails, ids of records or free text."""

    name = models.CharField(max_length=60)
    actor = models.CharField(max_length=32)  # keyed hash of (organisation, user)
    route = models.CharField(max_length=120, blank=True, default="")  # route pattern
    properties = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=["occurred_at", "name"], name="product_event_time_name"),
            models.Index(fields=["organisation", "occurred_at"], name="product_event_org_time"),
        ]
