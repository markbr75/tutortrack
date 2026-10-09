from __future__ import annotations

from rest_framework import serializers

from tutortrack.billing.models import Invoice, PaymentRequest
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneyOut,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.people.models import Client
from tutortrack.tenancy.models import Branch

from ..models import (
    Dispute,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    ProviderAccount,
    ProviderPayout,
    Refund,
)


class ProviderAccountSerializer(BaseModelSerializer):
    requirements = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = ProviderAccount
        fields = [
            "id",
            "provider",
            "branch",
            "account_ref",
            "status",
            "charges_enabled",
            "payouts_enabled",
            "requirements",
            "default_currency",
            "connected_at",
        ]
        read_only_fields = fields


class ConnectSerializer(serializers.Serializer):
    branch = TenantRelatedField(Branch, required=False, allow_null=True)
    email = serializers.EmailField(required=False, allow_blank=True, default="")


class OnboardingSerializer(serializers.Serializer):
    account = ProviderAccountSerializer()
    url = serializers.URLField()


class PaymentMethodSerializer(BaseModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "type",
            "brand",
            "last4",
            "exp_month",
            "exp_year",
            "mandate_status",
            "is_default",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class ClientMethodsSerializer(serializers.Serializer):
    auto_pay = serializers.BooleanField()
    consent_given_at = serializers.DateTimeField(allow_null=True)
    methods = PaymentMethodSerializer(many=True)


class SetupLinkOutSerializer(serializers.Serializer):
    url = serializers.URLField()


class AutoPaySerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class AllocationSerializer(BaseModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = ["id", "invoice", "invoice_number", "amount", "created_at"]
        read_only_fields = fields


class RefundSerializer(BaseModelSerializer):
    class Meta:
        model = Refund
        fields = ["id", "amount", "reason", "status", "provider_ref", "credit_note", "created_at"]
        read_only_fields = fields


class PaymentSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    allocations = AllocationSerializer(many=True, read_only=True)
    refunds = RefundSerializer(many=True, read_only=True)
    unallocated = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "client",
            "client_name",
            "currency",
            "amount",
            "refunded",
            "fee",
            "net",
            "unallocated",
            "method",
            "provider",
            "provider_ref",
            "status",
            "source",
            "received_at",
            "reference",
            "notes",
            "payment_request",
            "failure_code",
            "failure_message",
            "allocations",
            "refunds",
            "created_at",
        ]
        read_only_fields = fields

    def get_unallocated(self, obj: Payment) -> dict[str, str]:
        from ..services import unallocated

        return unallocated(obj).to_dict()


class AllocationInputSerializer(serializers.Serializer):
    invoice = TenantRelatedField(Invoice)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)


class RecordPaymentSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    amount = MoneySerializerField()
    method = serializers.ChoiceField(
        choices=[m for m in Payment.Method.choices if m[0] != Payment.Method.CARD]
    )
    received_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    payment_request = TenantRelatedField(PaymentRequest, required=False, allow_null=True)
    allocations = AllocationInputSerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text="Leave out to pay the oldest invoices first (the rest is credit).",
    )


class AllocateSerializer(serializers.Serializer):
    allocations = AllocationInputSerializer(many=True)


class RefundRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    reason = serializers.CharField(max_length=300)
    credit_note = serializers.BooleanField(
        default=False, help_text="Also credit the invoices the refunded money had paid."
    )


class DisputeSerializer(BaseModelSerializer):
    class Meta:
        model = Dispute
        fields = [
            "id",
            "payment",
            "provider_ref",
            "amount",
            "reason",
            "status",
            "evidence_due_by",
            "closed_at",
            "created_at",
        ]
        read_only_fields = fields


class PayoutSerializer(BaseModelSerializer):
    class Meta:
        model = ProviderPayout
        fields = ["id", "provider_ref", "amount", "status", "arrival_date", "created_at"]
        read_only_fields = fields


# --- public pages -------------------------------------------------------------------------------


class PayPageLineSerializer(serializers.Serializer):
    description = serializers.CharField()
    amount = MoneyOut()


class PayPageSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["invoice", "payment_request"])
    organisation = serializers.CharField()
    number = serializers.CharField()
    client_name = serializers.CharField()
    status = serializers.CharField()
    due_date = serializers.DateField(allow_null=True)
    total = MoneyOut()
    amount_due = MoneyOut()
    lines = PayPageLineSerializer(many=True)
    allow_partial = serializers.BooleanField()
    can_pay_online = serializers.BooleanField()
    has_pdf = serializers.BooleanField()


class PayIntentRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    save_method = serializers.BooleanField(default=False)


class PayIntentSerializer(serializers.Serializer):
    publishable_key = serializers.CharField()
    account = serializers.CharField()
    client_secret = serializers.CharField()
    intent = serializers.CharField()
    amount = MoneyOut()


class ConfirmSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=100)


class ConfirmResultSerializer(serializers.Serializer):
    status = serializers.CharField()


class SetupPageSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    client_name = serializers.CharField()
    publishable_key = serializers.CharField()
    account = serializers.CharField()
    client_secret = serializers.CharField()
    intent = serializers.CharField()
    consent_text = serializers.CharField()


class SetupCompleteSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=100)
    autopay = serializers.BooleanField(default=False)


class SetupDoneSerializer(serializers.Serializer):
    method = PaymentMethodSerializer()
    auto_pay = serializers.BooleanField()
