from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
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
    BankStatementImport,
    BankTransaction,
    Dispute,
    Payment,
    PaymentAllocation,
    PaymentGroup,
    PaymentMethod,
    ProviderAccount,
    ProviderMigration,
    ProviderPayout,
    ReconciliationMatch,
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


PAY_PROVIDERS = ["stripe", "gocardless", "paypal"]
SETUP_PROVIDERS = ["", "stripe", "gocardless"]
MIGRATION_PROVIDERS = ["stripe", "gocardless"]
MANUAL_METHODS = [m for m in Payment.Method.choices if m[0] != Payment.Method.CARD]


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
            "group",
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
    method = serializers.ChoiceField(choices=MANUAL_METHODS)
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
    providers = serializers.ListField(
        child=serializers.CharField(),
        help_text="Online providers offered: stripe, gocardless, paypal",
    )


class PayIntentRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True, min_value=0
    )
    save_method = serializers.BooleanField(default=False)
    provider = serializers.ChoiceField(choices=PAY_PROVIDERS, default="stripe")


class PayIntentSerializer(serializers.Serializer):
    provider = serializers.CharField(default="stripe")
    publishable_key = serializers.CharField()
    account = serializers.CharField()
    client_secret = serializers.CharField()
    intent = serializers.CharField()
    redirect_url = serializers.CharField(
        default="", help_text="GoCardless/PayPal: send the customer here"
    )
    amount = MoneyOut()


class ConfirmSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=100)
    provider = serializers.ChoiceField(choices=PAY_PROVIDERS, default="stripe")


class ConfirmResultSerializer(serializers.Serializer):
    status = serializers.CharField()


class SetupPageSerializer(serializers.Serializer):
    organisation = serializers.CharField()
    client_name = serializers.CharField()
    provider = serializers.CharField()
    providers = serializers.ListField(child=serializers.CharField())
    publishable_key = serializers.CharField()
    account = serializers.CharField()
    client_secret = serializers.CharField()
    intent = serializers.CharField()
    redirect_url = serializers.CharField()
    consent_text = serializers.CharField()


class SetupCompleteSerializer(serializers.Serializer):
    intent = serializers.CharField(max_length=100)
    autopay = serializers.BooleanField(default=False)
    provider = serializers.ChoiceField(choices=SETUP_PROVIDERS, required=False, default="")


class SetupDoneSerializer(serializers.Serializer):
    method = PaymentMethodSerializer()
    auto_pay = serializers.BooleanField()


# --- Phase 2 (E11-T11..T14) ---------------------------------------------------------------------


class PartnerCompleteSerializer(serializers.Serializer):
    state = serializers.CharField(max_length=200)
    code = serializers.CharField(
        max_length=300, help_text="GoCardless ``code``, or PayPal ``merchantIdInPayPal``"
    )


class SplitPartSerializer(serializers.Serializer):
    client = TenantRelatedField(Client)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    allocations = AllocationInputSerializer(many=True, required=False, allow_null=True)


class SplitPaymentSerializer(serializers.Serializer):
    payer_name = serializers.CharField(max_length=200)
    amount = MoneySerializerField()
    method = serializers.ChoiceField(choices=MANUAL_METHODS)
    received_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    parts = SplitPartSerializer(many=True)


class PaymentGroupSerializer(BaseModelSerializer):
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = PaymentGroup
        fields = ["id", "payer_name", "currency", "amount", "method", "received_at",
                  "reference", "notes", "payments", "created_at"]  # fmt: skip
        read_only_fields = fields


class MatchSerializer(BaseModelSerializer):
    invoice_number = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = ReconciliationMatch
        fields = ["id", "kind", "invoice", "invoice_number", "payment_request", "client",
                  "client_name", "payment", "payout", "score", "reason", "status"]  # fmt: skip
        read_only_fields = fields

    def get_invoice_number(self, obj: ReconciliationMatch) -> str:
        return obj.invoice.number if obj.invoice else ""

    def get_client_name(self, obj: ReconciliationMatch) -> str:
        return obj.client.display_name if obj.client else ""


class BankTransactionSerializer(BaseModelSerializer):
    matches = serializers.SerializerMethodField()

    class Meta:
        model = BankTransaction
        fields = ["id", "statement", "booked_on", "currency", "amount", "description",
                  "reference", "counterparty", "status", "payment", "payment_group", "payout",
                  "matched_at", "matches", "created_at"]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(MatchSerializer(many=True))
    def get_matches(self, obj: BankTransaction) -> list[dict[str, Any]]:
        rows = [m for m in obj.matches.all() if m.status != ReconciliationMatch.Status.REJECTED]
        return list(MatchSerializer(rows, many=True).data)


class BankImportSerializer(BaseModelSerializer):
    class Meta:
        model = BankStatementImport
        fields = ["id", "source", "filename", "account_name", "currency", "connection_id",
                  "stats", "created_at"]  # fmt: skip
        read_only_fields = fields


class BankUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    file_type = serializers.ChoiceField(
        choices=["", "csv", "ofx", "camt"], required=False, default="",
        help_text="Leave empty to detect from the file",
    )  # fmt: skip
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default="")
    month_first = serializers.BooleanField(default=False, help_text="US dates (month/day) in CSV")


class ConfirmMatchSerializer(serializers.Serializer):
    match = serializers.UUIDField(required=False, allow_null=True)
    client = TenantRelatedField(Client, required=False, allow_null=True)
    invoice = TenantRelatedField(Invoice, required=False, allow_null=True)


class SplitMatchSerializer(serializers.Serializer):
    payer_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    parts = SplitPartSerializer(many=True)


class BankSyncResultSerializer(serializers.Serializer):
    imports = BankImportSerializer(many=True)


class MigrationRequestSerializer(serializers.Serializer):
    to_provider = serializers.ChoiceField(choices=MIGRATION_PROVIDERS)


class ProviderMigrationSerializer(BaseModelSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)

    class Meta:
        model = ProviderMigration
        fields = ["id", "client", "client_name", "from_method", "to_provider", "new_method",
                  "status", "completed_at", "created_at"]  # fmt: skip
        read_only_fields = fields
