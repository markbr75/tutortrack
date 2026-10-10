"""Read side of the platform console (E30).

Lists that span organisations read through the BYPASSRLS ``platform`` connection, which is
only reachable from this app (``core.tests.test_rls``). Anything about one organisation is
read inside that organisation's tenant context instead, so RLS still applies.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.time import now
from tutortrack.tenancy.models import Organisation


def tenants(
    *,
    search: str = "",
    status: str = "",
    plan: str = "",
    region: str = "",
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    active_since: datetime | None = None,
) -> QuerySet[Organisation]:
    from tutortrack.identity.models import Membership
    from tutortrack.subscriptions.models import Subscription

    subs = Subscription.all_tenants.using(PLATFORM_DB_ALIAS).filter(organisation=OuterRef("pk"))
    members = Membership.all_tenants.using(PLATFORM_DB_ALIAS).filter(
        organisation=OuterRef("pk"), status=Membership.Status.ACTIVE
    )
    qs = Organisation.objects.using(PLATFORM_DB_ALIAS).annotate(
        plan_key=Subquery(subs.values("plan__key")[:1]),
        subscription_status=Subquery(subs.values("status")[:1]),
        billing_interval=Subquery(subs.values("interval")[:1]),
        billing_currency=Subquery(subs.values("currency")[:1]),
        seats=Subquery(subs.values("seats")[:1]),
        trial_ends_at=Subquery(subs.values("trial_ends_at")[:1]),
        last_activity=Subquery(
            members.exclude(last_active_at__isnull=True)
            .order_by("-last_active_at")
            .values("last_active_at")[:1]
        ),
        member_count=Coalesce(
            Subquery(
                members.order_by().values("organisation").annotate(n=Count("id")).values("n")[:1]
            ),
            0,
        ),
    )
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(slug__icontains=search)
            | Q(contact_email__icontains=search)
        )  # fmt: skip
    if status:
        qs = qs.filter(status=status)
    if plan:
        qs = qs.filter(plan_key=plan)
    if region:
        qs = qs.filter(region=region)
    if created_after:
        qs = qs.filter(created_at__gte=created_after)
    if created_before:
        qs = qs.filter(created_at__lt=created_before)
    if active_since:
        qs = qs.filter(last_activity__gte=active_since)
    return qs


def monthly_revenue(row: Any) -> dict[str, str] | None:
    """Approximate MRR from list prices: base fee, billable tutors and the plan's interval
    (annual prices / 12). Revenue share and custom contracts aren't included."""
    from tutortrack.subscriptions.models import PlanPrice

    if not row.plan_key or row.subscription_status not in ("active", "past_due"):
        return None
    prices = PlanPrice.objects.filter(
        plan__key=row.plan_key, currency=row.billing_currency, interval=row.billing_interval
    )
    total = Decimal(0)
    for price in prices:
        if price.component == PlanPrice.Component.BASE_FEE:
            total += price.unit_amount
        elif price.component == PlanPrice.Component.ACTIVE_TUTOR:
            total += price.unit_amount * max(0, (row.seats or 0) - price.included_quantity)
    if row.billing_interval == "year":
        total /= 12
    return {"amount": str(total.quantize(Decimal("0.01"))), "currency": row.billing_currency}


def tenant_detail(organisation: Organisation) -> dict[str, Any]:
    """Everything support needs about one organisation (read in its tenant context)."""
    from tutortrack.core.context import tenant_context
    from tutortrack.core.models import AuditEntry, OutboxEvent
    from tutortrack.identity.models import Membership
    from tutortrack.subscriptions import selectors as usage
    from tutortrack.subscriptions.models import EntitlementOverride, Subscription

    with tenant_context(organisation):
        subscription = Subscription.objects.select_related("plan", "pending_plan").first()
        memberships = list(
            Membership.objects.select_related("user").order_by("role", "user__email")[:200]
        )
        return {
            "organisation": organisation,
            "subscription": subscription,
            "overrides": list(EntitlementOverride.objects.order_by("key")),
            "usage": usage.usage_counts(),
            "members": memberships,
            "recent_errors": _recent_errors(),
            "dead_letters": OutboxEvent.objects.filter(
                organisation=organisation, dead_lettered_at__isnull=False
            ).count(),
            "audit": list(AuditEntry.objects.order_by("-created_at")[:25]),
        }


def _recent_errors() -> list[dict[str, Any]]:
    """Failed webhooks, Stripe Billing events and messages (in tenant context)."""
    from tutortrack.comms.models import Message
    from tutortrack.payments.models import ProviderWebhookEvent
    from tutortrack.subscriptions.models import BillingEvent

    out: list[dict[str, Any]] = []
    for row in ProviderWebhookEvent.objects.exclude(last_error="").order_by("-created_at")[:10]:
        out.append({"origin": "payments_webhook", "kind": row.type, "at": row.created_at,
                    "detail": row.last_error[:300]})  # fmt: skip
    for event in BillingEvent.objects.exclude(error="").order_by("-created_at")[:10]:
        out.append({"origin": "billing_webhook", "kind": event.type, "at": event.created_at,
                    "detail": event.error[:300]})  # fmt: skip
    for message in Message.objects.filter(status="failed").order_by("-created_at")[:10]:
        out.append({"origin": "message", "kind": f"{message.type_key}/{message.channel}",
                    "at": message.created_at, "detail": message.error[:300]})  # fmt: skip
    return sorted(out, key=lambda e: e["at"], reverse=True)[:20]


# --- operations (T04) ---------------------------------------------------------------------------


def dead_letters() -> QuerySet[Any]:
    from tutortrack.core.models import OutboxEvent

    return (
        OutboxEvent.objects.using(PLATFORM_DB_ALIAS)
        .filter(dead_lettered_at__isnull=False)
        .select_related("organisation")
        .order_by("-dead_lettered_at", "id")
    )


def queue_depths() -> dict[str, int]:
    """Messages waiting in each Celery queue (Redis lists)."""
    from tutortrack.core.redis import get_redis

    names = ["celery", "default", "comms", "billing"]
    try:
        client = get_redis()
        return {name: int(client.llen(name)) for name in names}
    except Exception:
        return {}


def operations() -> dict[str, Any]:
    from tutortrack.core.models import OutboxEvent
    from tutortrack.payments.models import ProviderWebhookEvent
    from tutortrack.subscriptions.models import BillingEvent

    outbox = OutboxEvent.objects.using(PLATFORM_DB_ALIAS)
    pending = outbox.filter(dispatched_at__isnull=True, dead_lettered_at__isnull=True)
    oldest = pending.order_by("occurred_at").values_list("occurred_at", flat=True).first()
    payments = ProviderWebhookEvent.all_tenants.using(PLATFORM_DB_ALIAS)
    billing = BillingEvent.all_tenants.using(PLATFORM_DB_ALIAS)
    return {
        "outbox_pending": pending.count(),
        "outbox_lag_seconds": int((now() - oldest).total_seconds()) if oldest else 0,
        "dead_letters": outbox.filter(dead_lettered_at__isnull=False).count(),
        "queues": queue_depths(),
        "payment_webhooks_unprocessed": payments.filter(processed_at__isnull=True).count(),
        "payment_webhooks_failed": payments.exclude(last_error="")
        .filter(processed_at__isnull=True)
        .count(),
        "billing_webhooks_unprocessed": billing.filter(processed_at__isnull=True).count(),
        "billing_webhooks_failed": billing.exclude(error="")
        .filter(processed_at__isnull=True)
        .count(),
        "dead_letters_by_type": list(
            outbox.filter(dead_lettered_at__isnull=False)
            .values("event_type")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        ),
    }
