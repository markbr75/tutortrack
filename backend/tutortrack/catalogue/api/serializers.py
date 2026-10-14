from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import BaseModelSerializer, MoneyOut, MoneySerializerField
from tutortrack.people.api.serializers import AddressInput, AddressSerializer

from ..models import (
    Category,
    DiscountRule,
    Holiday,
    HolidayCalendar,
    Level,
    Location,
    PackageTemplate,
    PayTier,
    PremiumRule,
    PriceList,
    Product,
    PromoCode,
    Room,
    Service,
    ServicePrice,
    Subject,
    TaxRate,
    TutorPayTierAssignment,
    TutorServiceRate,
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
    timezone = serializers.CharField(max_length=64, required=False)
    location = serializers.UUIDField(required=False, allow_null=True)
    online = serializers.BooleanField(required=False, default=False)
    booked_at = serializers.DateTimeField(required=False)
    promo_code = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "duration_minutes" not in attrs:
            start, end = attrs.get("starts_at"), attrs.get("ends_at")
            if not (start and end) or end <= start:
                raise serializers.ValidationError(
                    {"duration_minutes": ["Give a duration, or a start and a later end."]}
                )
            attrs["duration_minutes"] = int((end - start).total_seconds() // 60)
        return attrs


class AdjustmentOutSerializer(serializers.Serializer):
    name = serializers.CharField()
    amount = MoneyOut()


class ChargeLineSerializer(serializers.Serializer):
    student_id = serializers.CharField()
    client_id = serializers.CharField(allow_null=True)
    unit = serializers.CharField()
    rate = MoneyOut()
    quantity = serializers.CharField()
    amount = MoneyOut()
    undiscounted_amount = MoneyOut()
    tax_rate_id = serializers.CharField(allow_null=True)
    tax_percent = serializers.CharField()
    tax_amount = MoneyOut()
    premiums = AdjustmentOutSerializer(many=True)
    discounts = AdjustmentOutSerializer(many=True)
    trace = serializers.ListField(child=serializers.CharField())


class PayLineSerializer(serializers.Serializer):
    tutor_id = serializers.CharField()
    unit = serializers.CharField()
    rate = MoneyOut(allow_null=True)
    quantity = serializers.CharField()
    amount = MoneyOut()
    premiums = AdjustmentOutSerializer(many=True)
    trace = serializers.ListField(child=serializers.CharField())


class RateQuoteSerializer(serializers.Serializer):
    currency = serializers.CharField()
    duration_minutes = serializers.IntegerField()
    total_charge = MoneyOut(required=False)
    total_pay = MoneyOut(required=False)
    charges = ChargeLineSerializer(many=True, required=False)
    pay = PayLineSerializer(many=True, required=False)


# --- Phase 2: rooms, pay tiers, holidays, premiums, discounts, price lists ------------------------


class RoomResourceSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(min_value=1, max_value=999, required=False, default=1)


class RoomSerializer(BaseModelSerializer):
    resources = serializers.SerializerMethodField()
    resources_input = RoomResourceSerializer(
        many=True, write_only=True, required=False, source="resources"
    )
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = Room
        fields = [
            "id", "location", "location_name", "name", "description", "capacity", "bookable",
            "colour", "active", "resources", "resources_input", "created_at",
        ]  # fmt: skip
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {"colour": {"required": False}}

    @extend_schema_field(RoomResourceSerializer(many=True))
    def get_resources(self, obj: Room) -> list[dict[str, Any]]:
        return [{"name": r.name, "quantity": r.quantity} for r in obj.resources.all()]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance is not None and not isinstance(self.instance, list | tuple):
            self.fields["location"].read_only = True


class PayTierSerializer(BaseModelSerializer):
    class Meta:
        model = PayTier
        fields = ["id", "name", "description", "order", "archived_at"]
        read_only_fields = ["id", "archived_at"]


class TierRateCellSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    tier = serializers.UUIDField()
    pay_rate = MoneySerializerField(decimal_places=4, allow_null=True, required=False)
    charge_rate = MoneySerializerField(decimal_places=4, allow_null=True, required=False)


class TierGridSerializer(serializers.Serializer):
    tiers = PayTierSerializer(many=True)
    cells = TierRateCellSerializer(many=True)


class TierBulkSerializer(serializers.Serializer):
    cells = TierRateCellSerializer(many=True, max_length=2000)  # type: ignore[call-arg]


class TierImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    dry_run = serializers.BooleanField(required=False, default=False)


class TierImportResultSerializer(serializers.Serializer):
    updated = serializers.IntegerField()
    unchanged = serializers.IntegerField()
    row_errors = serializers.ListField(child=serializers.DictField())


class TierAssignmentSerializer(BaseModelSerializer):
    tier_name = serializers.CharField(source="tier.name", read_only=True)
    recalculate = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = TutorPayTierAssignment
        fields = ["id", "tutor", "tier", "tier_name", "effective_from", "note", "recalculate"]
        read_only_fields = ["id"]


class TutorRateSerializer(BaseModelSerializer):
    service_name = serializers.CharField(source="service.name", read_only=True)

    class Meta:
        model = TutorServiceRate
        fields = ["id", "tutor", "service", "service_name", "currency", "pay_rate"]
        read_only_fields = ["id", "currency"]
        field_permissions = {"pay_rate": "billing.rates.view_pay"}


class TutorRateInputSerializer(serializers.Serializer):
    tutor = serializers.UUIDField()
    service = serializers.UUIDField()
    pay_rate = MoneySerializerField(decimal_places=4, allow_null=True)


class HolidaySerializer(BaseModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "calendar", "date", "name"]
        read_only_fields = ["id"]


class HolidayCalendarSerializer(BaseModelSerializer):
    holidays = HolidaySerializer(many=True, read_only=True)

    class Meta:
        model = HolidayCalendar
        fields = [
            "id", "name", "country", "region", "branch", "skip_lessons", "active", "holidays",
        ]  # fmt: skip
        read_only_fields = ["id"]


class HolidayImportSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)


class HolidayInputSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField(max_length=100)


RULE_FIELDS = ["id", "name", "active", "priority", "stackable", "services", "valid_from",
               "valid_to"]  # fmt: skip


class PremiumRuleSerializer(BaseModelSerializer):
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6), required=False
    )
    location_types = serializers.ListField(
        child=serializers.ChoiceField(choices=Location.Type.choices), required=False
    )
    services = serializers.ListField(child=serializers.UUIDField(), required=False)
    subjects = serializers.ListField(child=serializers.UUIDField(), required=False)
    levels = serializers.ListField(child=serializers.UUIDField(), required=False)

    class Meta:
        model = PremiumRule
        fields = [
            *RULE_FIELDS, "weekdays", "time_from", "time_to", "public_holidays",
            "short_notice_hours", "location_types", "delivery", "subjects", "levels",
            "min_students", "max_students", "currency", "charge_percent", "charge_fixed",
            "pay_percent", "pay_fixed",
        ]  # fmt: skip
        read_only_fields = ["id", "currency"]
        field_permissions = {
            "charge_percent": "billing.rates.view_charge",
            "charge_fixed": "billing.rates.view_charge",
            "pay_percent": "billing.rates.view_pay",
            "pay_fixed": "billing.rates.view_pay",
        }

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for name in ("services", "subjects", "levels"):
            if name in attrs:
                attrs[name] = [str(v) for v in attrs[name]]
        return attrs


class DiscountRuleSerializer(BaseModelSerializer):
    services = serializers.ListField(child=serializers.UUIDField(), required=False)

    class Meta:
        model = DiscountRule
        fields = [
            *RULE_FIELDS, "kind", "percent", "currency", "fixed_amount", "fixed_price",
            "sibling_from", "volume_min_lessons", "min_classes", "client", "student",
        ]  # fmt: skip
        read_only_fields = ["id", "currency"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "services" in attrs:
            attrs["services"] = [str(v) for v in attrs["services"]]
        return attrs


class PromoCodeSerializer(BaseModelSerializer):
    discount_name = serializers.CharField(source="discount.name", read_only=True)

    class Meta:
        model = PromoCode
        fields = [
            "id", "code", "discount", "discount_name", "max_uses", "max_uses_per_client",
            "uses", "valid_from", "valid_to", "new_clients_only", "active",
        ]  # fmt: skip
        read_only_fields = ["id", "uses"]


class PriceListItemSerializer(serializers.Serializer):
    service = serializers.UUIDField()
    charge_rate = MoneySerializerField(decimal_places=4)


class PriceListSerializer(BaseModelSerializer):
    items = serializers.SerializerMethodField()
    clients = serializers.SerializerMethodField()
    items_input = PriceListItemSerializer(
        many=True, write_only=True, required=False, source="items"
    )
    client_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False, source="clients"
    )

    class Meta:
        model = PriceList
        fields = [
            "id", "name", "currency", "valid_from", "valid_to", "active", "notes", "items",
            "clients", "items_input", "client_ids",
        ]  # fmt: skip
        read_only_fields = ["id"]
        field_permissions = {"items": "billing.rates.view_charge"}

    @extend_schema_field(PriceListItemSerializer(many=True))
    def get_items(self, obj: PriceList) -> list[dict[str, Any]]:
        return [
            {"service": str(i.service_id), "charge_rate": i.charge_rate.to_dict()}
            for i in obj.items.all()
        ]

    @extend_schema_field(serializers.ListField(child=serializers.UUIDField()))
    def get_clients(self, obj: PriceList) -> list[str]:
        return [str(c.client_id) for c in obj.clients.all()]
