"""G6 (FR-04-1): add-ons bought in the app through Stripe Billing grant entitlements."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tutortrack.core import entitlements as core_entitlements
from tutortrack.core.context import tenant_context
from tutortrack.subscriptions import addons, services
from tutortrack.subscriptions.models import SubscriptionAddon

from .test_subscriptions import event_types, fake_sub, owner_api, role_api, subscribe, trial

pytestmark = pytest.mark.django_db


def test_the_shop_lists_add_ons_with_prices_in_the_subscription_currency(org):
    subscribe(org, "solo")
    rows = {r["key"]: r for r in owner_api(org).get("/api/v1/subscription/addons").json()}
    assert set(rows) == {"custom_domain", "white_label", "priority_support"}
    assert rows["custom_domain"]["price"] == {"amount": "10.00", "currency": "GBP"}
    assert rows["custom_domain"]["active"] is False


def test_buying_an_add_on_adds_a_stripe_item_and_grants_the_feature(org):
    subscription = subscribe(org, "solo")
    with tenant_context(org):
        assert not core_entitlements.has("custom_domain")
    api = owner_api(org)
    response = api.post("/api/v1/subscription/addons/custom_domain", HTTP_IDEMPOTENCY_KEY="buy-1")
    assert response.status_code == 201, response.content
    assert response.json()["active"] is True
    items = fake_sub(subscription)["items"]
    assert "tt-addon:custom_domain:GBP:month" in items
    assert any(ref.startswith("tt:solo:") for ref in items)  # the plan is untouched
    with tenant_context(org):
        assert core_entitlements.has("custom_domain")
        assert SubscriptionAddon.objects.get().status == "active"
    assert "subscription.changed" in event_types(org)
    # Buying again is harmless.
    again = api.post("/api/v1/subscription/addons/custom_domain")
    assert again.status_code == 201
    with tenant_context(org):
        assert SubscriptionAddon.objects.count() == 1


def test_add_ons_stay_when_the_plan_changes_and_stop_on_cancel(org):
    subscription = subscribe(org, "solo")
    with tenant_context(org):
        addons.purchase("priority_support")
        services.change_plan("team", "month")
    items = fake_sub(subscription)["items"]
    assert "tt-addon:priority_support:GBP:month" in items
    response = owner_api(org).delete("/api/v1/subscription/addons/priority_support")
    assert response.status_code == 200, response.content
    assert "tt-addon:priority_support:GBP:month" not in fake_sub(subscription)["items"]
    with tenant_context(org):
        assert not core_entitlements.has("priority_support")
        assert SubscriptionAddon.objects.get().status == "cancelled"


def test_an_add_on_removed_in_stripes_portal_ends(org):
    subscription = subscribe(org, "solo")
    with tenant_context(org):
        addons.purchase("white_label")
        remote = fake_sub(subscription)
        remote["items"].pop("tt-addon:white_label:GBP:month")
        current = services.current()
        assert addons.reconcile_remote(current, tuple(remote["items"])) == 1
        assert SubscriptionAddon.objects.get().status == "cancelled"


def test_a_trial_without_a_card_is_sent_to_checkout(org):
    trial(org)
    response = owner_api(org).post("/api/v1/subscription/addons/custom_domain")
    assert response.status_code == 422
    assert response.json()["code"] == "checkout_required"


def test_only_the_owner_buys(org):
    subscribe(org, "solo")
    assert (
        role_api(org, "finance").post("/api/v1/subscription/addons/custom_domain").status_code
        == 403
    )


def test_catalogue_prices_and_included_flags(org):
    subscribe(org, "solo")
    with tenant_context(org):
        rows = {r["key"]: r for r in addons.catalogue(services.current())}
        assert rows["priority_support"]["included_in_plan"] is False
        assert rows["white_label"]["price"].amount == Decimal("49")
