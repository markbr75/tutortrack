"""Resolves an organisation's entitlements (FR-04-2): unexpired platform override > plan
(the trial plan while trialing) > nothing. Organisations without a subscription (created
before E04, or internal) are not limited.

Snapshots are cached per organisation and invalidated whenever the subscription or an
override changes, so an upgrade takes effect on the next request.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from tutortrack.core.context import current_organisation_id, tenant_context
from tutortrack.core.time import now

from .catalogue import FEATURES, LIMITS

CACHE_TTL_SECONDS = 300
UNLIMITED = None


def _version_key(organisation_id: Any) -> str:
    return f"ent:v:{organisation_id}"


def invalidate(organisation_id: Any) -> None:
    key = _version_key(organisation_id)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 2, None)


PLANS_VERSION_KEY = "ent:plans:v"


def invalidate_all() -> None:
    """A plan's entitlements changed (platform console): every snapshot may be stale."""
    cache.delete("ent:required-plans")
    try:
        cache.incr(PLANS_VERSION_KEY)
    except ValueError:
        cache.set(PLANS_VERSION_KEY, 2, None)


def _version(organisation_id: Any) -> int:
    version = cache.get(_version_key(organisation_id))
    if version is None:
        version = 1
        cache.set(_version_key(organisation_id), version, None)
    return int(version)


def effective_plan_key(subscription: Any) -> str:
    if subscription.status == subscription.Status.TRIALING:
        return str(settings.SUBSCRIPTIONS["TRIAL_PLAN"])
    return str(subscription.plan.key)


def _compute(organisation_id: Any) -> dict[str, Any] | None:
    from .models import EntitlementOverride, PlanEntitlement, Subscription

    with tenant_context(organisation_id):
        subscription = Subscription.objects.select_related("plan").first()
        if subscription is None:
            return None
        plan_key = effective_plan_key(subscription)
        features = dict.fromkeys(FEATURES, False)
        limits: dict[str, int | None] = dict.fromkeys(LIMITS, 0)
        for row in PlanEntitlement.objects.filter(plan__key=plan_key):
            if row.key in FEATURES:
                features[row.key] = bool(row.bool_value)
            elif row.key in LIMITS:
                limits[row.key] = row.int_value
        overrides = EntitlementOverride.objects.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now())
        )
        for override in overrides:
            if override.key in FEATURES and override.bool_value is not None:
                features[override.key] = override.bool_value
            elif override.key in LIMITS:
                limits[override.key] = UNLIMITED if override.unlimited else override.int_value
        return {"plan": plan_key, "status": subscription.status, "features": features,
                "limits": limits}  # fmt: skip


def snapshot(organisation_id: Any = None) -> dict[str, Any] | None:
    org_id = organisation_id or current_organisation_id()
    if org_id is None:
        return None
    plans = cache.get(PLANS_VERSION_KEY) or 1
    key = f"ent:{plans}:{_version(org_id)}:{org_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None  # {} caches "no subscription"
    value = _compute(org_id)
    cache.set(key, value or {}, CACHE_TTL_SECONDS)
    return value


class PlanResolver:
    """Registered with ``core.entitlements`` at start-up."""

    def has(self, key: str, organisation_id: uuid.UUID | None) -> bool:
        snap = snapshot(organisation_id)
        if snap is None:
            return True
        return bool(snap["features"].get(key, False))

    def limit(self, key: str, organisation_id: uuid.UUID | None) -> int | None:
        snap = snapshot(organisation_id)
        if snap is None:
            return UNLIMITED
        return snap["limits"].get(key, 0)

    def required_plan(self, key: str, needed: int | None = None) -> str | None:
        return cheapest_plan_with(key, needed)


def cheapest_plan_with(key: str, needed: int | None = None) -> str | None:
    """The lowest-ranked public plan that grants ``key`` (or a limit of ``needed``)."""
    from .models import Plan, PlanEntitlement

    rows = (
        PlanEntitlement.objects.filter(key=key, plan__visibility=Plan.Visibility.PUBLIC)
        .select_related("plan")
        .order_by("plan__rank", "plan__key")
    )
    for row in rows:
        if key in FEATURES and row.bool_value:
            return row.plan.key
        if key in LIMITS and (row.int_value is None or (needed or 0) <= row.int_value):
            return row.plan.key
    return "enterprise"


def plan_key_for(organisation_id: uuid.UUID) -> str | None:
    """``core.flags`` plan resolver: lets feature flags target plans."""
    snap = snapshot(organisation_id)
    return snap["plan"] if snap else None
