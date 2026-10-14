"""Add-ons bought in the app (G6, FR-04-1): custom domain, white-label apps and priority
support.

An add-on is an extra recurring item on the organisation's Stripe subscription, in the
subscription's currency and interval, prorated when it starts or stops. While its
``SubscriptionAddon`` row is active the add-on's feature is granted (``entitlements``), on
top of the plan (an entitlement override can still switch it off). ``items_for`` keeps
active add-ons on the subscription when the plan changes, and an add-on removed from the
subscription in Stripe's billing portal is marked cancelled when the subscription update
arrives (``reconcile_remote``). Buying needs a paid subscription: during a trial without a
card the owner is sent to checkout first.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money
from tutortrack.core.time import now

from .catalogue import ADDONS, addon_def
from .gateway import GatewayError, Item, get_gateway
from .models import AddonPrice, Subscription, SubscriptionAddon

PREFIX = "tt-addon:"


def addon_ref(price: AddonPrice) -> str:
    """The Stripe price id, or a stable stand-in for the fake gateway."""
    return price.stripe_price_id or (f"{PREFIX}{price.addon}:{price.currency}:{price.interval}")


def addon_price_for_ref(ref: str) -> AddonPrice | None:
    found = AddonPrice.objects.filter(stripe_price_id=ref).first() if ref else None
    if found is not None or not ref.startswith(PREFIX):
        return found
    addon, currency, interval = [*ref.removeprefix(PREFIX).split(":"), "", "", ""][:3]
    return AddonPrice.objects.filter(addon=addon, currency=currency, interval=interval).first()


def price_for(addon: str, currency: str, interval: str) -> AddonPrice | None:
    return AddonPrice.objects.filter(addon=addon, currency=currency, interval=interval).first()


def active() -> dict[str, SubscriptionAddon]:
    return {
        a.addon: a for a in SubscriptionAddon.objects.filter(status=SubscriptionAddon.Status.ACTIVE)
    }


def addon_items(currency: str, interval: str) -> list[Item]:
    items = []
    for key in active():
        price = price_for(key, str(currency), interval)
        if price is not None:
            items.append(Item(addon_ref(price), 1))
    return items


def catalogue(subscription: Subscription | None) -> list[dict[str, Any]]:
    """Every add-on with its price for this subscription and whether it is active or already
    included in the plan."""
    from . import entitlements

    bought = active()
    snap = entitlements.snapshot() or {}
    out = []
    for definition in ADDONS:
        price = None
        if subscription is not None:
            row = price_for(definition.key, str(subscription.currency), subscription.interval)
            if row is not None:
                price = Money(row.unit_amount, row.currency)
        included = definition.key not in bought and bool(
            (snap.get("features") or {}).get(definition.feature)
        )
        out.append(
            {
                "key": definition.key,
                "name": str(definition.name),
                "description": str(definition.description),
                "feature": definition.feature,
                "price": price,
                "interval": subscription.interval if subscription else "month",
                "active": definition.key in bought,
                "included_in_plan": included,
                "started_at": bought[definition.key].started_at
                if definition.key in bought
                else None,
            }
        )
    return out


def _locked_subscription() -> Subscription:
    from .services import _locked

    return _locked()


def _push(subscription: Subscription) -> None:
    """Send the subscription's items (plan + active add-ons) to Stripe, prorated."""
    from .services import _apply_remote, items_for

    items = items_for(subscription, subscription.plan, subscription.interval)
    try:
        remote = get_gateway().update_items(
            subscription.stripe_subscription_id, items, prorate=True
        )
    except GatewayError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    _apply_remote(subscription, remote)


@transaction.atomic
def purchase(key: str, *, user: Any = None) -> SubscriptionAddon:
    from .services import _changed

    definition = addon_def(key)
    if definition is None:
        raise NotFound(_("Unknown add-on."))
    subscription = _locked_subscription()
    if not subscription.stripe_subscription_id or subscription.status not in (
        Subscription.Status.ACTIVE,
        Subscription.Status.PAST_DUE,
    ):
        raise BusinessRuleViolation(
            _("Choose a plan and add a payment method before buying add-ons."),
            extra={"code": "checkout_required"},
        )
    if key in active():
        return active()[key]
    if price_for(key, str(subscription.currency), subscription.interval) is None:
        raise BusinessRuleViolation(
            _("This add-on isn't available in your currency. Contact us to set it up."),
            extra={"code": "contact_sales"},
        )
    addon = SubscriptionAddon.objects.create(addon=key, started_at=now())
    price = price_for(key, str(subscription.currency), subscription.interval)
    addon.price_ref = addon_ref(price) if price else ""
    addon.save(update_fields=["price_ref", "updated_at"])
    _push(subscription)
    audit.record_create(addon)
    _changed(subscription, "addon")
    return addon


@transaction.atomic
def cancel(key: str, *, user: Any = None) -> SubscriptionAddon:
    from .services import _changed

    subscription = _locked_subscription()
    addon = active().get(key)
    if addon is None:
        raise NotFound(_("This add-on isn't active."))
    with audit.track(addon, action="cancel"):
        addon.status = SubscriptionAddon.Status.CANCELLED
        addon.cancelled_at = now()
        addon.save(update_fields=["status", "cancelled_at", "updated_at"])
    if subscription.stripe_subscription_id:
        _push(subscription)
    _changed(subscription, "addon")
    return addon


def reconcile_remote(subscription: Subscription, price_ids: tuple[str, ...]) -> int:
    """Add-ons no longer on the remote subscription (removed in Stripe's portal) end."""
    if not price_ids:
        return 0
    remote = set(price_ids)
    ended = 0
    for addon in active().values():
        if addon.price_ref and addon.price_ref not in remote:
            with audit.track(addon, action="cancel"):
                addon.status = SubscriptionAddon.Status.CANCELLED
                addon.cancelled_at = now()
                addon.save(update_fields=["status", "cancelled_at", "updated_at"])
            ended += 1
    return ended
