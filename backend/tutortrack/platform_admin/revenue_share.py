"""Revenue-share reconciliation (G6, E30 FR-30-7).

Organisations on a revenue-share plan (E04: a percentage of the card and direct debit
payments taken through TutorTrack) report each day's processed total to the Stripe meter
(``subscriptions.services.report_revenue``, a ``MeterReport`` per day). Reconciliation
compares, per organisation and month, what was processed (recomputed now from the
payments, so late payments and refunds show up) with what was reported to the meter, and
lists days that were never reported. Staff can report the missing days from the console;
other differences (refunds after the day was reported) are shown for a manual credit,
because meter events can't be negative.

Reads span organisations through each organisation's own tenant context (RLS applies).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from tutortrack.core.context import tenant_context
from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.money import Money
from tutortrack.core.time import now


def _days(month: date) -> list[date]:
    last = monthrange(month.year, month.month)[1]
    yesterday = now().date() - timedelta(days=1)
    return [d for d in (month.replace(day=n) for n in range(1, last + 1)) if d <= yesterday]


def share_organisations() -> list[str]:
    """Organisations whose plan has a revenue-share price in their currency."""
    from django.db.models import Exists, OuterRef

    from tutortrack.subscriptions.models import PlanPrice, Subscription

    shares = PlanPrice.objects.using(PLATFORM_DB_ALIAS).filter(
        plan=OuterRef("plan"),
        currency=OuterRef("currency"),
        component=PlanPrice.Component.REVENUE_SHARE,
    )
    return [
        str(pk)
        for pk in Subscription.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(Exists(shares))
        .exclude(stripe_customer_id="")
        .values_list("organisation_id", flat=True)
    ]


def reconcile_organisation(month: date) -> dict[str, Any] | None:
    """One organisation (in its tenant context) for one calendar month."""
    from tutortrack.payments.selectors import processed_totals
    from tutortrack.subscriptions.models import MeterReport, PlanPrice, Subscription
    from tutortrack.subscriptions.services import REVENUE_METER
    from tutortrack.tenancy.models import Organisation

    subscription = Subscription.objects.select_related("plan").first()
    if subscription is None:
        return None
    price = PlanPrice.objects.filter(
        plan=subscription.plan,
        currency=subscription.currency,
        component=PlanPrice.Component.REVENUE_SHARE,
    ).first()
    if price is None:
        return None
    currency = str(subscription.currency)
    days = _days(month)
    reports = {
        r.period_date: r
        for r in MeterReport.objects.filter(
            meter=REVENUE_METER,
            period_date__gte=month,
            period_date__lte=days[-1] if days else month,
        )
    }
    processed = Decimal(0)
    unreported: list[str] = []
    late: list[str] = []
    for day in days:
        start = datetime.combine(day, time(0), tzinfo=UTC)
        amount = processed_totals(start, start + timedelta(days=1)).get(currency) or Decimal(0)
        processed += amount
        report = reports.get(day)
        if report is None or report.reported_at is None:
            if amount:
                unreported.append(day.isoformat())
        elif Money(amount, currency).to_minor() != report.quantity:
            late.append(day.isoformat())
    reported_minor = (
        MeterReport.objects.filter(
            meter=REVENUE_METER,
            period_date__in=days,
            reported_at__isnull=False,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    reported = Money.from_minor(int(reported_minor), currency).amount
    percent = price.unit_amount
    org = Organisation.objects.get(pk=subscription.organisation_id)

    def fee(value: Decimal) -> str:
        return str(Money(value * percent / Decimal(100), currency).round_to_minor().amount)

    difference = processed - reported
    return {
        "organisation_id": str(org.pk),
        "organisation_name": org.name,
        "currency": currency,
        "percent": str(percent),
        "processed": str(Money(processed, currency).round_to_minor().amount),
        "reported": str(reported),
        "difference": str(Money(difference, currency).round_to_minor().amount),
        "expected_fee": fee(processed),
        "reported_fee": fee(reported),
        "unreported_days": unreported,
        "changed_days": late,
        "ok": not unreported and not late and difference == 0,
    }


def reconcile(month: date) -> dict[str, Any]:
    rows = []
    for org_id in share_organisations():
        with tenant_context(org_id):
            row = reconcile_organisation(month)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: (r["ok"], r["organisation_name"]))
    totals: dict[str, dict[str, str]] = {}
    for row in rows:
        bucket = totals.setdefault(
            row["currency"], {"processed": "0", "reported": "0", "expected_fee": "0"}
        )
        for key in bucket:
            bucket[key] = str(Decimal(bucket[key]) + Decimal(row[key]))
    return {"month": month.isoformat()[:7], "rows": rows, "totals": totals}


def report_missing(organisation_id: str, month: date) -> int:
    """Report the month's unreported days to the meter (idempotent per day). Audited in the
    organisation's log by ``report_revenue``'s ``MeterReport`` rows and here."""
    from django.db import transaction

    from tutortrack.core import audit
    from tutortrack.subscriptions import services as subscriptions
    from tutortrack.subscriptions.models import Subscription

    sent = 0
    with tenant_context(organisation_id):
        row = reconcile_organisation(month)
        if row is None:
            return 0
        for day in row["unreported_days"]:
            with transaction.atomic():
                if subscriptions.report_revenue(date.fromisoformat(day)) is not None:
                    sent += 1
        subscription = Subscription.objects.first()
        if subscription is not None and sent:
            with transaction.atomic():
                audit.record(
                    subscription,
                    "revenue_share_reported",
                    {"month": [None, month.isoformat()[:7]], "days": [None, sent]},
                )
    return sent
