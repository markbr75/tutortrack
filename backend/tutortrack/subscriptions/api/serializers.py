from __future__ import annotations

from typing import Any

from rest_framework import serializers

from tutortrack.core.api.serializers import MoneyOut

from ..credits import PACKS
from ..models import CreditType, Interval, Plan, PlanPrice, Subscription
from ..services import CANCEL_REASONS


class PlanPriceSerializer(serializers.Serializer):
    interval = serializers.ChoiceField(choices=Interval.choices)
    component = serializers.ChoiceField(choices=PlanPrice.Component.choices)
    unit_amount = serializers.CharField(help_text="An amount, or a percentage for revenue_share")
    included_quantity = serializers.IntegerField()


class PlanSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    visibility = serializers.ChoiceField(choices=Plan.Visibility.choices)
    rank = serializers.IntegerField()
    currency = serializers.CharField()
    prices = PlanPriceSerializer(many=True)
    features = serializers.DictField(child=serializers.BooleanField())
    limits = serializers.DictField(child=serializers.IntegerField(allow_null=True))


class CardSerializer(serializers.Serializer):
    brand = serializers.CharField()
    last4 = serializers.CharField()
    exp_month = serializers.IntegerField(allow_null=True)
    exp_year = serializers.IntegerField(allow_null=True)


class SubscriptionSerializer(serializers.Serializer):
    plan = serializers.CharField(source="plan.key")
    plan_name = serializers.CharField(source="plan.name")
    effective_plan = serializers.CharField()
    status = serializers.ChoiceField(choices=Subscription.Status.choices)
    interval = serializers.ChoiceField(choices=Interval.choices)
    currency = serializers.CharField()
    trial_ends_at = serializers.DateTimeField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    pending_plan = serializers.CharField(source="pending_plan.key", allow_null=True)
    pending_interval = serializers.CharField()
    cancel_at_period_end = serializers.BooleanField()
    past_due_since = serializers.DateTimeField(allow_null=True)
    has_payment_method = serializers.BooleanField()
    card = CardSerializer(allow_null=True)
    can_manage = serializers.BooleanField()


class PlanChoiceSerializer(serializers.Serializer):
    plan = serializers.SlugField()
    interval = serializers.ChoiceField(choices=Interval.choices, default=Interval.MONTH)


class ChangePreviewSerializer(serializers.Serializer):
    plan = serializers.CharField()
    interval = serializers.CharField()
    direction = serializers.ChoiceField(choices=["upgrade", "downgrade", "same"])
    effective = serializers.ChoiceField(choices=["now", "period_end", "checkout"])
    blockers = serializers.ListField(child=serializers.CharField())
    amount_due_now = MoneyOut(allow_null=True)


class RedirectSerializer(serializers.Serializer):
    url = serializers.URLField(allow_blank=True)


class CompleteCheckoutSerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=200)


class CancelSubscriptionSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=[(r, r) for r in CANCEL_REASONS])
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ReactivateSerializer(serializers.Serializer):
    subscription = SubscriptionSerializer()
    url = serializers.CharField(allow_blank=True)


class LimitUsageSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    used = serializers.IntegerField()
    allowed = serializers.IntegerField(allow_null=True)


class CreditAccountSerializer(serializers.Serializer):
    credit_type = serializers.ChoiceField(choices=CreditType.choices)
    balance = serializers.IntegerField()
    allowance = serializers.IntegerField()
    included_balance = serializers.IntegerField()
    purchased_balance = serializers.IntegerField()
    used_this_period = serializers.IntegerField()
    auto_top_up = serializers.BooleanField()
    top_up_pack = serializers.IntegerField()
    low_threshold = serializers.IntegerField()
    allow_overage = serializers.BooleanField()
    packs = serializers.SerializerMethodField()

    def get_packs(self, obj: Any) -> list[int]:
        kind = obj["credit_type"] if isinstance(obj, dict) else obj.credit_type
        return sorted(PACKS[kind])


class UsageSerializer(serializers.Serializer):
    limits = LimitUsageSerializer(many=True)
    billable_tutors = serializers.IntegerField()
    included_tutors = serializers.IntegerField()
    next_invoice = MoneyOut(allow_null=True)
    credits = CreditAccountSerializer(many=True)


class InvoiceSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField()
    status = serializers.CharField()
    total = MoneyOut()
    created = serializers.DateTimeField()
    pdf_url = serializers.CharField()
    hosted_url = serializers.CharField()


class CreditSettingsSerializer(serializers.Serializer):
    auto_top_up = serializers.BooleanField(required=False)
    top_up_pack = serializers.IntegerField(required=False, min_value=1)
    low_threshold = serializers.IntegerField(required=False, min_value=0, max_value=100000)
    allow_overage = serializers.BooleanField(required=False)


class CreditLedgerEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    delta = serializers.IntegerField()
    reason = serializers.CharField()
    balance_after = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class CreditDetailSerializer(serializers.Serializer):
    account = CreditAccountSerializer()
    ledger = CreditLedgerEntrySerializer(many=True)


class TopUpSerializer(serializers.Serializer):
    credits = serializers.IntegerField(min_value=1)


class TopUpResultSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["paid", "redirect"])
    url = serializers.CharField(allow_blank=True)
    account = CreditAccountSerializer()


class EntitlementsSerializer(serializers.Serializer):
    plan = serializers.CharField(allow_null=True)
    status = serializers.CharField(allow_null=True)
    features = serializers.DictField(child=serializers.BooleanField())
    limits = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    required_plans = serializers.DictField(child=serializers.CharField())
