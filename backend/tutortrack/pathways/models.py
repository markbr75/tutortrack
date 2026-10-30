"""Pathways (E34 FR-34-1, ADR 0048): processes a business sets for someone else to follow.

A ``PathwayTemplate`` is versioned: each save that changes the stages adds a
``PathwayTemplateVersion``, and a ``PathwayRun`` keeps the version it started with. A run's
``PathwayStep`` rows are made when it starts (status ``waiting``) and open a stage at a time.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import BranchScopedModel, TenantModel


class PathwayTemplate(TenantModel):
    class Kind(models.TextChoices):
        APPLY = "apply", _("Apply for a job")
        JOIN = "join", _("Join a job")
        FINISH = "finish", _("Finish a job")
        CUSTOM = "custom", _("Custom")

    key = models.SlugField(max_length=60)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUSTOM)
    subject_type = models.CharField(max_length=40)  # an automations record type, e.g. "job"
    builtin_key = models.CharField(max_length=60, blank=True, default="")  # E34 T02
    edited = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    current_version = models.ForeignKey(
        "PathwayTemplateVersion", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip

    class Meta(TenantModel.Meta):
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="pathway_template_key")
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def stages(self) -> list[dict[str, Any]]:
        return self.current_version.stages if self.current_version else []


class PathwayTemplateVersion(TenantModel):
    template = models.ForeignKey(PathwayTemplate, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    stages = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        ordering = ("template", "-version")
        constraints = [
            models.UniqueConstraint(fields=["template", "version"], name="pathway_version_unique")
        ]


class PathwayRun(BranchScopedModel):
    class Status(models.TextChoices):
        RUNNING = "running", _("In progress")
        COMPLETED = "completed", _("Completed")
        REJECTED = "rejected", _("Turned down")
        CANCELLED = "cancelled", _("Cancelled")

    class Participant(models.TextChoices):
        TUTOR = "tutor", _("Tutor")

    template = models.ForeignKey(PathwayTemplate, on_delete=models.PROTECT, related_name="runs")
    version = models.ForeignKey(PathwayTemplateVersion, on_delete=models.PROTECT, related_name="+")
    subject_type = models.CharField(max_length=40)
    subject_id = models.CharField(max_length=64)
    participant_type = models.CharField(
        max_length=10, choices=Participant.choices, default=Participant.TUTOR
    )
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.CASCADE,
        related_name="pathway_runs",
    )  # fmt: skip
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    stage = models.CharField(max_length=40, blank=True, default="")
    gates = models.JSONField(default=list, blank=True)  # gates reached, in order
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ("-started_at",)
        indexes = [models.Index(fields=["subject_type", "subject_id"], name="pathway_run_subject")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor__membership__user=user) | Q(owner=user)

    @property
    def workflow_id(self) -> str:
        from .processes import run_workflow_id

        return run_workflow_id(self.organisation_id, self.pk)

    @property
    def finished(self) -> bool:
        return self.status != self.Status.RUNNING


class PathwayStep(TenantModel):
    class Status(models.TextChoices):
        WAITING = "waiting", _("Not started")
        OPEN = "open", _("To do")
        REVIEW = "review", _("Waiting for review")
        DONE = "done", _("Done")
        SKIPPED = "skipped", _("Skipped")
        REJECTED = "rejected", _("Turned down")

    class Assignee(models.TextChoices):
        PARTICIPANT = "participant", _("The tutor")
        STAFF = "staff", _("Staff")
        FAMILY = "family", _("The family")
        SYSTEM = "system", _("TutorTrack")

    run = models.ForeignKey(PathwayRun, on_delete=models.CASCADE, related_name="steps")
    stage = models.CharField(max_length=40)
    key = models.CharField(max_length=40)
    position = models.PositiveSmallIntegerField()
    type = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    assignee = models.CharField(max_length=12, choices=Assignee.choices)
    role = models.CharField(max_length=40, blank=True, default="")  # staff steps: a role key
    config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    due_days = models.PositiveSmallIntegerField(null=True, blank=True)  # after the step opens
    opened_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    overdue_at = models.DateTimeField(null=True, blank=True)  # when the overdue notice went
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    result = models.JSONField(default=dict, blank=True)  # what the step recorded
    reason = models.TextField(blank=True, default="")  # skipped, returned or turned down

    class Meta(TenantModel.Meta):
        ordering = ("run", "position")
        constraints = [
            models.UniqueConstraint(fields=["run", "key"], name="pathway_step_key_unique")
        ]

    @property
    def is_closed(self) -> bool:
        return self.status in (self.Status.DONE, self.Status.SKIPPED, self.Status.REJECTED)
