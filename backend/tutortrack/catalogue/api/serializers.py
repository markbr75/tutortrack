from __future__ import annotations

from typing import Any

from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, MoneySerializerField
from tutortrack.people.api.serializers import AddressInput, AddressSerializer

from ..models import (
    Category,
    Level,
    Location,
    PackageTemplate,
    Product,
    Service,
    ServicePrice,
    Subject,
    TaxRate,
)


class CategorySerializer(BaseModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "order", "archived_at"]
        read_only_fields = ["id", "archived_at"]


class LevelSerializer(BaseModelSerializer):
    class Meta:
        model = Level
        fields = ["id", "subject", "name", "order", "archived_at"]
        read_only_fields = ["id", "archived_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance is not None and not isinstance(self.instance, list | tuple):
            self.fields["subject"].read_only = True


class SubjectSerializer(BaseModelSerializer):
    levels = serializers.SerializerMethodField()
    exam_boards = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, max_length=30
    )

    class Meta:
        model = Subject
        fields = ["id", "name", "category", "exam_boards", "order", "levels", "archived_at"]
        read_only_fields = ["id", "archived_at"]

    def get_levels(self, obj: Subject) -> list[dict[str, Any]]:
        levels = [lvl for lvl in obj.levels.all() if lvl.archived_at is None]
        return LevelSerializer(levels, many=True).data  # type: ignore[return-value]


class TaxRateSerializer(BaseModelSerializer):
    class Meta:
        model = TaxRate
        fields = [
            "id",
            "name",
            "percent",
            "country",
            "region",
            "is_default",
            "exempt_reason",
            "active",
        ]
        read_only_fields = ["id"]


class ServicePriceSerializer(BaseModelSerializer):
    charge_rate = MoneySerializerField(decimal_places=4)
    pay_rate = MoneySerializerField(decimal_places=4, required=False, allow_null=True)

    class Meta:
        model = ServicePrice
        fields = ["currency", "charge_rate", "pay_rate", "pay_percent"]
        read_only_fields = ["currency"]
        field_permissions = {
            "charge_rate": "billing.rates.view_charge",
            "pay_rate": "billing.rates.view_pay",
            "pay_percent": "billing.rates.view_pay",
        }


class ServiceSerializer(BaseModelSerializer):
    prices = ServicePriceSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            "id", "name", "description", "public_description", "category", "subject", "level",
            "format", "max_students", "delivery_mode", "default_duration_minutes",
            "allowed_durations", "pricing_unit", "group_charge", "currency", "charge_rate",
            "pay_unit", "pay_rate", "pay_percent", "prices", "tax_rate", "revenue_account_code",
            "branches", "bookable_online", "colour", "active", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "currency", "created_at"]
        field_permissions = {
            "charge_rate": "billing.rates.view_charge",
            "pay_rate": "billing.rates.view_pay",
            "pay_percent": "billing.rates.view_pay",
            "prices": "billing.rates.view_charge",
        }
        extra_kwargs = {"colour": {"required": False}}


class LocationSerializer(BaseModelSerializer):
    address = AddressSerializer(read_only=True)
    address_input = AddressInput(write_only=True, required=False, source="address_data")

    class Meta:
        model = Location
        fields = [
            "id", "name", "type", "address", "address_input", "timezone", "branch",
            "capacity", "opening_hours", "online_url", "archived_at", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "archived_at", "created_at"]


class ProductSerializer(BaseModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "name", "description", "category", "currency", "price", "tax_rate",
            "account_code", "tutor_share_percent", "active", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "currency", "created_at"]


class PackageTemplateSerializer(BaseModelSerializer):
    class Meta:
        model = PackageTemplate
        fields = [
            "id", "name", "description", "services", "quantity_type", "quantity", "currency",
            "price", "validity_days", "valid_until", "tax_rate",
            "transferable_between_siblings", "refund_policy", "bookable_online", "auto_renew",
            "active", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "currency", "created_at"]


# --- quote ----------------------------------------------------------------------------------------


class QuoteStudentInput(serializers.Serializer):
    student = serializers.UUIDField()
    rate_override = MoneySerializerField(decimal_places=4, required=False, allow_null=True)
    job_rate_override = MoneySerializerField(decimal_places=4, required=False, allow_null=True)


class QuoteTutorInput(serializers.Serializer):
    tutor = serializers.UUIDField()
    rate_override = MoneySerializerField(decimal_places=4, required=False, allow_null=True)
    job_rate_override = MoneySerializerField(decimal_places=4, required=False, allow_null=True)


class QuoteRequestSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=600, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    currency = serializers.CharField(max_length=3, required=False)
    job_charge_rate = MoneySerializerField(decimal_places=4, required=False, allow_null=True)
    students = QuoteStudentInput(many=True, min_length=1, max_length=100)  # type: ignore[call-arg]
    tutors = QuoteTutorInput(  # type: ignore[call-arg]
        many=True, required=False, default=list, max_length=10
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "duration_minutes" not in attrs:
            start, end = attrs.get("starts_at"), attrs.get("ends_at")
            if not (start and end) or end <= start:
                raise serializers.ValidationError(
                    {"duration_minutes": ["Give a duration, or a start and a later end."]}
                )
            attrs["duration_minutes"] = int((end - start).total_seconds() // 60)
        return attrs


class MoneyOut(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


class ChargeLineSerializer(serializers.Serializer):
    student_id = serializers.CharField()
    client_id = serializers.CharField(allow_null=True)
    unit = serializers.CharField()
    rate = MoneyOut()
    quantity = serializers.CharField()
    amount = MoneyOut()
    tax_rate_id = serializers.CharField(allow_null=True)
    tax_percent = serializers.CharField()
    tax_amount = MoneyOut()
    trace = serializers.ListField(child=serializers.CharField())


class PayLineSerializer(serializers.Serializer):
    tutor_id = serializers.CharField()
    unit = serializers.CharField()
    rate = MoneyOut(allow_null=True)
    quantity = serializers.CharField()
    amount = MoneyOut()
    trace = serializers.ListField(child=serializers.CharField())


class RateQuoteSerializer(serializers.Serializer):
    currency = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    total_charge = MoneyOut(required=False)
    total_pay = MoneyOut(required=False)
    charges = ChargeLineSerializer(many=True, required=False)
    pay = PayLineSerializer(many=True, required=False)
