from django.db import models

from .base import TenantModel


class WorkflowLink(TenantModel):
    """A durable process (Temporal workflow) linked to the record it is about (E32 §5).

    Written when the workflow starts and kept current by its activities, so the API can
    list a record's processes without asking Temporal on every page view.
    """

    class Status(models.TextChoices):
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"
        TERMINATED = "terminated"
        TIMED_OUT = "timed_out"

    workflow_id = models.CharField(max_length=255)
    run_id = models.CharField(max_length=64, blank=True, default="")
    workflow_type = models.CharField(max_length=100)
    process = models.CharField(max_length=60, db_index=True)
    task_queue = models.CharField(max_length=40, default="default")
    subject_type = models.CharField(max_length=60, blank=True, default="")
    subject_id = models.CharField(max_length=64, blank=True, default="")
    branch_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    current_step = models.CharField(max_length=60, blank=True, default="")
    input = models.JSONField(default=dict, blank=True)  # ids only (restart after failure)
    started_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "workflow_id"], name="workflow_link_unique"
            )
        ]
        indexes = [
            models.Index(
                fields=["organisation", "subject_type", "subject_id"], name="workflow_link_subject"
            )
        ]

    def __str__(self) -> str:
        return self.workflow_id


class ScheduleLink(TenantModel):
    """A per-organisation Temporal Schedule (E32 FR-32-7), so an organisation's schedules
    can be paused or deleted together (suspension, closure)."""

    schedule_id = models.CharField(max_length=255)
    process = models.CharField(max_length=60)
    paused = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "schedule_id"], name="schedule_link_unique"
            )
        ]

    def __str__(self) -> str:
        return self.schedule_id
