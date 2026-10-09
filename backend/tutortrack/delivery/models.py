"""Cancellation policies, makeup credits, report templates and lesson reports (E09)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.models import TenantModel


class CancellationPolicy(TenantModel):
    """Rules for cancellations and attendance outcomes (FR-09-3). One organisation default
    plus overrides for a branch, service, job or client; the most specific wins.

    Editing rules creates a new version (the old row is kept, ``active=False``) so
    ``CancellationRecord.policy_snapshot`` and history stay explainable."""

    class Scope(models.TextChoices):
        ORGANISATION = "organisation", _("Organisation default")
        BRANCH = "branch", _("Branch")
        SERVICE = "service", _("Service")
        JOB = "job", _("Job")
        CLIENT = "client", _("Client")

    name = models.CharField(max_length=120)
    scope_type = models.CharField(max_length=12, choices=Scope.choices)
    scope_id = models.UUIDField(null=True, blank=True)
    rules = models.JSONField(default=dict)
    version = models.PositiveIntegerField(default=1)
    active = models.BooleanField(default=True)
    previous = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["scope_type", "name"]
        verbose_name_plural = "cancellation policies"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "scope_type", "scope_id"],
                condition=Q(active=True, scope_id__isnull=False),
                name="cancellation_policy_scope_unique",
            ),
            models.UniqueConstraint(
                fields=["organisation", "scope_type"],
                condition=Q(active=True, scope_id__isnull=True),
                name="cancellation_policy_default_unique",
            ),
        ]


class CancellationRecord(TenantModel):
    """Who cancelled a lesson, with how much notice, and what the policy decided."""

    class Kind(models.TextChoices):
        FREE = "free", _("Free cancellation")
        LATE = "late", _("Late cancellation")
        TUTOR = "tutor", _("Tutor cancellation")
        ADMIN = "admin", _("Cancelled by us")

    lesson = models.OneToOneField(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="cancellation"
    )
    cancelled_by_type = models.CharField(max_length=7)  # client/student/tutor/admin
    cancelled_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.CharField(max_length=300, blank=True, default="")
    notice_minutes = models.IntegerField()
    kind = models.CharField(max_length=5, choices=Kind.choices)
    policy = models.ForeignKey(
        CancellationPolicy, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    policy_snapshot = models.JSONField(default=dict)
    charge_percent = models.DecimalField(max_digits=5, decimal_places=2)
    pay_percent = models.DecimalField(max_digits=5, decimal_places=2)
    overridden = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=300, blank=True, default="")
    makeup_credit_issued = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]


class MakeupCredit(TenantModel):
    """Instead of a refund, a student may book a makeup lesson within ``expires_at``."""

    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        USED = "used", _("Used")
        EXPIRED = "expired", _("Expired")
        VOID = "void", _("Void")

    student = models.ForeignKey(
        "people.Student", on_delete=models.CASCADE, related_name="makeup_credits"
    )
    client = models.ForeignKey("people.Client", on_delete=models.CASCADE, related_name="+")
    source_lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.PROTECT, related_name="+"
    )
    expires_at = models.DateTimeField()
    consumed_by_lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    consumed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["expires_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_lesson", "student"], name="makeup_credit_source_unique"
            )
        ]

    def status_at(self, moment: Any) -> str:
        if self.voided_at:
            return self.Status.VOID
        if self.consumed_by_lesson_id:
            return self.Status.USED
        if self.expires_at <= moment:
            return self.Status.EXPIRED
        return self.Status.AVAILABLE


class ReportTemplate(TenantModel):
    """A lesson report form (FR-09-4). Fields live on immutable versions; reports point at
    the version they were written against."""

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default="")
    is_default = models.BooleanField(default=False)
    current_version = models.ForeignKey(
        "ReportTemplateVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    services = models.ManyToManyField("catalogue.Service", blank=True, related_name="+")
    subjects = models.ManyToManyField("catalogue.Subject", blank=True, related_name="+")
    jobs = models.ManyToManyField("jobs.Job", blank=True, related_name="+")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation"],
                condition=Q(is_default=True, archived_at__isnull=True),
                name="report_template_one_default",
            )
        ]


class ReportTemplateVersion(TenantModel):
    """``fields``: ``[{"key", "label", "type", "required", "visibility", "options",
    "help_text"}]``. Types: ``rich_text``, ``text``, ``rating``, ``select``,
    ``multi_select``, ``checklist``, ``topics``, ``homework``, ``next_steps``,
    ``attachment``. Visibility: ``staff``, ``client`` or ``student`` (who can see it;
    ``student`` implies the client too)."""

    template = models.ForeignKey(ReportTemplate, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    fields = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        ordering = ["template", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["template", "version"], name="report_template_version_unique"
            )
        ]


class LessonReport(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Not started")
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        RETURNED = "returned", _("Returned to tutor")
        APPROVED = "approved", _("Approved")

    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.CASCADE, related_name="reports"
    )
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    template_version = models.ForeignKey(
        ReportTemplateVersion, on_delete=models.PROTECT, related_name="+"
    )
    answers = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    returned_note = models.CharField(max_length=500, blank=True, default="")
    shared_at = models.DateTimeField(null=True, blank=True)
    overdue_at = models.DateTimeField(null=True, blank=True)  # when it was marked overdue
    escalated_at = models.DateTimeField(null=True, blank=True)
    pay_held = models.BooleanField(default=False)  # E12 holds the pay item

    class Meta(TenantModel.Meta):
        ordering = ["due_at"]
        constraints = [
            models.UniqueConstraint(fields=["lesson", "tutor"], name="lesson_report_unique")
        ]
        indexes = [models.Index(fields=["organisation", "status", "due_at"], name="report_due_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor__membership__user=user)

    @property
    def is_written(self) -> bool:
        return self.status in {self.Status.SUBMITTED, self.Status.APPROVED}

    def sla_state(self, moment: Any) -> str:
        """``due | overdue | submitted | approved | shared`` (FR-09-7)."""
        if self.shared_at:
            return "shared"
        if self.status == self.Status.APPROVED:
            return "approved"
        if self.status == self.Status.SUBMITTED:
            return "submitted"
        return "overdue" if self.due_at <= moment else "due"


class LessonReportComment(TenantModel):
    """Replies on a report from the client, tutor or staff (FR-09-6)."""

    class Visibility(models.TextChoices):
        STAFF = "staff", _("Staff and tutor only")
        CLIENT = "client", _("Visible to the client")

    report = models.ForeignKey(LessonReport, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    author_name = models.CharField(max_length=200)
    body = models.TextField()
    visibility = models.CharField(
        max_length=6, choices=Visibility.choices, default=Visibility.CLIENT
    )

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
