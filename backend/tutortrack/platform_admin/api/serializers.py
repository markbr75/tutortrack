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


# --- Part 2: health (T09) -----------------------------------------------------------------------


class HealthComponentsSerializer(serializers.Serializer):
    usage = serializers.IntegerField(allow_null=True)
    tutors = serializers.IntegerField(allow_null=True)
    payments = serializers.IntegerField(allow_null=True)
    reliability = serializers.IntegerField(allow_null=True)
    support = serializers.IntegerField(allow_null=True)
    nps = serializers.IntegerField(allow_null=True)


class HealthRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    status = serializers.CharField()
    plan = serializers.CharField(source="plan_key", allow_null=True)
    last_activity = serializers.DateTimeField(allow_null=True)
    score = serializers.IntegerField(source="health_score")
    risk = serializers.CharField(source="health_risk")
    scored_on = serializers.DateField(source="health_date")
    components = HealthComponentsSerializer(source="health_components")


class HealthPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    score = serializers.IntegerField()
    risk = serializers.CharField()
    components = HealthComponentsSerializer()
    inputs = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    alerted_at = serializers.DateTimeField(allow_null=True)


class RiskCountsSerializer(serializers.Serializer):
    healthy = serializers.IntegerField()
    watch = serializers.IntegerField()
    at_risk = serializers.IntegerField()


class InsightsRunSerializer(serializers.Serializer):
    workflow_id = serializers.CharField()


# --- Part 2: SaaS metrics (T10) -----------------------------------------------------------------


def _money(amount: Any, currency: str) -> dict[str, str]:
    from ..metrics import as_money

    return as_money(amount, currency)


def _rate(value: Any) -> str | None:
    return None if value is None else str(value)


class SaasMonthSerializer(serializers.Serializer):
    month = serializers.DateField()
    mrr = MoneyOut()
    arr = MoneyOut()
    customers = serializers.IntegerField()
    arpa = MoneyOut()
    trialing = serializers.IntegerField()
    past_due_mrr = MoneyOut()
    new_mrr = MoneyOut()
    reactivation_mrr = MoneyOut()
    expansion_mrr = MoneyOut()
    contraction_mrr = MoneyOut()
    churned_mrr = MoneyOut()
    net_new_mrr = MoneyOut()
    new_customers = serializers.IntegerField()
    churned_customers = serializers.IntegerField()
    logo_churn_rate = serializers.CharField(allow_null=True, help_text="Fraction, e.g. 0.0250")
    revenue_churn_rate = serializers.CharField(allow_null=True)
    net_revenue_retention = serializers.CharField(allow_null=True)

    def to_representation(self, row: Any) -> dict[str, Any]:
        c = self.context["currency"]
        m = row.movements
        return {
            "month": row.month.isoformat(),
            "mrr": _money(row.mrr, c),
            "arr": _money(row.arr, c),
            "customers": row.customers,
            "arpa": _money(row.arpa, c),
            "trialing": row.trialing,
            "past_due_mrr": _money(row.past_due_mrr, c),
            "new_mrr": _money(m.new, c),
            "reactivation_mrr": _money(m.reactivation, c),
            "expansion_mrr": _money(m.expansion, c),
            "contraction_mrr": _money(m.contraction, c),
            "churned_mrr": _money(m.churn, c),
            "net_new_mrr": _money(m.net_new, c),
            "new_customers": m.customers_new,
            "churned_customers": m.customers_churned,
            "logo_churn_rate": _rate(row.logo_churn_rate),
            "revenue_churn_rate": _rate(row.revenue_churn_rate),
            "net_revenue_retention": _rate(row.net_revenue_retention),
        }


class TrialCohortSerializer(serializers.Serializer):
    month = serializers.DateField()
    trials = serializers.IntegerField()
    converted = serializers.IntegerField()
    conversion_rate = serializers.CharField(allow_null=True)

    def to_representation(self, row: Any) -> dict[str, Any]:
        return {
            "month": row.month.isoformat(),
            "trials": row.trials,
            "converted": row.converted,
            "conversion_rate": _rate(row.rate),
        }


class RetentionCohortSerializer(serializers.Serializer):
    month = serializers.DateField()
    size = serializers.IntegerField()
    starting_mrr = MoneyOut()
    logo_retention = serializers.ListField(child=serializers.CharField(allow_null=True))
    revenue_retention = serializers.ListField(child=serializers.CharField(allow_null=True))

    def to_representation(self, row: Any) -> dict[str, Any]:
        return {
            "month": row.month.isoformat(),
            "size": row.size,
            "starting_mrr": _money(row.starting_mrr, self.context["currency"]),
            "logo_retention": [_rate(v) for v in row.logos],
            "revenue_retention": [_rate(v) for v in row.revenue],
        }


class SaasMetricsSerializer(serializers.Serializer):
    currency = serializers.CharField()
    currencies = serializers.ListField(child=serializers.CharField())
    months = SaasMonthSerializer(many=True)
    trial_conversion = TrialCohortSerializer(many=True)
    cohorts = RetentionCohortSerializer(many=True)

    def to_representation(self, data: Any) -> dict[str, Any]:
        context = {"currency": data["currency"]}
        return {
            "currency": data["currency"],
            "currencies": data["currencies"],
            "months": SaasMonthSerializer(data["months"], many=True, context=context).data,
            "trial_conversion": TrialCohortSerializer(data["trial_conversion"], many=True).data,
            "cohorts": RetentionCohortSerializer(data["cohorts"], many=True, context=context).data,
        }


# --- Part 2: NPS and usage (T09) ----------------------------------------------------------------


class NpsBucketSerializer(serializers.Serializer):
    plan = serializers.CharField(required=False)
    month = serializers.DateField(required=False)
    nps = serializers.IntegerField(allow_null=True)
    answers = serializers.IntegerField()


class NpsCommentSerializer(serializers.Serializer):
    organisation_id = serializers.UUIDField()
    organisation = serializers.CharField()
    score = serializers.IntegerField()
    role = serializers.CharField()
    comment = serializers.CharField()
    created_at = serializers.DateTimeField()


class NpsSummarySerializer(serializers.Serializer):
    days = serializers.IntegerField()
    nps = serializers.IntegerField(allow_null=True)
    answers = serializers.IntegerField()
    dismissed = serializers.IntegerField()
    promoters = serializers.IntegerField()
    passives = serializers.IntegerField()
    detractors = serializers.IntegerField()
    by_plan = NpsBucketSerializer(many=True)
    by_month = NpsBucketSerializer(many=True)
    comments = NpsCommentSerializer(many=True)
    csat_average = serializers.DecimalField(max_digits=4, decimal_places=2, allow_null=True)
    csat_answers = serializers.IntegerField()


class UsageEventSerializer(serializers.Serializer):
    name = serializers.CharField()
    count = serializers.IntegerField()
    organisations = serializers.IntegerField()
    people = serializers.IntegerField()


class UsagePageSerializer(serializers.Serializer):
    route = serializers.CharField()
    count = serializers.IntegerField()
    people = serializers.IntegerField()


class UsageDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    people = serializers.IntegerField()
    organisations = serializers.IntegerField()


class FunnelStepSerializer(serializers.Serializer):
    step = serializers.CharField()
    organisations = serializers.IntegerField()


class UsageSummarySerializer(serializers.Serializer):
    days = serializers.IntegerField()
    events = serializers.IntegerField()
    people = serializers.IntegerField()
    organisations = serializers.IntegerField()
    top_events = UsageEventSerializer(many=True)
    top_pages = UsagePageSerializer(many=True)
    daily = UsageDaySerializer(many=True)
    funnel = FunnelStepSerializer(many=True)


# --- Part 2: support inbox (T08) ----------------------------------------------------------------


def _name(user: Any) -> str:
    if user is None:
        return ""
    return " ".join(p for p in (user.first_name, user.last_name) if p) or user.email


class PlatformSupportRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    organisation_id = serializers.UUIDField()
    organisation_name = serializers.CharField(source="organisation.name")
    subject = serializers.CharField()
    status = serializers.CharField()
    page = serializers.CharField()
    opened_by_name = serializers.SerializerMethodField()
    assignee_name = serializers.SerializerMethodField()
    support_unread = serializers.BooleanField()
    last_message_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()

    @extend_schema_field(serializers.CharField())
    def get_opened_by_name(self, obj: Any) -> str:
        return _name(obj.opened_by)

    @extend_schema_field(serializers.CharField())
    def get_assignee_name(self, obj: Any) -> str:
        return _name(obj.assignee)


class PlatformSupportMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    from_support = serializers.BooleanField()
    author_name = serializers.SerializerMethodField()
    body = serializers.CharField()
    created_at = serializers.DateTimeField()

    @extend_schema_field(serializers.CharField())
    def get_author_name(self, obj: Any) -> str:
        return _name(obj.author)


class PlatformSupportDetailSerializer(PlatformSupportRowSerializer):
    messages = PlatformSupportMessageSerializer(many=True, source="messages.all")


class PlatformSupportReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)
