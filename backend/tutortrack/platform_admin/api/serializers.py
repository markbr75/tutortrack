from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.core.api.serializers import MoneyOut
from tutortrack.core.models import FeatureFlag, FeatureFlagOverride, PlatformNotice
from tutortrack.subscriptions.catalogue import FEATURES, LIMITS
from tutortrack.subscriptions.models import Interval, Plan, PlanPrice

from .. import selectors


class PlatformMeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    is_platform_staff = serializers.BooleanField()
    mfa_verified = serializers.BooleanField()
    network_allowed = serializers.BooleanField()


class TenantRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    region = serializers.CharField()
    country = serializers.CharField()
    created_at = serializers.DateTimeField()
    plan = serializers.CharField(source="plan_key", allow_null=True)
    subscription_status = serializers.CharField(allow_null=True)
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    last_activity = serializers.DateTimeField(allow_null=True)
    members = serializers.IntegerField(source="member_count")
    mrr = serializers.SerializerMethodField()

    @extend_schema_field(MoneyOut(allow_null=True))
    def get_mrr(self, obj: Any) -> dict[str, str] | None:
        return selectors.monthly_revenue(obj)


class OverrideSerializer(serializers.Serializer):
    key = serializers.CharField()
    bool_value = serializers.BooleanField(allow_null=True)
    int_value = serializers.IntegerField(allow_null=True)
    unlimited = serializers.BooleanField()
    expires_at = serializers.DateTimeField(allow_null=True)
    reason = serializers.CharField()


class TenantSubscriptionSerializer(serializers.Serializer):
    plan = serializers.CharField(source="plan.key")
    status = serializers.CharField()
    interval = serializers.CharField()
    currency = serializers.CharField()
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    pending_plan = serializers.CharField(source="pending_plan.key", allow_null=True)
    cancel_at_period_end = serializers.BooleanField()
    cancellation_reason = serializers.CharField()
    stripe_customer_id = serializers.CharField()
    stripe_subscription_id = serializers.CharField()
    seats = serializers.IntegerField()


class MemberSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.get_full_name")
    role = serializers.CharField()
    status = serializers.CharField()
    last_active_at = serializers.DateTimeField(allow_null=True)
    email_verified = serializers.SerializerMethodField()
    has_mfa = serializers.BooleanField(source="user.has_mfa")

    def get_email_verified(self, obj: Any) -> bool:
        return obj.user.email_verified_at is not None


class ErrorSerializer(serializers.Serializer):
    origin = serializers.CharField()
    kind = serializers.CharField()
    at = serializers.DateTimeField()
    detail = serializers.CharField()


class AuditSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    created_at = serializers.DateTimeField()
    action = serializers.CharField()
    object_type = serializers.CharField()
    object_repr = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    impersonator_id = serializers.UUIDField(allow_null=True)


class TenantOrganisationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    business_type = serializers.CharField()
    country = serializers.CharField()
    region = serializers.CharField()
    default_currency = serializers.CharField()
    timezone = serializers.CharField()
    contact_email = serializers.CharField()
    created_at = serializers.DateTimeField()
    suspension_reason = serializers.CharField()
    closed_at = serializers.DateTimeField(allow_null=True)
    base_url = serializers.CharField()


class TenantDetailSerializer(serializers.Serializer):
    organisation = TenantOrganisationSerializer()
    subscription = TenantSubscriptionSerializer(allow_null=True)
    overrides = OverrideSerializer(many=True)
    usage = serializers.DictField(child=serializers.IntegerField())
    members = MemberSerializer(many=True)
    recent_errors = ErrorSerializer(many=True)
    dead_letters = serializers.IntegerField()
    audit = AuditSerializer(many=True)


class PlatformReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class ExtendTrialSerializer(PlatformReasonSerializer):
    days = serializers.IntegerField(min_value=1, max_value=90)


class OverrideRequestSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=sorted([*FEATURES, *LIMITS]))
    enabled = serializers.BooleanField(required=False, allow_null=True, default=None)
    limit = serializers.IntegerField(required=False, allow_null=True, min_value=0, default=None)
    unlimited = serializers.BooleanField(default=False)
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(max_length=255)


class PlatformChangePlanSerializer(serializers.Serializer):
    plan = serializers.SlugField()
    interval = serializers.ChoiceField(choices=Interval.choices, default=Interval.MONTH)
    note = serializers.CharField(max_length=500)
    activate = serializers.BooleanField(default=False)


class ScheduleDeletionSerializer(PlatformReasonSerializer):
    confirm_slug = serializers.CharField()


class SupportSessionRequestSerializer(serializers.Serializer):
    membership_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=500)
    ticket = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    write = serializers.BooleanField(default=False)


class EnterUrlSerializer(serializers.Serializer):
    url = serializers.CharField()


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField()


class FlagOverrideSerializer(serializers.ModelSerializer):
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)

    class Meta:
        model = FeatureFlagOverride
        fields = ["organisation", "organisation_name", "enabled", "expires_at", "reason"]


class FlagSerializer(serializers.ModelSerializer):
    plan_keys = serializers.ListField(child=serializers.SlugField())
    overrides = FlagOverrideSerializer(many=True, read_only=True)

    class Meta:
        model = FeatureFlag
        fields = ["key", "description", "enabled_globally", "plan_keys", "rollout_percent",
                  "overrides", "updated_at"]  # fmt: skip
        read_only_fields = ["updated_at"]


class FlagUpdateSerializer(serializers.Serializer):
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    enabled_globally = serializers.BooleanField(required=False)
    plan_keys = serializers.ListField(child=serializers.SlugField(), required=False)
    rollout_percent = serializers.IntegerField(required=False, min_value=0, max_value=100)


class FlagCreateSerializer(FlagUpdateSerializer):
    key = serializers.SlugField(max_length=100)


class FlagOverrideRequestSerializer(serializers.Serializer):
    organisation = serializers.UUIDField()
    enabled = serializers.BooleanField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")


class OperationsSerializer(serializers.Serializer):
    outbox_pending = serializers.IntegerField()
    outbox_lag_seconds = serializers.IntegerField()
    dead_letters = serializers.IntegerField()
    queues = serializers.DictField(child=serializers.IntegerField())
    payment_webhooks_unprocessed = serializers.IntegerField()
    payment_webhooks_failed = serializers.IntegerField()
    billing_webhooks_unprocessed = serializers.IntegerField()
    billing_webhooks_failed = serializers.IntegerField()
    dead_letters_by_type = serializers.ListField(child=serializers.DictField())


class DeadLetterSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event_type = serializers.CharField()
    organisation_name = serializers.CharField(source="organisation.name", allow_null=True)
    occurred_at = serializers.DateTimeField()
    dead_lettered_at = serializers.DateTimeField()
    attempts = serializers.IntegerField()
    last_error = serializers.CharField()


class ReplaySerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=500)


class NoticeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformNotice
        fields = ["id", "message", "severity", "starts_at", "ends_at", "created_at"]
        read_only_fields = ["id", "created_at"]


class PlanAdminPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanPrice
        fields = ["id", "currency", "interval", "component", "unit_amount", "included_quantity",
                  "stripe_price_id"]  # fmt: skip
        read_only_fields = ["id", "currency", "interval", "component"]


class PlanAdminSerializer(serializers.ModelSerializer):
    prices = PlanAdminPriceSerializer(many=True, read_only=True)
    entitlements = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ["key", "name", "description", "visibility", "rank", "trial_days",
                  "seat_mode", "prices", "entitlements"]  # fmt: skip
        read_only_fields = ["key"]

    def get_entitlements(self, obj: Plan) -> dict[str, Any]:
        return {
            e.key: (e.bool_value if e.key in FEATURES else e.int_value)
            for e in obj.entitlements.all()
        }
