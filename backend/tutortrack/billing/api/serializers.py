from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.catalogue.models import PackageTemplate, Product, TaxRate
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.core.models import StoredFile
from tutortrack.jobs.models import Job
from tutortrack.people.models import Client, Student, TutorProfile
from tutortrack.tenancy.models import Branch

from ..models import (
    BillingPlan,
    Charge,
    ClientLedgerEntry,
    CollectionsCase,
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    InvoiceRun,
    InvoiceTemplate,
    LateFeeRule,
    PackageConsumption,
    PackagePurchase,
    PaymentRequest,
    TutorInvoiceReview,
)


class ChargeSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    student_name = serializers.SerializerMethodField()
    invoice_number = serializers.SerializerMethodField()

    class Meta:
        model = Charge
        fields = [
            "id",
            "client",
            "client_name",
            "student",
            "student_name",
            "job",
            "lesson",
            "kind",
            "description",
            "date",
            "currency",
            "quantity",
            "unit",
            "unit_price",
            "tax_percent",
            "net",
            "tax",
            "gross",
            "status",
            "invoice",
            "invoice_number",
            "category",
            "created_at",
        ]
        read_only_fields = fields

    def get_student_name(self, obj: Charge) -> str:
        return obj.student.full_name if obj.student else ""

    def get_invoice_number(self, obj: Charge) -> str:
        return obj.invoice.number if obj.invoice else ""


class AdHocChargeSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    job = TenantRelatedField(Job, required=False, allow_null=True)
    product = TenantRelatedField(Product, required=False, allow_null=True)
    tax_rate = TenantRelatedField(TaxRate, required=False, allow_null=True)
    description = serializers.CharField(max_length=300)
    day = serializers.DateField(required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=4, default=Decimal(1))
    unit_price = MoneySerializerField(decimal_places=4, help_text="Negative for a discount")
    category = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    tutor = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    tutor_share = MoneySerializerField(required=False, allow_null=True)


class InvoiceLineSerializer(BaseModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "charge",
            "kind",
            "parent",
            "position",
            "date",
            "description",
            "student_name",
            "tutor_name",
            "quantity",
            "unit",
            "unit_price",
            "tax_percent",
            "net",
            "tax",
            "gross",
            "credited",
        ]
        read_only_fields = fields


INVOICE_FIELDS = [
    "id",
    "number",
    "client",
    "client_name",
    "branch",
    "currency",
    "status",
    "is_overdue",
    "issue_date",
    "due_date",
    "period_start",
    "period_end",
    "subtotal",
    "tax_total",
    "total",
    "amount_paid",
    "amount_credited",
    "balance_due",
    "po_number",
    "notes",
    "sent_at",
    "invoice_run",
    "created_at",
]


class InvoiceSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = INVOICE_FIELDS
        read_only_fields = fields

    def get_is_overdue(self, obj: Invoice) -> bool:
        from ..services import org_today

        return bool(obj.is_open and obj.due_date and obj.due_date < org_today())


class CreditNoteLineSerializer(BaseModelSerializer):
    class Meta:
        model = CreditNoteLine
        fields = ["id", "invoice_line", "description", "net", "tax", "gross"]
        read_only_fields = fields


class CreditNoteSerializer(BaseModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    lines = CreditNoteLineSerializer(many=True, read_only=True)

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "number",
            "invoice",
            "invoice_number",
            "client",
            "currency",
            "reason",
            "application",
            "net",
            "tax",
            "total",
            "issued_at",
            "lines",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(InvoiceSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    credit_notes = CreditNoteSerializer(many=True, read_only=True)
    billing_snapshot = serializers.JSONField(read_only=True)

    class Meta:
        model = Invoice
        fields = [*INVOICE_FIELDS, "billing_snapshot", "lines", "credit_notes"]
        read_only_fields = fields


class InvoiceCreateSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    until = serializers.DateField(required=False, allow_null=True, default=None)


class InvoiceUpdateSerializer(serializers.Serializer):
    po_number = serializers.CharField(max_length=60, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)


class AddLineSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=300)
    unit_price = MoneySerializerField(decimal_places=4)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=4, default=Decimal(1))
    student = TenantRelatedField(Student, required=False, allow_null=True)
    tax_rate = TenantRelatedField(TaxRate, required=False, allow_null=True)
    product = TenantRelatedField(Product, required=False, allow_null=True)


class RemoveLineSerializer(serializers.Serializer):
    line = serializers.UUIDField()


class BillingReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class CreditLineSerializer(serializers.Serializer):
    line = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)


class CreditNoteRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
    application = serializers.ChoiceField(choices=CreditNote.Application.choices, default="invoice")
    lines = CreditLineSerializer(
        many=True, required=False, help_text="Leave out to credit everything still owed."
    )


class ApplyCreditSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0
    )


class AppliedSerializer(serializers.Serializer):
    applied = MoneyOut()
    invoice = InvoiceSerializer()


class PaymentRequestSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)

    class Meta:
        model = PaymentRequest
        fields = [
            "id",
            "number",
            "client",
            "client_name",
            "currency",
            "amount",
            "amount_paid",
            "description",
            "status",
            "source",
            "due_date",
            "sent_at",
            "paid_at",
            "created_at",
        ]
        read_only_fields = fields


class PaymentRequestCreateSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    amount = MoneySerializerField()
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)


class BulkRequestSerializer(serializers.Serializer):
    clients = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Leave out for every active client with prepaid jobs.",
    )
    below = MoneySerializerField(required=False, allow_null=True)
    amount = MoneySerializerField(required=False, allow_null=True)
    top_up_to = MoneySerializerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if bool(attrs.get("amount")) == bool(attrs.get("top_up_to")):
            raise serializers.ValidationError("Give either an amount or a top-up target.")
        return attrs


class BulkRequestResultSerializer(serializers.Serializer):
    created = PaymentRequestSerializer(many=True)


class InvoiceRunSerializer(BaseModelSerializer):
    class Meta:
        model = InvoiceRun
        fields = [
            "id",
            "branch",
            "period_start",
            "period_end",
            "mode",
            "filters",
            "status",
            "stats",
            "review_until",
            "approved_at",
            "created_at",
        ]
        read_only_fields = fields


class TutorReviewLessonSerializer(serializers.Serializer):
    invoice_id = serializers.CharField()
    date = serializers.DateField()
    lesson_id = serializers.CharField(allow_null=True)
    description = serializers.CharField()
    student = serializers.CharField(allow_blank=True)
    duration_minutes = serializers.IntegerField(allow_null=True)


class TutorInvoiceReviewSerializer(BaseModelSerializer):
    """A tutor's check of their lessons on an invoice run's drafts (gap G3). Never amounts."""

    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    period_start = serializers.DateField(source="invoice_run.period_start", read_only=True)
    period_end = serializers.DateField(source="invoice_run.period_end", read_only=True)
    review_until = serializers.DateTimeField(source="invoice_run.review_until", read_only=True)
    lessons = serializers.SerializerMethodField()

    class Meta:
        model = TutorInvoiceReview
        fields = [
            "id",
            "invoice_run",
            "tutor",
            "tutor_name",
            "status",
            "comment",
            "flagged_invoices",
            "decided_at",
            "period_start",
            "period_end",
            "review_until",
            "lessons",
        ]
        read_only_fields = fields

    @extend_schema_field(TutorReviewLessonSerializer(many=True))
    def get_lessons(self, obj: TutorInvoiceReview) -> list[dict[str, Any]]:
        from ..tutor_review import lessons_for

        return TutorReviewLessonSerializer(lessons_for(obj), many=True).data  # type: ignore[return-value]


class TutorReviewFlagSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=2000)
    invoice_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=50,
        help_text="Only these drafts (default: every draft with your lessons).",
    )


class InvoiceRunCreateSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    mode = serializers.ChoiceField(choices=InvoiceRun.Mode.choices, default="arrears")
    branch = TenantRelatedField(Branch, required=False, allow_null=True)
    client = TenantRelatedField(Client, required=False, allow_null=True)


class RunPreviewSerializer(serializers.Serializer):
    clients = serializers.IntegerField()
    charges = serializers.IntegerField()
    totals = serializers.DictField(child=serializers.CharField())


class BalancesSerializer(serializers.Serializer):
    currency = serializers.CharField()
    ledger = MoneyOut()
    invoice_balance = MoneyOut()
    available_credit = MoneyOut()
    uninvoiced = MoneyOut()
    projected = MoneyOut()
    overdue = MoneyOut()


class LedgerEntrySerializer(BaseModelSerializer):
    class Meta:
        model = ClientLedgerEntry
        fields = [
            "id",
            "type",
            "currency",
            "amount",
            "balance_after",
            "ref_type",
            "ref_id",
            "description",
            "occurred_at",
        ]
        read_only_fields = fields


class LedgerAdjustSerializer(serializers.Serializer):
    amount = MoneySerializerField(help_text="Positive adds to what the client owes")
    reason = serializers.CharField(max_length=300)


class AgeingSerializer(serializers.Serializer):
    current = MoneyOut()
    one_to_30 = MoneyOut(source="1_30")
    thirty_one_to_60 = MoneyOut(source="31_60")
    sixty_one_to_90 = MoneyOut(source="61_90")
    over_90 = MoneyOut(source="90_plus")


class StatementSerializer(serializers.Serializer):
    client_id = serializers.UUIDField()
    currency = serializers.CharField()
    start = serializers.DateField()
    end = serializers.DateField()
    opening = MoneyOut()
    closing = MoneyOut()
    entries = LedgerEntrySerializer(many=True)
    ageing = AgeingSerializer()


class AgeingRowSerializer(AgeingSerializer):
    client = serializers.UUIDField()
    client_name = serializers.CharField()
    total = MoneyOut()


# --- Phase 2: packages (T12) --------------------------------------------------------------------


class PackageConsumptionSerializer(BaseModelSerializer):
    class Meta:
        model = PackageConsumption
        fields = ["id", "kind", "lesson", "units", "value", "note", "created_at"]
        read_only_fields = fields


class PackagePurchaseSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    student_name = serializers.SerializerMethodField()
    units_remaining = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    invoice = serializers.SerializerMethodField()
    invoice_number = serializers.SerializerMethodField()

    class Meta:
        model = PackagePurchase
        fields = [
            "id",
            "client",
            "client_name",
            "student",
            "student_name",
            "template",
            "name",
            "quantity_type",
            "units_total",
            "units_used",
            "units_expired",
            "units_remaining",
            "currency",
            "price",
            "shareable",
            "auto_renew",
            "status",
            "source",
            "invoice",
            "invoice_number",
            "activated_at",
            "expires_at",
            "closed_at",
            "close_reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_student_name(self, obj: PackagePurchase) -> str:
        return obj.student.full_name if obj.student else ""

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_invoice(self, obj: PackagePurchase) -> str | None:
        charge = obj.charge
        return str(charge.invoice_id) if charge and charge.invoice_id else None

    def get_invoice_number(self, obj: PackagePurchase) -> str:
        charge = obj.charge
        return charge.invoice.number if charge and charge.invoice_id else ""  # type: ignore[union-attr]


class PackageDetailSerializer(PackagePurchaseSerializer):
    consumptions = PackageConsumptionSerializer(many=True, read_only=True)

    class Meta(PackagePurchaseSerializer.Meta):
        fields = [*PackagePurchaseSerializer.Meta.fields, "consumptions"]
        read_only_fields = fields


class SellPackageSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    template = TenantRelatedField(PackageTemplate, filter={"active": True})
    student = TenantRelatedField(Student, required=False, allow_null=True)


class ExtendPackageSerializer(serializers.Serializer):
    until = serializers.DateTimeField()


class CancelPackageSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)
    refund = serializers.BooleanField(
        required=False, allow_null=True, default=None, help_text="Omit to follow the policy"
    )


# --- Phase 2: recurring fees (T13) --------------------------------------------------------------


class BillingPlanSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)

    class Meta:
        model = BillingPlan
        fields = [
            "id",
            "client",
            "client_name",
            "job",
            "student",
            "description",
            "currency",
            "amount",
            "tax_rate",
            "interval",
            "anchor_date",
            "start_date",
            "end_date",
            "prorate",
            "attendance_independent",
            "status",
            "paused_at",
            "created_at",
        ]
        read_only_fields = fields


class BillingPlanCreateSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    job = TenantRelatedField(Job, required=False, allow_null=True)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    tax_rate = TenantRelatedField(TaxRate, required=False, allow_null=True)
    description = serializers.CharField(max_length=200)
    amount = MoneySerializerField()
    interval = serializers.ChoiceField(choices=BillingPlan.Interval.choices)
    start_date = serializers.DateField()
    anchor_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    prorate = serializers.BooleanField(default=True)
    attendance_independent = serializers.BooleanField(default=True)


class BillingPlanUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=200, required=False)
    amount = MoneySerializerField(required=False)
    end_date = serializers.DateField(required=False, allow_null=True)
    prorate = serializers.BooleanField(required=False)
    attendance_independent = serializers.BooleanField(required=False)


class PlanStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BillingPlan.Status.choices)


class ProrationPreviewSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    amount = MoneyOut()
    partial = serializers.BooleanField()  # type: ignore[assignment]


# --- Phase 2: late fees and collections (T14) ---------------------------------------------------


class LateFeeRuleSerializer(BaseModelSerializer):
    branch = TenantRelatedField(Branch, required=False, allow_null=True)
    tax_rate = TenantRelatedField(TaxRate, required=False, allow_null=True)

    class Meta:
        model = LateFeeRule
        fields = [
            "id",
            "branch",
            "kind",
            "amount",
            "percent",
            "days_overdue",
            "recurrence",
            "max_applications",
            "cap",
            "minimum_balance",
            "mode",
            "tax_rate",
            "active",
        ]
        read_only_fields = ["id"]


class WaiveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class CollectionsCaseSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    balance_due = MoneySerializerField(source="invoice.balance_due", read_only=True)

    class Meta:
        model = CollectionsCase
        fields = [
            "id",
            "client",
            "client_name",
            "invoice",
            "invoice_number",
            "balance_due",
            "status",
            "block",
            "task_id",
            "opened_at",
            "closed_at",
            "close_reason",
        ]
        read_only_fields = fields


class CloseCaseSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


# --- Phase 2: split billing (T15) ---------------------------------------------------------------


class SplitShareSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    percent = serializers.DecimalField(max_digits=5, decimal_places=2)


class SplitShareOutSerializer(serializers.Serializer):
    client = serializers.UUIDField(source="client_id")
    client_name = serializers.CharField(source="client.display_name")
    percent = serializers.DecimalField(max_digits=5, decimal_places=2)


class BillingSplitSerializer(serializers.Serializer):
    job = TenantRelatedField(Job, required=False, allow_null=True)
    student = TenantRelatedField(Student, required=False, allow_null=True)
    shares = SplitShareSerializer(many=True)


class BillingSplitOutSerializer(serializers.Serializer):
    job = serializers.UUIDField(allow_null=True)
    student = serializers.UUIDField(allow_null=True)
    shares = SplitShareOutSerializer(many=True)


class InvoiceTemplateSerializer(BaseModelSerializer):
    """An invoice template (ADR 0046). Blank wording and colour fall back to the billing
    settings and the brand kit."""

    logo = TenantRelatedField(
        StoredFile, required=False, allow_null=True, help_text="Used when logo_mode is own."
    )

    class Meta:
        model = InvoiceTemplate
        fields = [
            "id", "name", "is_default", "style", "accent_colour", "logo_mode", "logo", "title",
            "trading_name", "intro", "payment_instructions", "footer", "show_date",
            "show_student", "show_tutor", "show_quantity", "show_unit_price", "created_at",
            "updated_at",
        ]  # fmt: skip
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_accent_colour(self, value: str) -> str:
        # It goes into the document's CSS: only a hex colour (the preview isn't saved, so
        # the service's checks don't run for it).
        from ..invoice_templates import HEX

        if value and not HEX.match(value):
            raise serializers.ValidationError(_("Use a colour like #1D4ED8, or leave it empty."))
        return value


class InvoiceTemplatePreviewSerializer(InvoiceTemplateSerializer):
    """Unsaved template settings for the editor's preview (nothing is stored)."""

    class Meta(InvoiceTemplateSerializer.Meta):
        extra_kwargs = {"name": {"required": False, "allow_blank": True}}


class InvoiceTemplatePreviewResponse(serializers.Serializer):
    html = serializers.CharField(help_text="The sample invoice as HTML, for an iframe.")
