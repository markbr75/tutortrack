from __future__ import annotations

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, MoneySerializerField

from ..bankfiles import FORMAT_CHOICES
from ..models import (
    BankFileExport,
    Expense,
    ExpenseCategory,
    PayItem,
    PayMethod,
    Payout,
    PayRun,
    PayStatement,
    TutorPayProfile,
)


class PayProfileSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    employment_type = serializers.CharField(source="tutor.employment_type", read_only=True)
    bank = serializers.SerializerMethodField()

    class Meta:
        model = TutorPayProfile
        fields = ["id", "tutor", "tutor_name", "employment_type", "method", "currency",
                  "payee_name", "bank_country", "bank_hint", "bank", "vat_registered",
                  "vat_number", "self_billing_agreed_at", "self_billing_agreement_version",
                  "stripe_account_id", "stripe_payouts_enabled", "hourly_rate"]  # fmt: skip
        read_only_fields = ["id", "tutor", "bank_country", "bank_hint", "self_billing_agreed_at",
                            "self_billing_agreement_version", "stripe_account_id",
                            "stripe_payouts_enabled"]  # fmt: skip

    def get_bank(self, obj: TutorPayProfile) -> dict[str, str]:
        from .. import services

        return services.bank_details(obj, full=bool(self.context.get("full_bank")))


class PayProfileUpdateSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=PayMethod.choices, required=False)
    currency = serializers.CharField(required=False, allow_blank=True, max_length=3)
    payee_name = serializers.CharField(required=False, allow_blank=True, max_length=140)
    vat_registered = serializers.BooleanField(required=False)
    vat_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    hourly_rate = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class BankDetailsSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    account_name = serializers.CharField(max_length=70)
    sort_code = serializers.CharField(required=False, allow_blank=True)
    account_number = serializers.CharField(required=False, allow_blank=True)
    iban = serializers.CharField(required=False, allow_blank=True)
    bic = serializers.CharField(required=False, allow_blank=True)
    routing_number = serializers.CharField(required=False, allow_blank=True)
    account_type = serializers.ChoiceField(choices=["checking", "savings"], required=False)
    bsb = serializers.CharField(required=False, allow_blank=True)
    bank_code = serializers.CharField(required=False, allow_blank=True)


class OriginatorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=140)
    bank = BankDetailsSerializer()
    company_id = serializers.CharField(required=False, allow_blank=True, max_length=20)
    immediate_destination = serializers.CharField(required=False, allow_blank=True, max_length=10)
    destination_name = serializers.CharField(required=False, allow_blank=True, max_length=23)
    apca_id = serializers.CharField(required=False, allow_blank=True, max_length=6)
    bank_short_name = serializers.CharField(required=False, allow_blank=True, max_length=3)


class OriginatorOutSerializer(serializers.Serializer):
    name = serializers.CharField()
    bank_hint = serializers.CharField()
    configured = serializers.BooleanField()


class PayItemSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    pay_run_number = serializers.CharField(source="pay_run.number", read_only=True, default=None)

    class Meta:
        model = PayItem
        fields = ["id", "tutor", "tutor_name", "kind", "status", "description", "date",
                  "quantity", "unit", "amount", "hold_reasons", "hold_note", "lesson",
                  "pay_run", "pay_run_number", "expense", "created_at"]  # fmt: skip
        read_only_fields = fields


class ManualItemSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    kind = serializers.ChoiceField(
        choices=["bonus", "referral", "adjustment", "deduction", "salary"]
    )
    description = serializers.CharField(max_length=300)
    amount = MoneySerializerField()
    date = serializers.DateField()


class HoldNoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=300)


class ExpenseCategorySerializer(BaseModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "kind", "account_code", "limit_amount", "mileage_rate",
                  "distance_unit", "rebillable_default", "active"]  # fmt: skip


class ExpenseSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = ["id", "tutor", "tutor_name", "category", "category_name", "status", "date",
                  "description", "amount", "tax", "distance", "receipt", "lesson", "job",
                  "client", "rebillable", "submitted_at", "decided_by_name", "decided_at",
                  "decision_comment", "charge_id"]  # fmt: skip
        read_only_fields = fields

    def get_decided_by_name(self, obj: Expense) -> str:
        user = obj.decided_by
        return (user.get_full_name() or user.email) if user else ""


class ExpenseSubmitSerializer(serializers.Serializer):
    tutor = serializers.UUIDField(
        required=False, help_text="Staff only; tutors claim for themselves"
    )
    category = serializers.UUIDField()
    date = serializers.DateField()
    description = serializers.CharField(max_length=300)
    amount = MoneySerializerField(required=False, allow_null=True)
    tax = MoneySerializerField(required=False, allow_null=True)
    distance = serializers.DecimalField(max_digits=8, decimal_places=2, required=False,
                                        allow_null=True)  # fmt: skip
    receipt = serializers.UUIDField(required=False, allow_null=True)
    lesson = serializers.UUIDField(required=False, allow_null=True)
    job = serializers.UUIDField(required=False, allow_null=True)
    client = serializers.UUIDField(required=False, allow_null=True)
    rebillable = serializers.BooleanField(required=False, allow_null=True, default=None)


class DecisionSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class MileageLegSerializer(serializers.Serializer):
    origin = serializers.CharField()
    destination = serializers.CharField()
    lesson = serializers.UUIDField()
    distance = serializers.DecimalField(max_digits=8, decimal_places=1)
    unit = serializers.CharField()


class TutorPayoutSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    statement = serializers.SerializerMethodField()

    class Meta:
        model = Payout
        fields = ["id", "tutor", "tutor_name", "amount", "method", "status", "provider_ref",
                  "reference", "failure_reason", "paid_at", "statement"]  # fmt: skip
        read_only_fields = fields

    def get_statement(self, obj: Payout) -> dict[str, str] | None:
        statement = getattr(obj, "statement", None)
        return {"id": str(statement.pk), "number": statement.number} if statement else None


class PayRunSerializer(BaseModelSerializer):
    class Meta:
        model = PayRun
        fields = ["id", "number", "all_branches", "branch", "period_start", "period_end",
                  "status", "totals", "warnings", "approvals", "approvals_required",
                  "approved_at", "paid_at", "created_at"]  # fmt: skip
        read_only_fields = fields


class BankFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankFileExport
        fields = ["id", "format", "filename", "payout_count", "total", "created_at"]


class PayRunDetailSerializer(PayRunSerializer):
    payouts = TutorPayoutSerializer(many=True, read_only=True)
    bank_files = BankFileSerializer(many=True, read_only=True)

    class Meta(PayRunSerializer.Meta):
        fields = [*PayRunSerializer.Meta.fields, "payouts", "bank_files"]
        read_only_fields = fields


class PayRunCreateSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    branch = serializers.UUIDField(required=False, allow_null=True)


class AdjustmentSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    description = serializers.CharField(max_length=300)
    amount = MoneySerializerField()


class RemoveItemSerializer(serializers.Serializer):
    item = serializers.UUIDField()


class MarkPaidSerializer(serializers.Serializer):
    payouts = serializers.ListField(child=serializers.UUIDField(), required=False)
    reference = serializers.CharField(required=False, allow_blank=True, max_length=100)


class FailPayoutSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class BankFileRequestSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=FORMAT_CHOICES, required=False)


class PayStatementSerializer(BaseModelSerializer):
    tutor_name = serializers.CharField(source="tutor.full_name", read_only=True)
    pay_run_number = serializers.CharField(source="payout.pay_run.number", read_only=True)

    class Meta:
        model = PayStatement
        fields = ["id", "tutor", "tutor_name", "kind", "number", "issued_at", "net", "vat",
                  "total", "pay_run_number"]  # fmt: skip
        read_only_fields = fields


class EarningsSerializer(serializers.Serializer):
    upcoming = PayItemSerializer(many=True)
    upcoming_total = serializers.DictField(child=serializers.CharField())
    held = PayItemSerializer(many=True)
    held_total = serializers.DictField(child=serializers.CharField())
    payouts = TutorPayoutSerializer(many=True)
    statements = PayStatementSerializer(many=True)
    year_to_date = serializers.DictField(child=serializers.CharField())


class OnboardingLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
