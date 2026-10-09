from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from tutortrack.catalogue.models import Product, TaxRate
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.jobs.models import Job
from tutortrack.people.models import Client, Student, TutorProfile
from tutortrack.tenancy.models import Branch

from ..models import (
    Charge,
    ClientLedgerEntry,
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    InvoiceRun,
    PaymentRequest,
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
