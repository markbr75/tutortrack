"""Tutor pay (E12): pay profiles, pay items, expenses, pay runs, payouts, statements and
bank file exports. Amounts are ``Money``; paid items are never edited (adjustments are
new items)."""

from __future__ import annotations

from typing import ClassVar

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.crypto import EncryptedField
from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class PayMethod(models.TextChoices):
    STRIPE_CONNECT = "stripe_connect", _("Stripe (paid to their Stripe account)")
    BANK_FILE = "bank_file", _("Bank transfer (payment file)")
    MANUAL = "manual", _("Paid manually")
    EXTERNAL_PAYROLL = "external_payroll", _("Payroll provider (employees)")


class TutorPayProfile(TenantModel):
    """How and where a tutor is paid (FR-12-2). Bank details are encrypted at rest."""

    tutor = models.OneToOneField(
        "people.TutorProfile", on_delete=models.CASCADE, related_name="pay_profile"
    )
    method = models.CharField(max_length=20, choices=PayMethod.choices, default=PayMethod.MANUAL)
    currency = CurrencyField(blank=True, default="")
    payee_name = models.CharField(max_length=140, blank=True, default="")
    bank_country = models.CharField(max_length=2, blank=True, default="")
    bank_details = EncryptedField(blank=True, default="")  # JSON
    bank_hint = models.CharField(max_length=40, blank=True, default="")  # masked, for display
    vat_registered = models.BooleanField(default=False)
    vat_number = models.CharField(max_length=30, blank=True, default="")
    self_billing_agreed_at = models.DateTimeField(null=True, blank=True)
    self_billing_agreement_version = models.CharField(max_length=40, blank=True, default="")
    stripe_account_id = models.CharField(max_length=100, blank=True, default="")
    stripe_payouts_enabled = models.BooleanField(default=False)
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="For paid meetings and training",
    )  # fmt: skip

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"bank_details"})

    def __str__(self) -> str:
        return f"Pay profile for {self.tutor_id}"


class PayRun(BranchScopedModel):
    """A batch of pay for a period (FR-12-5). ``branch`` empty in ``branches`` = all."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Collecting")
        REVIEW = "review", _("Ready for review")
        APPROVED = "approved", _("Approved")
        PAYING = "paying", _("Paying out")
        PAID = "paid", _("Paid")
        PARTIALLY_FAILED = "partially_failed", _("Paid with failures")
        CANCELLED = "cancelled", _("Cancelled")

    number = models.CharField(max_length=20)
    all_branches = models.BooleanField(default=True)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    totals = models.JSONField(default=dict, blank=True)  # {currency: "amount"}
    warnings = models.JSONField(default=list, blank=True)
    approvals = models.JSONField(default=list, blank=True)  # [{user, name, at}]
    approvals_required = models.PositiveSmallIntegerField(default=1)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    workflow_id = models.CharField(max_length=200, blank=True, default="")

    class Meta(BranchScopedModel.Meta):
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "number"], name="payrun_number_unique")
        ]

    def __str__(self) -> str:
        return self.number


class Payout(TenantModel):
    """What one tutor gets from a pay run, in one currency (FR-12-7)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        PROCESSING = "processing", _("Sending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        CARRIED = "carried", _("Carried forward")

    pay_run = models.ForeignKey(PayRun, on_delete=models.CASCADE, related_name="payouts")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    amount = MoneyField()
    method = models.CharField(max_length=20, choices=PayMethod.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    reference = models.CharField(max_length=100, blank=True, default="")
    failure_reason = models.CharField(max_length=500, blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["pay_run", "tutor"]
        constraints = [
            models.UniqueConstraint(
                fields=["pay_run", "tutor", "currency"], name="payout_one_per_tutor_currency"
            )
        ]

    def __str__(self) -> str:
        return f"{self.tutor_id}: {self.amount}"


class PayItem(BranchScopedModel):
    """One line of pay (FR-12-1)."""

    class Kind(models.TextChoices):
        LESSON = "lesson", _("Lesson")
        CANCELLATION = "cancellation", _("Cancelled lesson")
        EVENT = "event", _("Meeting or training")
        CHARGE_SHARE = "charge_share", _("Share of a charge")
        EXPENSE = "expense", _("Expense")
        MILEAGE = "mileage", _("Mileage")
        BONUS = "bonus", _("Bonus")
        REFERRAL = "referral", _("Referral bonus")
        ADJUSTMENT = "adjustment", _("Adjustment")
        DEDUCTION = "deduction", _("Deduction")
        SALARY = "salary", _("Salary or fixed amount")

    class Status(models.TextChoices):
        READY = "ready", _("Ready")
        HELD = "held", _("On hold")
        IN_PAY_RUN = "in_pay_run", _("In a pay run")
        APPROVED = "approved", _("Approved")
        PAID = "paid", _("Paid")
        VOID = "void", _("Cancelled")

    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.READY)
    source_key = models.CharField(max_length=120)
    description = models.CharField(max_length=300)
    date = models.DateField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit = models.CharField(max_length=10, blank=True, default="")
    currency = CurrencyField()
    amount = MoneyField()
    hold_reasons = models.JSONField(default=list, blank=True)
    hold_note = models.CharField(max_length=300, blank=True, default="")
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lesson_tutor = models.ForeignKey(
        "scheduling.LessonTutor", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip
    pay_run = models.ForeignKey(
        PayRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="items"
    )
    payout = models.ForeignKey(
        Payout, null=True, blank=True, on_delete=models.SET_NULL, related_name="items"
    )
    expense = models.ForeignKey(
        "payroll.Expense", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "source_key"], name="payitem_source_unique"
            )
        ]
        indexes = [
            models.Index(fields=["organisation", "tutor", "status"], name="payitem_tutor_status"),
        ]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(tutor__membership__user=user)

    def __str__(self) -> str:
        return f"{self.kind} {self.amount}"


class ExpenseCategory(TenantModel):
    class Kind(models.TextChoices):
        EXPENSE = "expense", _("Expense")
        MILEAGE = "mileage", _("Mileage")

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.EXPENSE)
    account_code = models.CharField(max_length=30, blank=True, default="")
    limit_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    mileage_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    distance_unit = models.CharField(
        max_length=2, choices=[("km", "km"), ("mi", "miles")], default="mi"
    )
    rebillable_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Expense(BranchScopedModel):
    """An expense or mileage claim (FR-12-3, FR-12-4)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    date = models.DateField()
    description = models.CharField(max_length=300)
    currency = CurrencyField()
    amount = MoneyField()
    tax = MoneyField(default=0)
    distance = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    receipt = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    client = models.ForeignKey(
        "people.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    rebillable = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        "identity.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.CharField(max_length=500, blank=True, default="")
    charge_id = models.UUIDField(null=True, blank=True)  # billing.Charge when rebilled

    class Meta(BranchScopedModel.Meta):
        ordering = ["-date", "-created_at"]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(tutor__membership__user=user)

    def __str__(self) -> str:
        return self.description


class PayStatement(TenantModel):
    """A self-billing invoice (self-employed tutors who agreed to self-billing) or a
    remittance advice (FR-12-6). Self-billing numbers run per tutor."""

    class Kind(models.TextChoices):
        SELF_BILLING = "self_billing", _("Self-billing invoice")
        REMITTANCE = "remittance", _("Remittance advice")

    payout = models.OneToOneField(Payout, on_delete=models.CASCADE, related_name="statement")
    tutor = models.ForeignKey("people.TutorProfile", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=15, choices=Kind.choices)
    number = models.CharField(max_length=40)
    issued_at = models.DateTimeField()
    currency = CurrencyField()
    net = MoneyField()
    vat = MoneyField(default=0)
    total = MoneyField()
    snapshot = models.JSONField(default=dict)  # supplier/customer details as issued

    class Meta(TenantModel.Meta):
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "number"], name="paystatement_number")
        ]

    @classmethod
    def own_scope_q(cls, user: object) -> Q:
        return Q(tutor__membership__user=user)

    def __str__(self) -> str:
        return self.number


class BankFileExport(TenantModel):
    """A bank payment file generated for a pay run (FR-12-7)."""

    pay_run = models.ForeignKey(PayRun, on_delete=models.CASCADE, related_name="bank_files")
    format = models.CharField(max_length=20)
    filename = models.CharField(max_length=120)
    content = EncryptedField()  # contains bank details
    payout_count = models.PositiveIntegerField()
    total = models.JSONField(default=dict)
    generated_by = models.ForeignKey(
        "identity.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"content"})

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.filename


class PayrollOriginator(TenantModel):
    """The organisation's own account that pays tutors, for bank files (one per org)."""

    name = models.CharField(max_length=140, blank=True, default="")
    bank_details = EncryptedField(blank=True, default="")  # JSON
    bank_hint = models.CharField(max_length=40, blank=True, default="")

    audit_sensitive_fields: ClassVar[frozenset[str]] = frozenset({"bank_details"})

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["organisation"], name="payroll_originator_one")
        ]

    def __str__(self) -> str:
        return self.name
