"""Client billing (E10): an append-only ledger, charges, invoices, credit notes, payment
requests and invoice runs. Money is ``Decimal`` in each record's currency."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


class ImmutableRecord(Exception):
    pass


class ClientLedgerEntry(TenantModel):
    """One movement on a client's account. Positive amounts increase what the client owes
    (invoices, refunds); negative amounts reduce it (payments, credit notes, write-offs).
    The balance is the sum of entries. Entries are never updated or deleted."""

    class Type(models.TextChoices):
        INVOICE = "invoice", _("Invoice")
        INVOICE_VOID = "invoice_void", _("Invoice voided")
        PAYMENT = "payment", _("Payment")
        CREDIT_NOTE = "credit_note", _("Credit note")
        REFUND = "refund", _("Refund")
        PAYMENT_REQUEST_PAYMENT = "payment_request_payment", _("Credit top-up")
        ADJUSTMENT = "adjustment", _("Adjustment")
        WRITE_OFF = "write_off", _("Write-off")
        PACKAGE_PURCHASE = "package_purchase", _("Package purchase")

    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    type = models.CharField(max_length=24, choices=Type.choices)
    currency = CurrencyField()
    amount = MoneyField()
    balance_after = MoneyField()
    ref_type = models.CharField(max_length=30, blank=True, default="")
    ref_id = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=300, blank=True, default="")
    occurred_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["occurred_at", "created_at", "id"]
        verbose_name_plural = "client ledger entries"
        indexes = [
            models.Index(fields=["client", "currency", "occurred_at"], name="ledger_client_idx")
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ImmutableRecord("Ledger entries are never changed; post an adjustment.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ImmutableRecord("Ledger entries are never deleted; post an adjustment.")


class Charge(BranchScopedModel):
    """A billable line awaiting (or on) an invoice (FR-10-2)."""

    class Kind(models.TextChoices):
        LESSON = "lesson", _("Lesson")
        ADVANCE = "advance", _("Lesson (invoiced in advance)")
        LATE_CANCELLATION = "late_cancellation", _("Late cancellation fee")
        RECONCILIATION = "reconciliation", _("Adjustment for a changed lesson")
        AD_HOC = "ad_hoc", _("One-off charge")

    class Status(models.TextChoices):
        UNINVOICED = "uninvoiced", _("Not invoiced")
        INVOICED = "invoiced", _("Invoiced")
        VOID = "void", _("Void")

    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lesson_attendee = models.ForeignKey(
        "scheduling.LessonAttendee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    product = models.ForeignKey(
        "catalogue.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    source_key = models.CharField(max_length=120)  # idempotency: one charge per source
    description = models.CharField(max_length=300)
    date = models.DateField()
    currency = CurrencyField()
    quantity = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    unit = models.CharField(max_length=20, blank=True, default="")
    unit_price = MoneyField(decimal_places=4)
    tax_rate = models.ForeignKey(
        "catalogue.TaxRate", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    net = MoneyField()
    tax = MoneyField()
    gross = MoneyField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNINVOICED)
    invoice = models.ForeignKey(
        "Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="charges"
    )
    category = models.CharField(max_length=60, blank=True, default="")
    tutor = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tutor_share = MoneyField(null=True, blank=True)  # E12 pays this to the tutor
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "source_key"],
                condition=~Q(status="void"),
                name="charge_source_unique",
            )
        ]
        indexes = [
            models.Index(fields=["organisation", "status", "date"], name="charge_status_idx"),
            models.Index(fields=["client", "status"], name="charge_client_idx"),
        ]


class InvoiceRun(BranchScopedModel):
    """A batch of draft invoices for a period (FR-10-3). ``branch`` is the branch whose
    clients are invoiced; one run per branch, period and mode."""

    class Mode(models.TextChoices):
        ARREARS = "arrears", _("Delivered lessons and charges")
        ADVANCE = "advance", _("Scheduled lessons, in advance")

    class Status(models.TextChoices):
        COLLECTING = "collecting", _("Collecting charges")
        REVIEW = "review", _("Drafts in review")
        ISSUING = "issuing", _("Issuing")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    period_start = models.DateField()
    period_end = models.DateField()
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.ARREARS)
    filters = models.JSONField(default=dict, blank=True)  # {"client": id}
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COLLECTING)
    stats = models.JSONField(default=dict, blank=True)
    review_until = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workflow_id = models.CharField(max_length=255, blank=True, default="")

    class Meta(BranchScopedModel.Meta):
        ordering = ["-period_end", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "branch", "period_start", "period_end", "mode"],
                name="invoice_run_period_unique",
            )
        ]


class Invoice(BranchScopedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")
        PARTIALLY_PAID = "partially_paid", _("Partially paid")
        PAID = "paid", _("Paid")
        VOID = "void", _("Void")
        WRITTEN_OFF = "written_off", _("Written off")

    OPEN = (Status.ISSUED, Status.PARTIALLY_PAID)

    number = models.CharField(max_length=40, blank=True, default="")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="invoices")
    currency = CurrencyField()
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    subtotal = MoneyField(default=0)
    tax_total = MoneyField(default=0)
    total = MoneyField(default=0)
    amount_paid = MoneyField(default=0)
    amount_credited = MoneyField(default=0)
    balance_due = MoneyField(default=0)
    po_number = models.CharField(max_length=60, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    billing_snapshot = models.JSONField(default=dict, blank=True)  # name/address at issue
    invoice_run = models.ForeignKey(
        InvoiceRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=300, blank=True, default="")
    written_off_at = models.DateTimeField(null=True, blank=True)
    write_off_reason = models.CharField(max_length=300, blank=True, default="")
    pay_token = models.CharField(max_length=64, blank=True, default="", db_index=True)  # E11

    class Meta(BranchScopedModel.Meta):
        ordering = ["-issue_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "number"],
                condition=~Q(number=""),
                name="invoice_number_unique",
            )
        ]
        indexes = [
            models.Index(fields=["organisation", "status", "due_date"], name="invoice_status_idx"),
            models.Index(fields=["client", "status"], name="invoice_client_idx"),
        ]

    def __str__(self) -> str:
        return self.number or f"Draft {self.pk}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class InvoiceLine(TenantModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    charge = models.OneToOneField(
        Charge, null=True, blank=True, on_delete=models.SET_NULL, related_name="line"
    )
    position = models.PositiveIntegerField(default=0)
    date = models.DateField()
    description = models.CharField(max_length=300)
    student_name = models.CharField(max_length=200, blank=True, default="")
    tutor_name = models.CharField(max_length=200, blank=True, default="")
    currency = CurrencyField()
    quantity = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    unit = models.CharField(max_length=20, blank=True, default="")
    unit_price = MoneyField(decimal_places=4)
    tax_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    net = MoneyField()
    tax = MoneyField()
    gross = MoneyField()
    credited = MoneyField(default=0)  # sum of credit note lines against this line

    class Meta(TenantModel.Meta):
        ordering = ["invoice", "position", "date"]


class CreditNote(BranchScopedModel):
    """A (partial) reversal of an issued invoice (FR-10-5). Immutable once issued."""

    class Application(models.TextChoices):
        INVOICE = "invoice", _("Reduce what is owed on the invoice")
        CREDIT = "credit", _("Keep as client credit")

    number = models.CharField(max_length=40)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="credit_notes")
    client = models.ForeignKey("people.Client", on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    reason = models.CharField(max_length=300)
    application = models.CharField(max_length=7, choices=Application.choices)
    net = MoneyField()
    tax = MoneyField()
    total = MoneyField()
    issued_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(fields=["organisation", "number"], name="credit_note_number")
        ]


class CreditNoteLine(TenantModel):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(
        InvoiceLine, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    description = models.CharField(max_length=300)
    currency = CurrencyField()
    net = MoneyField()
    tax = MoneyField()
    gross = MoneyField()

    class Meta(TenantModel.Meta):
        ordering = ["credit_note", "created_at"]


class CreditAllocation(TenantModel):
    """Client credit applied to an invoice (no ledger movement: it is an allocation)."""

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="+")
    currency = CurrencyField()
    amount = MoneyField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["created_at"]


class PaymentRequest(BranchScopedModel):
    """A request to top up prepaid credit (FR-10-6). Not a tax invoice."""

    class Status(models.TextChoices):
        OPEN = "open", _("Awaiting payment")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Created by staff")
        BULK = "bulk", _("Bulk request")
        THRESHOLD = "threshold", _("Automatic top-up")

    number = models.CharField(max_length=40)
    client = models.ForeignKey(
        "people.Client", on_delete=models.PROTECT, related_name="payment_requests"
    )
    currency = CurrencyField()
    amount = MoneyField()
    amount_paid = MoneyField(default=0)
    description = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=9, choices=Source.choices, default=Source.MANUAL)
    due_date = models.DateField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    pay_token = models.CharField(max_length=64, blank=True, default="", db_index=True)  # E11

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "number"], name="payment_request_number"
            )
        ]
