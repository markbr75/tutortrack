"""Our own SaaS subscription (E04): plans, prices, entitlements, each organisation's
subscription, entitlement overrides and the SMS/AI credit ledger.

``Plan``, ``PlanPrice``, ``PlanEntitlement`` and ``CustomerRoute`` are platform tables (the
catalogue, and webhook routing before any tenant is known), so they have no RLS policy.
Everything an organisation owns is a ``TenantModel``.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField
from tutortrack.core.ids import new_id
from tutortrack.core.models import TenantModel, TimeStampedModel


class Interval(models.TextChoices):
    MONTH = "month", _("Monthly")
    YEAR = "year", _("Annual")


class Plan(TimeStampedModel):
    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Public")
        LEGACY = "legacy", _("Legacy (existing subscribers only)")
        CUSTOM = "custom", _("Custom (contact sales)")

    class SeatMode(models.TextChoices):
        ACTIVE = "active", _("Every active tutor")
        DELIVERED = "delivered", _("Tutors with a completed lesson in the period")

    id = models.UUIDField(primary_key=True, default=new_id, editable=False)
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True, default="")
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    rank = models.PositiveSmallIntegerField(default=0, help_text="Higher = bigger plan")
    trial_days = models.PositiveSmallIntegerField(default=30)
    seat_mode = models.CharField(
        max_length=10, choices=SeatMode.choices, default=SeatMode.DELIVERED
    )

    class Meta:
        ordering = ["rank", "key"]

    def __str__(self) -> str:
        return self.key


class PlanPrice(models.Model):
    """One pricing component of a plan in one currency and interval. ``revenue_share``
    prices hold a percentage in ``unit_amount``; the others an amount per unit."""

    class Component(models.TextChoices):
        BASE_FEE = "base_fee", _("Base fee")
        ACTIVE_TUTOR = "active_tutor", _("Per active tutor")
        REVENUE_SHARE = "revenue_share", _("Share of payments processed")
        BRANCH = "branch", _("Per extra branch")

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="prices")
    currency = CurrencyField()
    interval = models.CharField(max_length=5, choices=Interval.choices)
    component = models.CharField(max_length=20, choices=Component.choices)
    unit_amount = models.DecimalField(max_digits=12, decimal_places=4)
    included_quantity = models.PositiveIntegerField(default=0)
    stripe_price_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        ordering = ["plan", "currency", "interval", "component"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "currency", "interval", "component"], name="plan_price_unique"
            )
        ]

    def __str__(self) -> str:
        return f"{self.plan_id}:{self.currency}:{self.interval}:{self.component}"


class PlanEntitlement(models.Model):
    """A feature (``bool_value``) or limit (``int_value``; empty = unlimited)."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="entitlements")
    key = models.CharField(max_length=50)
    bool_value = models.BooleanField(null=True, blank=True)
    int_value = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "key"], name="plan_entitlement_unique")
        ]

    def __str__(self) -> str:
        return f"{self.plan_id}:{self.key}"


class CustomerRoute(models.Model):
    """Platform routing for Stripe Billing webhooks: customer → organisation."""

    customer_ref = models.CharField(max_length=100, unique=True)
    organisation_id = models.UUIDField(unique=True)

    def __str__(self) -> str:
        return self.customer_ref


class Subscription(TenantModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", _("Trial")
        ACTIVE = "active", _("Active")
        PAST_DUE = "past_due", _("Payment overdue")
        SUSPENDED = "suspended", _("Suspended (read-only)")
        CANCELLED = "cancelled", _("Cancelled (read-only)")

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    interval = models.CharField(max_length=5, choices=Interval.choices, default=Interval.MONTH)
    currency = CurrencyField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIALING)

    stripe_customer_id = models.CharField(max_length=100, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=100, blank=True, default="")
    payment_method = models.JSONField(default=dict, blank=True)  # {brand, last4} for display

    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)

    # Downgrades and interval switches wait for the period end (FR-04-5).
    pending_plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    pending_interval = models.CharField(max_length=5, choices=Interval.choices, blank=True)

    cancel_at_period_end = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=50, blank=True, default="")
    cancellation_feedback = models.TextField(blank=True, default="")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    past_due_since = models.DateTimeField(null=True, blank=True)
    seats = models.PositiveIntegerField(default=0, help_text="Billable tutors last synced")
    seats_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organisation"], name="subscription_one_per_org")
        ]

    def __str__(self) -> str:
        return f"{self.plan_id} ({self.status})"


class EntitlementOverride(TenantModel):
    """Platform admin grants (FR-04-2): turn a feature on or raise a limit, optionally
    until a date. ``unlimited`` lifts a limit entirely."""

    key = models.CharField(max_length=50)
    bool_value = models.BooleanField(null=True, blank=True)
    int_value = models.PositiveIntegerField(null=True, blank=True)
    unlimited = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )  # fmt: skip

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "key"], name="entitlement_override_unique"
            )
        ]

    def __str__(self) -> str:
        return self.key


class CreditType(models.TextChoices):
    SMS = "sms", _("SMS credits")
    AI = "ai", _("AI credits")


class CreditAccount(TenantModel):
    """Balance and settings for one credit type (FR-04-8). The monthly allowance is used
    first and resets each period; purchased credits carry over."""

    credit_type = models.CharField(max_length=5, choices=CreditType.choices)
    allowance = models.PositiveIntegerField(default=0)
    included_balance = models.PositiveIntegerField(default=0)
    purchased_balance = models.IntegerField(default=0)  # negative = overage owed
    used_this_period = models.PositiveIntegerField(default=0)
    period_started_at = models.DateTimeField(null=True, blank=True)
    auto_top_up = models.BooleanField(default=False)
    top_up_pack = models.PositiveIntegerField(default=500)
    low_threshold = models.PositiveIntegerField(default=20)
    allow_overage = models.BooleanField(default=False)
    low_notified = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "credit_type"], name="credit_account_unique"
            )
        ]

    @property
    def balance(self) -> int:
        return self.included_balance + self.purchased_balance

    def __str__(self) -> str:
        return f"{self.credit_type}: {self.balance}"


class UsageCreditLedger(TenantModel):
    """Every movement of credits (immutable)."""

    class Reason(models.TextChoices):
        GRANT = "grant", _("Monthly allowance")
        EXPIRY = "expiry", _("Unused allowance expired")
        PURCHASE = "purchase", _("Top-up")
        CONSUMPTION = "consumption", _("Used")
        ADJUSTMENT = "adjustment", _("Adjustment")

    credit_type = models.CharField(max_length=5, choices=CreditType.choices)
    delta = models.IntegerField()
    reason = models.CharField(max_length=12, choices=Reason.choices)
    ref = models.CharField(max_length=120, blank=True, default="")
    balance_after = models.IntegerField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "credit_type", "created_at"])]

    def __str__(self) -> str:
        return f"{self.credit_type} {self.delta:+d}"


class CreditPurchase(TenantModel):
    """A top-up being paid for; credits are granted once (``completed_at``)."""

    credit_type = models.CharField(max_length=5, choices=CreditType.choices)
    credits = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = CurrencyField()
    automatic = models.BooleanField(default=False)
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.credits} {self.credit_type}"


class MeterReport(TenantModel):
    """One usage figure sent to Stripe Billing Meters (idempotent per identifier)."""

    meter = models.CharField(max_length=40)
    period_date = models.DateField()
    quantity = models.BigIntegerField()
    identifier = models.CharField(max_length=120)
    reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["identifier"], name="meter_report_identifier_unique")
        ]

    def __str__(self) -> str:
        return self.identifier


class BillingEvent(TenantModel):
    """Raw Stripe Billing webhook (our platform account), stored then processed."""

    event_id = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["event_id"], name="billing_event_unique"),
        ]
        indexes = [models.Index(fields=["type"], condition=Q(processed_at__isnull=True),
                                name="billing_event_unprocessed")]  # fmt: skip

    def __str__(self) -> str:
        return f"{self.type} {self.event_id}"
