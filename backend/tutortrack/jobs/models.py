"""Jobs: the ongoing engagement for a client's student(s) (E07)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, RateField
from tutortrack.core.models import BranchScopedModel, TenantModel
from tutortrack.people.models import CustomisableModel


def _tutor_on_job(user: Any, prefix: str = "") -> Q:
    """Jobs (or rows reached through ``prefix``) where ``user`` is an offered/active tutor."""
    return Q(
        **{
            f"{prefix}tutors__tutor__membership__user": user,
            f"{prefix}tutors__status__in": [JobTutor.Status.OFFERED, JobTutor.Status.ACTIVE],
        }
    )


class Job(BranchScopedModel, CustomisableModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SEEKING_TUTOR = "seeking_tutor", _("Seeking tutor")
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    class BillingMethod(models.TextChoices):
        PAYG = "pay_as_you_go", _("Pay as you go")
        PREPAID = "prepaid_credit", _("Prepaid credit")
        PACKAGE = "package", _("Package")
        RECURRING = "recurring_fixed", _("Recurring fixed fee")

    class CapPeriod(models.TextChoices):
        WEEK = "week", _("Per week")
        MONTH = "month", _("Per month")
        TOTAL = "total", _("In total")

    reference = models.CharField(max_length=20, editable=False)
    name = models.CharField(max_length=200)
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="jobs")
    bill_to = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="Another client pays (e.g. a school or local authority).",
    )  # fmt: skip
    service = models.ForeignKey("catalogue.Service", on_delete=models.PROTECT, related_name="+")
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    currency = CurrencyField()
    charge_rate = RateField(null=True, blank=True)  # overrides the service rate
    billing_method = models.CharField(
        max_length=16, choices=BillingMethod.choices, default=BillingMethod.PAYG
    )
    package_template = models.ForeignKey(
        "catalogue.PackageTemplate", null=True, blank=True, on_delete=models.PROTECT,
        related_name="+",
    )  # fmt: skip
    po_number = models.CharField(max_length=60, blank=True, default="")
    default_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    location = models.ForeignKey(
        "catalogue.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    online = models.BooleanField(default=False)
    meeting_provider = models.CharField(max_length=20, blank=True, default="")  # E22
    default_schedule = models.JSONField(default=list, blank=True)  # [{weekday, time}], E08
    start_date = models.DateField(null=True, blank=True)
    expected_end_date = models.DateField(null=True, blank=True)
    lessons_per_week = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    expected_total_hours = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    goals = models.TextField(blank=True, default="")
    notes_internal = models.TextField(blank=True, default="")
    notes_for_tutor = models.TextField(blank=True, default="")
    notes_for_client = models.TextField(blank=True, default="")
    account_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    hours_cap = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    hours_cap_period = models.CharField(
        max_length=5, choices=CapPeriod.choices, default=CapPeriod.TOTAL
    )
    # Overrides of org policies, filled in by E09 (cancellation policy, report template).
    policy_overrides = models.JSONField(default=dict, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "reference"], name="job_reference_unique"
            ),
            models.CheckConstraint(
                condition=Q(charge_rate_amount__isnull=True) | Q(charge_rate_amount__gte=0),
                name="job_charge_rate_non_negative",
            ),
        ]
        indexes = [models.Index(fields=["organisation", "status"], name="job_status_idx")]

    def __str__(self) -> str:
        return f"{self.reference} {self.name}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _tutor_on_job(user)


class JobStudent(TenantModel):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="students")
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="job_links"
    )
    currency = CurrencyField()
    charge_rate_override = RateField(null=True, blank=True, currency_field="currency")
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["job", "student"], name="job_student_unique")
        ]


class JobTutor(TenantModel):
    class Role(models.TextChoices):
        LEAD = "lead", _("Lead")
        ASSISTANT = "assistant", _("Assistant")

    class Status(models.TextChoices):
        OFFERED = "offered", _("Offered")
        ACTIVE = "active", _("Active")
        ENDED = "ended", _("Ended")
        DECLINED = "declined", _("Declined")

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="tutors")
    tutor = models.ForeignKey(
        "people.TutorProfile", on_delete=models.PROTECT, related_name="job_links"
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.LEAD)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    currency = CurrencyField()
    pay_rate_override = RateField(null=True, blank=True, currency_field="currency")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
        constraints = [
            # A tutor holds at most one current (offered/active) place on a job.
            models.UniqueConstraint(
                fields=["job", "tutor"],
                condition=Q(status__in=["offered", "active"]),
                name="job_tutor_current_unique",
            )
        ]


class JobStatusHistory(TenantModel):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=15, blank=True, default="")
    to_status = models.CharField(max_length=15)
    reason = models.CharField(max_length=300, blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]
