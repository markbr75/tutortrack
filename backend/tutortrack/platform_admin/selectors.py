"""Read side of the platform console (E30).

Lists that span organisations read through the BYPASSRLS ``platform`` connection, which is
only reachable from this app (``core.tests.test_rls``). Anything about one organisation is
read inside that organisation's tenant context instead, so RLS still applies.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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


# --- Part 2: tenant health (T09) ----------------------------------------------------------------


def health_rows(*, risk: str = "", search: str = "", plan: str = "") -> QuerySet[Organisation]:
    """Organisations with their latest health score (unscored ones left out)."""
    from .models import TenantHealthScore

    latest = (
        TenantHealthScore.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(organisation=OuterRef("pk"))
        .order_by("-date")
    )
    qs = (
        tenants(search=search, plan=plan)
        .annotate(
            health_score=Subquery(latest.values("score")[:1]),
            health_risk=Subquery(latest.values("risk")[:1]),
            health_date=Subquery(latest.values("date")[:1]),
            health_components=Subquery(latest.values("components")[:1]),
        )
        .filter(health_score__isnull=False)
    )
    if risk:
        qs = qs.filter(health_risk=risk)
    return qs


def health_history(organisation: Organisation, days: int = 90) -> list[Any]:
    from .models import TenantHealthScore

    since = now().date() - timedelta(days=days)
    return list(
        TenantHealthScore.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(organisation=organisation, date__gte=since)
        .order_by("-date")
    )


def risk_counts() -> dict[str, int]:
    counts = {"healthy": 0, "watch": 0, "at_risk": 0}
    for value in health_rows().values_list("health_risk", flat=True):  # type: ignore[misc]
        if value in counts:
            counts[value] += 1
    return counts


# --- Part 2: SaaS metrics (T10) -----------------------------------------------------------------


def month_ends(months: int, today: date | None = None) -> list[date]:
    """The last day of each of the last ``months`` months, oldest first; the current month
    ends today."""
    cursor = today or now().date()
    ends = []
    for _ in range(months):
        ends.append(cursor)
        cursor = cursor.replace(day=1) - timedelta(days=1)
    return list(reversed(ends))


def snapshot_currencies() -> list[str]:
    from .models import SubscriptionSnapshot

    values = (
        SubscriptionSnapshot.all_tenants.using(PLATFORM_DB_ALIAS)
        .exclude(currency="")
        .order_by("currency")
        .values_list("currency", flat=True)
        .distinct()
    )
    return [str(c) for c in values]


def _month_states(currency: str, ends: list[date]) -> list[tuple[date, dict[str, Any]]]:
    from .metrics import OrgMonth
    from .models import SubscriptionSnapshot

    snaps = SubscriptionSnapshot.all_tenants.using(PLATFORM_DB_ALIAS).filter(currency=currency)
    out = []
    for end in ends:
        rows = (
            snaps.filter(date__gte=end.replace(day=1), date__lte=end)
            .order_by("organisation_id", "-date")
            .distinct("organisation_id")
            .values_list("organisation_id", "status", "mrr")
        )
        out.append((end, {str(o): OrgMonth(status, mrr) for o, status, mrr in rows}))
    return out


def saas_metrics(*, currency: str = "", months: int = 12) -> dict[str, Any]:
    """MRR/ARR, movements, churn, NRR, ARPA, trial conversion and cohort retention for one
    billing currency, from the nightly subscription snapshots (``metrics`` has the maths)."""
    from django.db.models import Case, IntegerField, Max, Min, When

    from . import metrics
    from .models import SubscriptionSnapshot

    currencies = snapshot_currencies()
    if not currency:
        currency = "GBP" if "GBP" in currencies or not currencies else currencies[0]
    ends = month_ends(max(1, min(months, 36)) + 1)
    states = _month_states(currency, ends)
    snaps = SubscriptionSnapshot.all_tenants.using(PLATFORM_DB_ALIAS).filter(currency=currency)
    first_paid = {
        str(row["organisation_id"]): row["first"]
        for row in snaps.filter(status__in=metrics.PAYING, mrr__gt=0)
        .values("organisation_id")
        .annotate(first=Min("date"))
    }
    trial_rows = snaps.values("organisation_id").annotate(
        signed=Min("signed_up_on"),
        trialed=Max(Case(When(status="trialing", then=1), default=0, output_field=IntegerField())),
        paid=Max(
            Case(
                When(status__in=metrics.PAYING, mrr__gt=0, then=1),
                default=0,
                output_field=IntegerField(),
            )
        ),
    )
    window_start = ends[1].replace(day=1)
    trials = metrics.trial_conversion(
        (r["signed"], bool(r["trialed"]), bool(r["paid"]))
        for r in trial_rows
        if r["signed"] and r["signed"] >= window_start
    )
    series = metrics.monthly_series(states, currency=currency, first_paid=first_paid)[1:]
    return {
        "currency": currency,
        "currencies": currencies or [currency],
        "months": series,
        "trial_conversion": trials,
        "cohorts": metrics.cohort_retention(states[1:], first_paid),
    }


# --- Part 2: NPS, CSAT and product usage (T09) --------------------------------------------------


def nps_summary(days: int = 90) -> dict[str, Any]:
    from django.db.models import Avg
    from django.db.models.functions import TruncMonth

    from tutortrack.subscriptions.models import Subscription
    from tutortrack.success.models import SurveyResponse

    from . import health

    since = now() - timedelta(days=days)
    surveys = SurveyResponse.all_tenants.using(PLATFORM_DB_ALIAS)
    answers = surveys.filter(kind="nps", score__isnull=False)
    recent = list(answers.filter(created_at__gte=since).values_list("organisation_id", "score"))
    scores = [int(score) for _org, score in recent]
    plans = dict(
        Subscription.all_tenants.using(PLATFORM_DB_ALIAS).values_list(
            "organisation_id", "plan__key"
        )
    )
    by_plan: dict[str, list[int]] = {}
    for org_id, score in recent:
        by_plan.setdefault(plans.get(org_id) or "", []).append(int(score))
    by_month: dict[date, list[int]] = {}
    monthly = (
        answers.filter(created_at__gte=now() - timedelta(days=365))
        .annotate(month=TruncMonth("created_at"))
        .values_list("month", "score")
    )
    for month, score in monthly:
        by_month.setdefault(month.date(), []).append(int(score))
    comments = (
        answers.filter(created_at__gte=since)
        .exclude(comment="")
        .select_related("organisation")
        .order_by("-created_at")[:25]
    )
    csat = surveys.filter(kind="csat", score__isnull=False, created_at__gte=since)
    average = csat.aggregate(avg=Avg("score"))["avg"]
    return {
        "days": days,
        "nps": health.nps(scores),
        "answers": len(scores),
        "dismissed": surveys.filter(kind="nps", score__isnull=True, created_at__gte=since).count(),
        "promoters": sum(1 for s in scores if s >= 9),
        "passives": sum(1 for s in scores if 7 <= s <= 8),
        "detractors": sum(1 for s in scores if s <= 6),
        "by_plan": [
            {"plan": plan, "nps": health.nps(values), "answers": len(values)}
            for plan, values in sorted(by_plan.items())
        ],
        "by_month": [
            {"month": month, "nps": health.nps(values), "answers": len(values)}
            for month, values in sorted(by_month.items())
        ],
        "comments": [
            {
                "organisation_id": c.organisation_id,
                "organisation": c.organisation.name,
                "score": c.score,
                "role": c.role,
                "comment": c.comment,
                "created_at": c.created_at,
            }
            for c in comments
        ],
        "csat_average": None
        if average is None
        else Decimal(str(average)).quantize(Decimal("0.01")),
        "csat_answers": csat.count(),
    }


SETUP_ORDER = ["service", "student", "lesson", "payments", "invoice"]


def usage_summary(days: int = 30) -> dict[str, Any]:
    """Feature usage from consented, pseudonymous events, and the onboarding funnel from the
    setup checklists of organisations that signed up in the last ``3 x days`` days."""
    from django.db.models.functions import TruncDate

    from tutortrack.success.models import ProductEvent, SetupChecklistItem

    since = now() - timedelta(days=days)
    events = ProductEvent.all_tenants.using(PLATFORM_DB_ALIAS).filter(occurred_at__gte=since)
    top = (
        events.values("name")
        .annotate(
            count=Count("id"),
            organisations=Count("organisation", distinct=True),
            people=Count("actor", distinct=True),
        )
        .order_by("-count", "name")[:25]
    )
    pages = (
        events.filter(name="page.viewed")
        .values("route")
        .annotate(count=Count("id"), people=Count("actor", distinct=True))
        .order_by("-count", "route")[:25]
    )
    daily = (
        events.annotate(day=TruncDate("occurred_at"))
        .values("day")
        .annotate(
            people=Count("actor", distinct=True),
            organisations=Count("organisation", distinct=True),
        )
        .order_by("day")
    )
    orgs = list(
        Organisation.objects.using(PLATFORM_DB_ALIAS)
        .filter(created_at__gte=now() - timedelta(days=days * 3))
        .values_list("pk", flat=True)
    )
    done: dict[Any, set[str]] = {}
    for org_id, key in (
        SetupChecklistItem.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(organisation_id__in=orgs)
        .values_list("organisation_id", "key")
    ):
        done.setdefault(org_id, set()).add(key)
    funnel = [{"step": "signed_up", "organisations": len(orgs)}]
    for i, step in enumerate(SETUP_ORDER):
        needed = set(SETUP_ORDER[: i + 1])
        reached = sum(1 for o in orgs if needed <= done.get(o, set()))
        funnel.append({"step": step, "organisations": reached})
    return {
        "days": days,
        "events": events.count(),
        "people": events.values("actor").distinct().count(),
        "organisations": events.values("organisation").distinct().count(),
        "top_events": list(top),
        "top_pages": list(pages),
        "daily": list(daily),
        "funnel": funnel,
    }


# --- Part 2: support inbox (T08) ----------------------------------------------------------------


def support_inbox(*, status: str = "", search: str = "") -> QuerySet[Any]:
    from tutortrack.success.models import SupportConversation

    qs = SupportConversation.all_tenants.using(PLATFORM_DB_ALIAS).select_related(
        "organisation", "opened_by", "assignee"
    )
    if status == "unread":
        qs = qs.filter(support_unread=True)
    elif status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(Q(subject__icontains=search) | Q(organisation__name__icontains=search))
    return qs


def support_organisation_id(conversation_id: Any) -> Any:
    """The organisation of a conversation (to enter its tenant context), or None."""
    from tutortrack.success.models import SupportConversation

    return (
        SupportConversation.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(pk=conversation_id)
        .values_list("organisation_id", flat=True)
        .first()
    )
