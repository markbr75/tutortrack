"""Automations: When → If → Then (E14)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.models import TenantModel


class Automation(TenantModel):
    class Trigger(models.TextChoices):
        EVENT = "event", _("When something happens")
        SCHEDULE = "schedule", _("On a schedule")
        DATE = "date", _("Relative to a date")
        MANUAL = "manual", _("Run by hand")

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    trigger_type = models.CharField(max_length=8, choices=Trigger.choices)
    # The event type for event triggers (indexed lookup when events arrive).
    trigger_key = models.CharField(max_length=80, blank=True, default="", db_index=True)
    trigger_config = models.JSONField(default=dict, blank=True)
    subject_type = models.CharField(max_length=40)
    conditions = models.JSONField(default=dict, blank=True)
    steps = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=False)
    max_runs_per_record = models.PositiveSmallIntegerField(default=1)  # per 24 hours
    recipe_key = models.CharField(max_length=60, blank=True, default="")
    webhook_secret = EncryptedField(blank=True, default="")

    audit_sensitive_fields = frozenset({"webhook_secret"})

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class AutomationVersion(TenantModel):
    """What a run executes: edits make a new version; runs keep theirs."""

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    trigger_type = models.CharField(max_length=8)
    trigger_config = models.JSONField(default=dict, blank=True)
    conditions = models.JSONField(default=dict, blank=True)
    steps = models.JSONField(default=list, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["automation", "version"], name="automation_version_unique"
            )
        ]


class AutomationRun(TenantModel):
    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        WAITING = "waiting", _("Waiting")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="runs")
    version = models.ForeignKey(AutomationVersion, on_delete=models.PROTECT, related_name="+")
    subject_type = models.CharField(max_length=40)
    subject_id = models.CharField(max_length=64, blank=True, default="")
    event_id = models.UUIDField(null=True, blank=True)
    event_type = models.CharField(max_length=80, blank=True, default="")
    run_key = models.CharField(max_length=200)  # event id, schedule date or manual id
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    causation_depth = models.PositiveSmallIntegerField(default=0)
    workflow_id = models.CharField(max_length=300, blank=True, default="", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=1)
    error = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["automation", "subject_id", "run_key"], name="automation_run_unique"
            )
        ]
        indexes = [
            models.Index(fields=["automation", "subject_id", "started_at"], name="run_record_idx")
        ]


class AutomationRunStep(TenantModel):
    class Status(models.TextChoices):
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")
        WAITING = "waiting", _("Waiting")

    run = models.ForeignKey(AutomationRun, on_delete=models.CASCADE, related_name="steps")
    step_key = models.CharField(max_length=60)  # "2", "2.then.0", ...
    step_type = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=Status.choices)
    resume_at = models.DateTimeField(null=True, blank=True)  # waits (informational)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["run", "step_key"], name="automation_step_unique")
        ]
