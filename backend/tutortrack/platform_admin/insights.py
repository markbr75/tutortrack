"""The nightly per-organisation facts behind the console's health and SaaS metrics pages
(E30 FR-30-6/7). ``record_day`` runs inside one organisation's tenant context (RLS
applies); ``targets`` and ``send_churn_alerts`` are platform-wide and use the BYPASSRLS
connection, which only this app may use.

Rows are written with ``update_or_create`` on (organisation, date), so a retried or
repeated run for the same day replaces that day's numbers instead of adding to them.
These are computed facts, not user changes, so they aren't written to the audit log.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core.context import require_organisation_id
from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.time import now

from . import health, metrics
from .models import SubscriptionSnapshot, TenantHealthScore

logger = structlog.get_logger(__name__)
SCORED_STATUSES = ("trial", "active", "past_due", "suspended")


def targets() -> list[str]:
    """Organisations to score: everything not cancelled (closing organisations stop)."""
    from tutortrack.tenancy.models import Organisation

    return [
        str(pk)
        for pk in Organisation.objects.using(PLATFORM_DB_ALIAS)
        .filter(status__in=SCORED_STATUSES)
        .order_by("created_at")
        .values_list("pk", flat=True)
    ]


def subscription_value() -> dict[str, Any]:
    """Plan, status and monthly value of the subscription of the organisation in context."""
    from tutortrack.subscriptions.models import PlanPrice, Subscription
    from tutortrack.tenancy.models import Branch

    subscription = Subscription.objects.select_related("plan").first()
    if subscription is None:
        return {
            "plan_key": "",
            "status": "",
            "interval": "",
            "currency": "",
            "seats": 0,
            "mrr": Decimal(0),
        }
    branches = Branch.objects.filter(archived_at__isnull=True).count()
    prices = [
        metrics.PriceComponent(p.component, p.unit_amount, p.included_quantity)
        for p in PlanPrice.objects.filter(
            plan=subscription.plan,
            currency=subscription.currency,
            interval=subscription.interval,
        )
    ]
    mrr = metrics.subscription_mrr(
        prices,
        seats=subscription.seats,
        branches=branches,
        interval=subscription.interval,
        currency=str(subscription.currency),
    )
    return {
        "plan_key": subscription.plan.key,
        "status": subscription.status,
        "interval": subscription.interval,
        "currency": str(subscription.currency),
        "seats": subscription.seats,
        "mrr": mrr,
    }


@transaction.atomic
def record_day(day: date) -> dict[str, Any]:
    """Snapshot the subscription and score health for the organisation in context."""
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    values = subscription_value()
    SubscriptionSnapshot.objects.update_or_create(
        date=day, defaults={**values, "signed_up_on": org.created_at.date()}
    )
    inputs = health.collect_inputs()
    value, risk, parts = health.score(inputs)
    previous = TenantHealthScore.objects.filter(date__lt=day).order_by("-date").first()
    row, _created = TenantHealthScore.objects.update_or_create(
        date=day,
        defaults={
            "score": value,
            "risk": risk,
            "components": parts,
            "inputs": health.as_dict(inputs),
        },
    )
    newly_at_risk = (
        risk == TenantHealthScore.Risk.AT_RISK
        and previous is not None
        and previous.risk != TenantHealthScore.Risk.AT_RISK
        and row.alerted_at is None
    )
    return {"score": value, "risk": risk, "newly_at_risk": newly_at_risk}


def send_churn_alerts(day: date, organisation_ids: list[str]) -> int:
    """One email to platform staff listing organisations that became at risk (once per
    organisation and day: ``alerted_at``). Organisation names and scores only."""
    from tutortrack.identity.models import User
    from tutortrack.tenancy.models import Organisation

    rows = list(
        TenantHealthScore.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(date=day, organisation_id__in=organisation_ids, alerted_at__isnull=True)
        .order_by("score")
    )
    if not rows:
        return 0
    names = dict(
        Organisation.objects.using(PLATFORM_DB_ALIAS)
        .filter(pk__in=[r.organisation_id for r in rows])
        .values_list("pk", "name")
    )
    recipients = list(
        User.objects.filter(is_platform_staff=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    lines = [f"- {names.get(r.organisation_id, r.organisation_id)}: {r.score}/100" for r in rows]
    link = f"{settings.PLATFORM_BASE_URL}/platform/health?risk=at_risk"
    if recipients:
        send_mail(
            _("%(count)s organisations became at risk") % {"count": len(rows)},
            "\n".join([_("These organisations' health scores fell below 40:"), *lines, "", link]),
            None,
            recipients,
        )
    TenantHealthScore.all_tenants.using(PLATFORM_DB_ALIAS).filter(
        pk__in=[r.pk for r in rows]
    ).update(alerted_at=now())
    logger.info("platform.churn_alerts", count=len(rows), recipients=len(recipients))
    return len(rows)
