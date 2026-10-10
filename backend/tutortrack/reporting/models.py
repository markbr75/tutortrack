"""Reporting (E26): fact tables, daily aggregates, FX rates, dashboards, saved and scheduled
reports and their runs.

Fact rows are *derived* data: ``facts.py`` rebuilds a row from its source record whenever a
domain event says the source changed (FR-26-7), so reports aggregate one narrow, indexed
table instead of joining the operational ones. References to other apps' records are
foreign keys without database constraints (``db_constraint=False``): facts never block
or cascade into operational data, and a row whose source disappears is deleted on the next
refresh.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel
from tutortrack.core.models.base import TimeStampedModel, UUIDModel


def _ref(model: str, **kwargs: Any) -> Any:
    """A reference to another app's record that never constrains or cascades."""
    return models.ForeignKey(
        model,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
        **kwargs,
    )


def _tutor_ids(user: Any) -> Any:
    from tutortrack.people.models import TutorProfile

    return TutorProfile.objects.filter(membership__user=user).values("pk")


# --- facts (T01) ---------------------------------------------------------------------------------


class FactLesson(BranchScopedModel):
    """One row per lesson and tutor (a lesson without a tutor has one row with no tutor).
    ``primary`` marks the first row of each lesson, which also carries the lesson's revenue,
    so counting or summing revenue over ``primary`` rows never double counts."""

    key = models.CharField(max_length=80)  # "<lesson>:<tutor or ->"
    lesson = _ref("scheduling.Lesson")
    tutor = _ref("people.TutorProfile")
    job = _ref("jobs.Job")
    service = _ref("catalogue.Service")
    subject = _ref("catalogue.Subject")
    location = _ref("catalogue.Location")
    primary = models.BooleanField(default=True)
    date = models.DateField()  # in the organisation's timezone
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=10)
    cancelled_by = models.CharField(max_length=10, blank=True, default="")
    minutes = models.PositiveIntegerField(default=0)  # scheduled
    delivered_minutes = models.PositiveIntegerField(default=0)  # completed lessons only
    attendees = models.PositiveSmallIntegerField(default=0)
    present = models.PositiveSmallIntegerField(default=0)
    absent = models.PositiveSmallIntegerField(default=0)
    unconfirmed = models.BooleanField(default=False)
    currency = CurrencyField(blank=True, default="")
    revenue = MoneyField(default=0)  # attendees' charges (primary row only)
    pay = MoneyField(default=0)  # this tutor's pay

    class Meta(BranchScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "key"], name="fact_lesson_key_unique")
        ]
        indexes = [
            models.Index(fields=["organisation", "date"], name="fact_lesson_date_idx"),
            models.Index(fields=["organisation", "tutor", "date"], name="fact_lesson_tutor_idx"),
            models.Index(fields=["organisation", "lesson"], name="fact_lesson_lesson_idx"),
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor_id__in=_tutor_ids(user))


class FactCharge(BranchScopedModel):
    charge = _ref("billing.Charge")
    invoice = _ref("billing.Invoice")
    client = _ref("people.Client")
    student = _ref("people.Student")
    tutor = _ref("people.TutorProfile")
    job = _ref("jobs.Job")
    lesson = _ref("scheduling.Lesson")
    service = _ref("catalogue.Service")
    subject = _ref("catalogue.Subject")
    date = models.DateField()
    kind = models.CharField(max_length=20)
    status = models.CharField(max_length=10)
    currency = CurrencyField()
    net = MoneyField(default=0)
    tax = MoneyField(default=0)
    gross = MoneyField(default=0)

    class Meta(BranchScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "charge"], name="fact_charge_unique")
        ]
        indexes = [models.Index(fields=["organisation", "date"], name="fact_charge_date_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor_id__in=_tutor_ids(user))


class FactPayment(BranchScopedModel):
    payment = _ref("payments.Payment")
    client = _ref("people.Client")
    date = models.DateField()
    method = models.CharField(max_length=14)
    provider = models.CharField(max_length=10)
    status = models.CharField(max_length=18)
    currency = CurrencyField()
    amount = MoneyField(default=0)
    refunded = MoneyField(default=0)
    fee = MoneyField(default=0)

    class Meta(BranchScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "payment"], name="fact_payment_unique")
        ]
        indexes = [models.Index(fields=["organisation", "date"], name="fact_payment_date_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(pk__in=[])  # payments belong to clients, not to tutors


class FactPayItem(BranchScopedModel):
    pay_item = _ref("payroll.PayItem")
    tutor = _ref("people.TutorProfile")
    lesson = _ref("scheduling.Lesson")
    job = _ref("jobs.Job")
    service = _ref("catalogue.Service")
    pay_run = _ref("payroll.PayRun")
    date = models.DateField()
    kind = models.CharField(max_length=15)
    status = models.CharField(max_length=12)
    currency = CurrencyField()
    amount = MoneyField(default=0)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta(BranchScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "pay_item"], name="fact_pay_item_unique"
            )
        ]
        indexes = [models.Index(fields=["organisation", "date"], name="fact_pay_item_date_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(tutor_id__in=_tutor_ids(user))


class DailyAggregate(BranchScopedModel):
    """Per branch, day and currency totals, recomputed from the facts of that day whenever
    one of them changes (FR-26-7). Counts live on the row with an empty currency."""

    date = models.DateField()
    currency = models.CharField(max_length=3, blank=True, default="")
    lessons_completed = models.PositiveIntegerField(default=0)
    lessons_cancelled = models.PositiveIntegerField(default=0)
    lessons_planned = models.PositiveIntegerField(default=0)
    delivered_minutes = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    collected = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    pay_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta(BranchScopedModel.Meta):
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "branch", "date", "currency"], name="daily_aggregate_unique"
            )
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(pk__in=[])  # organisation-wide totals


class FxRate(UUIDModel, TimeStampedModel):
    """A daily exchange rate (platform data, not tenant data): 1 ``base`` = ``rate`` quote."""

    date = models.DateField()
    base = models.CharField(max_length=3)
    quote = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    source = models.CharField(max_length=20, default="ecb")

    class Meta:
        ordering = ["-date", "quote"]
        constraints = [
            models.UniqueConstraint(fields=["date", "base", "quote"], name="fx_rate_unique")
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.base}/{self.quote} {self.rate}"


# --- dashboards (T02, T03) -----------------------------------------------------------------------


class DashboardLayout(TenantModel):
    """A user's own dashboard: ``widgets`` is an ordered list of
    ``{"widget": key, "size": "s"|"m"|"l"}`` (FR-26-1)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    widgets = models.JSONField(default=list)

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation", "user"], name="dashboard_one_per_user")
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(user=user)


# --- saved and scheduled reports (T07) -----------------------------------------------------------


class SavedReport(TenantModel):
    """A report with its filters, saved as a named view (FR-26-2)."""

    name = models.CharField(max_length=120)
    report_key = models.CharField(max_length=60)
    params = models.JSONField(default=dict, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    shared = models.BooleanField(default=False)  # visible to staff who may run the report

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(owner=user) | Q(shared=True)


class ScheduledReport(TenantModel):
    """Email a saved report to staff on a schedule (FR-26-4); a Temporal Schedule per row."""

    class Frequency(models.TextChoices):
        DAILY = "daily", _("Daily")
        WEEKLY = "weekly", _("Weekly")
        MONTHLY = "monthly", _("Monthly")

    class Format(models.TextChoices):
        CSV = "csv", _("CSV")
        XLSX = "xlsx", _("Excel")
        PDF = "pdf", _("PDF")

    saved_report = models.ForeignKey(
        SavedReport, on_delete=models.CASCADE, related_name="schedules"
    )
    frequency = models.CharField(max_length=7, choices=Frequency.choices)
    weekday = models.PositiveSmallIntegerField(default=0)  # Monday = 0 (weekly)
    day_of_month = models.PositiveSmallIntegerField(default=1)  # 1-28 (monthly)
    time = models.TimeField()
    format = models.CharField(max_length=4, choices=Format.choices, default=Format.CSV)
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+")
    enabled = models.BooleanField(default=True)
    schedule_id = models.CharField(max_length=255, blank=True, default="")
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.saved_report_id} {self.frequency}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(saved_report__owner=user)


class ReportRun(TenantModel):
    """One export of a report: on demand (no file kept) or scheduled (file in storage)."""

    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        COMPLETED = "completed", _("Completed")
        DELIVERED = "delivered", _("Delivered")
        FAILED = "failed", _("Failed")

    report_key = models.CharField(max_length=60)
    params = models.JSONField(default=dict, blank=True)
    format = models.CharField(max_length=4, choices=ScheduledReport.Format.choices)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.RUNNING)
    run_key = models.CharField(max_length=255, blank=True, default="")  # dedupes retries
    scheduled_report = models.ForeignKey(
        ScheduledReport, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    file = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    row_count = models.PositiveIntegerField(default=0)
    recipients = models.JSONField(default=list, blank=True)  # emails it went to
    error = models.CharField(max_length=500, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "run_key"],
                condition=~Q(run_key=""),
                name="report_run_key_unique",
            )
        ]

    def __str__(self) -> str:
        return f"{self.report_key} {self.format}"

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(requested_by=user)
