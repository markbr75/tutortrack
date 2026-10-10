"""E04: plans, entitlements, trials, checkout, plan changes, dunning state, seats, revenue
share, credits and the API."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import transaction

from tutortrack.comms import channels
from tutortrack.core import entitlements as core_entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import UpgradeRequired
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.subscriptions import credits, entitlements, services
from tutortrack.subscriptions.credits import SmsCreditMeter
from tutortrack.subscriptions.gateway.fake import FakeGateway
from tutortrack.subscriptions.models import (
    CreditAccount,
    Plan,
    PlanPrice,
    Subscription,
    UsageCreditLedger,
)
from tutortrack.tenancy.models import Organisation

pytestmark = pytest.mark.django_db


# --- helpers ------------------------------------------------------------------------------------


def owner_api(org: Organisation) -> Any:
    user = UserFactory()
    with tenant_context(org):
        MembershipFactory(organisation=org, user=user, role="owner")
    return client_for(org, user)


def role_api(org: Organisation, role: str) -> Any:
    user = UserFactory()
    with tenant_context(org):
        MembershipFactory(organisation=org, user=user, role=role)
    return client_for(org, user)


def trial(org: Organisation) -> Subscription:
    return services.start_trial(org)


def session_id(url: str) -> str:
    return parse_qs(urlparse(url).query)["checkout"][0]


def subscribe(org: Organisation, plan: str = "solo", interval: str = "month") -> Subscription:
    """A paying subscriber on ``plan`` (trial already over)."""
    trial(org)
    with tenant_context(org):
        Subscription.objects.update(
            plan=services.get_plan(plan), trial_ends_at=now() - timedelta(minutes=1)
        )
        url = services.checkout(plan, interval)
        services.complete_checkout(session_id(url))
        services.end_trial()
        return Subscription.objects.select_related("plan").get()


def event_types(org: Organisation) -> list[str]:
    with tenant_context(org):
        return list(OutboxEvent.objects.values_list("event_type", flat=True))


def fake_sub(subscription: Subscription) -> dict[str, Any]:
    return FakeGateway.subscriptions[subscription.stripe_subscription_id]


def webhook(event_type: str, obj: dict[str, Any], event_id: str | None = None) -> Any:
    from django.test import Client, TestCase

    body = {"id": event_id or f"evt_{event_type}_{now().timestamp()}", "type": event_type,
            "data": {"object": obj}}  # fmt: skip
    with TestCase.captureOnCommitCallbacks(execute=True):
        return Client().post(
            "/webhooks/stripe/platform", data=json.dumps(body), content_type="application/json",
            HTTP_STRIPE_SIGNATURE="fake-signature",
        )  # fmt: skip


# --- catalogue (FR-04-1) ------------------------------------------------------------------------


def test_catalogue_has_four_tiers_priced_in_six_currencies():
    services.get_plan("solo")  # heals the table if a transactional test emptied it
    assert list(Plan.objects.values_list("key", flat=True)) == [
        "solo", "team", "agency", "agency_payg", "enterprise",
    ]  # fmt: skip
    solo = PlanPrice.objects.filter(plan__key="solo", component="base_fee")
    assert set(solo.values_list("currency", flat=True)) == {
        "GBP", "USD", "EUR", "AUD", "CAD", "NZD",
    }  # fmt: skip
    monthly = solo.get(currency="GBP", interval="month").unit_amount
    assert solo.get(currency="GBP", interval="year").unit_amount == monthly * 10
    assert not PlanPrice.objects.filter(plan__key="enterprise").exists()


# --- trials and entitlements (FR-04-2, FR-04-3) -------------------------------------------------


def test_new_organisation_starts_a_trial_with_agency_features(org):
    subscription = trial(org)
    assert subscription.status == "trialing"
    assert subscription.plan.key == "solo"  # sole trader: will move to Solo
    assert (subscription.trial_ends_at - subscription.trial_started_at).days == 30
    org.refresh_from_db()
    assert org.status == "trial"
    with tenant_context(org):
        assert core_entitlements.has("recruitment")
        assert core_entitlements.limit("max_tutors") is None
        assert credits.account("sms").balance == 1000  # the trial plan's allowance
    assert "subscription.started" in event_types(org)


def test_signup_creates_the_trial(db):
    from tutortrack.core.events.dispatcher import dispatch_batch
    from tutortrack.tenancy.services import create_organisation

    with transaction.atomic():
        org = create_organisation(name="Acme Tutors", owner=UserFactory(), business_type="team")
    dispatch_batch()
    with tenant_context(org):
        assert Subscription.objects.get().plan.key == "team"


def test_organisations_without_a_subscription_are_not_limited(tenant):
    assert core_entitlements.has("sso_saml")
    assert core_entitlements.limit("max_tutors") is None


def test_inviting_a_second_tutor_on_solo_needs_team_then_works_without_reload(org):
    """AC FR-04-2."""
    subscribe(org, "solo")
    api = owner_api(org)
    first = api.post("/api/v1/tutors", {"email": "a@example.com", "first_name": "Ann"})
    assert first.status_code == 201, first.content
    second = api.post("/api/v1/tutors", {"email": "b@example.com", "first_name": "Bob"})
    assert second.status_code == 403
    problem = second.json()
    assert problem["type"].endswith("/upgrade-required")
    assert (problem["limit"], problem["allowed"], problem["required_plan"]) == (
        "max_tutors", 1, "team",
    )  # fmt: skip

    upgrade = api.post("/api/v1/subscription/change-plan", {"plan": "team", "interval": "month"})
    assert upgrade.status_code == 200, upgrade.content
    assert upgrade.json()["plan"] == "team"
    again = api.post("/api/v1/tutors", {"email": "b@example.com", "first_name": "Bob"})
    assert again.status_code == 201, again.content


def test_direct_tutor_invitations_count_too(org):
    subscribe(org, "solo")
    api = owner_api(org)
    with tenant_context(org):
        TutorProfileFactory(organisation=org, status="active")
    response = api.post("/api/v1/invitations", {"email": "t@example.com", "role": "tutor"})
    assert response.status_code == 403, response.content
    assert response.json()["required_plan"] == "team"


def test_active_student_limit(org):
    from tutortrack.people import services as people
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory

    subscribe(org, "solo")
    with tenant_context(org):
        client = ClientFactory(organisation=org)
        for _ in range(40):
            StudentFactory(organisation=org, client=client, status="active")
        with pytest.raises(UpgradeRequired):
            people.create_student(client, first_name="Max", last_name="Lee")
        waiting = people.create_student(client, first_name="Max", last_name="Lee",
                                        status="waiting")  # fmt: skip
        with pytest.raises(UpgradeRequired):
            people.change_student_status(waiting, "active")


def test_extra_branches_need_multi_branch_and_capacity(org):
    from tutortrack.core.models import FeatureFlag
    from tutortrack.tenancy.services import create_branch

    FeatureFlag.objects.update_or_create(key="multi_branch", defaults={"enabled_globally": True})
    subscribe(org, "team")
    with tenant_context(org):
        with pytest.raises(UpgradeRequired) as exc:
            create_branch(name="North", code="N")
        assert exc.value.extra == {"feature": "multi_branch", "required_plan": "agency"}
        services.set_override("multi_branch", enabled=True, reason="pilot")
        with pytest.raises(UpgradeRequired) as exc:
            create_branch(name="North", code="N")
        assert exc.value.extra["limit"] == "max_branches"
        services.set_override("max_branches", limit=3, reason="pilot")
        assert create_branch(name="North", code="N").code == "N"


def test_overrides_expire_and_can_lift_limits(org):
    subscribe(org, "solo")
    with tenant_context(org):
        services.set_override("payroll", enabled=True,
                              expires_at=now() - timedelta(days=1))  # fmt: skip
        assert not core_entitlements.has("payroll")
        services.set_override("payroll", enabled=True, expires_at=now() + timedelta(days=1))
        assert core_entitlements.has("payroll")
        services.set_override("max_tutors", unlimited=True)
        assert core_entitlements.limit("max_tutors") is None
        services.remove_override("max_tutors")
        assert core_entitlements.limit("max_tutors") == 1


def test_storage_quota(org, s3):
    from tutortrack.core.storage import services as storage

    subscribe(org, "solo")
    with tenant_context(org):
        services.set_override("storage_gb", limit=0)
        with pytest.raises(UpgradeRequired):
            storage.create_upload(filename="a.pdf", content_type="application/pdf",
                                  size_bytes=10)  # fmt: skip


def test_feature_flags_can_target_plans(org):
    from tutortrack.core import flags
    from tutortrack.core.models import FeatureFlag

    FeatureFlag.objects.create(key="beta-reports", plan_keys=["team"])
    subscribe(org, "team")
    assert flags.is_enabled("beta-reports", org.pk)


# --- trial end, checkout and plan changes (FR-04-3..5) ------------------------------------------


def test_trial_end_without_a_card_makes_the_account_read_only(org):
    trial(org)
    owner = owner_api(org)
    admin = role_api(org, "admin")
    with tenant_context(org):
        Subscription.objects.update(trial_ends_at=now())
        assert services.end_trial() == "locked"
    org.refresh_from_db()
    assert org.status == "suspended"
    assert "subscription.suspended" in event_types(org)
    assert admin.get("/api/v1/subscription").status_code == 200
    blocked = admin.post("/api/v1/tutors", {"email": "x@example.com", "first_name": "X"})
    assert blocked.status_code == 423
    pay = owner.post("/api/v1/subscription/checkout-session", {"plan": "solo"})
    assert pay.status_code == 200, pay.content
    done = owner.post("/api/v1/subscription/checkout-session/complete",
                      {"session_id": session_id(pay.json()["url"])})  # fmt: skip
    assert done.json()["status"] == "active"
    org.refresh_from_db()
    assert org.status == "active"


def test_card_added_during_trial_keeps_the_trial_then_carries_on(org):
    trial(org)
    with tenant_context(org):
        url = services.checkout("team", "year")
        subscription = services.complete_checkout(session_id(url))
        assert subscription.status == "trialing"  # the rest of the free trial is kept
        assert fake_sub(subscription)["status"] == "trialing"
        assert services.end_trial().startswith("extended:")
        Subscription.objects.update(trial_ends_at=now())
        assert services.end_trial() == "active"
        subscription.refresh_from_db()
    assert (subscription.plan.key, subscription.interval) == ("team", "year")
    org.refresh_from_db()
    assert org.status == "active"


def test_choosing_a_plan_during_the_trial_needs_no_card(org):
    trial(org)
    api = owner_api(org)
    response = api.post("/api/v1/subscription/change-plan", {"plan": "agency"})
    assert response.status_code == 200
    assert (response.json()["plan"], response.json()["effective_plan"]) == ("agency", "agency")


def test_downgrade_is_validated_then_scheduled_for_the_period_end(org):
    subscription = subscribe(org, "team")
    api = owner_api(org)
    with tenant_context(org):
        for _ in range(3):
            TutorProfileFactory(organisation=org, status="active")
    preview = api.post("/api/v1/subscription/change-plan?preview=true", {"plan": "solo"})
    assert preview.status_code == 202
    body = preview.json()
    assert body["direction"] == "downgrade"
    assert "You have 3 tutors; Solo allows 1" in body["blockers"][0]
    refused = api.post("/api/v1/subscription/change-plan", {"plan": "solo"})
    assert refused.status_code == 422
    assert refused.json()["blockers"]

    upgrade = api.post("/api/v1/subscription/change-plan?preview=true", {"plan": "agency"})
    assert upgrade.json()["effective"] == "now"
    assert Decimal(upgrade.json()["amount_due_now"]["amount"]) > 0

    with tenant_context(org):
        Subscription.objects.filter(pk=subscription.pk).update(plan=services.get_plan("agency"))
    scheduled = api.post("/api/v1/subscription/change-plan", {"plan": "team"})
    assert scheduled.json()["pending_plan"] == "team"
    assert scheduled.json()["plan"] == "agency"
    assert fake_sub(subscription)["scheduled"]

    # At the period end Stripe switches the items and tells us.
    remote = fake_sub(subscription)
    remote["items"], remote["scheduled"] = remote["scheduled"], None
    assert webhook("customer.subscription.updated",
                   {"id": subscription.stripe_subscription_id, "object": "subscription",
                    "customer": subscription.stripe_customer_id}).status_code == 200  # fmt: skip
    with tenant_context(org):
        subscription.refresh_from_db()
    assert (subscription.plan.key, subscription.pending_plan) == ("team", None)


def test_custom_plans_need_sales(org):
    trial(org)
    response = owner_api(org).post("/api/v1/subscription/checkout-session",
                                   {"plan": "enterprise"})  # fmt: skip
    assert response.status_code == 422
    assert response.json()["code"] == "contact_sales"


def test_cancel_with_survey_then_reactivate_and_resubscribe(org):
    subscription = subscribe(org, "solo")
    api = owner_api(org)
    cancelled = api.post("/api/v1/subscription/cancel", {"reason": "too_expensive",
                                                         "feedback": "Busy term"})  # fmt: skip
    assert cancelled.json()["cancel_at_period_end"] is True
    assert fake_sub(subscription)["cancel"] is True
    undone = api.post("/api/v1/subscription/reactivate")
    assert undone.json()["subscription"]["cancel_at_period_end"] is False

    api.post("/api/v1/subscription/cancel", {"reason": "closing"})
    webhook("customer.subscription.deleted",
            {"id": subscription.stripe_subscription_id, "object": "subscription",
             "customer": subscription.stripe_customer_id})  # fmt: skip
    org.refresh_from_db()
    assert org.status == "suspended"
    assert "subscription.cancelled" in event_types(org)
    again = api.post("/api/v1/subscription/reactivate")
    assert again.status_code == 200
    assert "checkout=" in again.json()["url"]


# --- webhooks and dunning state (FR-04-4, FR-04-6) ----------------------------------------------


def test_failed_renewal_marks_past_due_and_payment_restores(org):
    subscription = subscribe(org, "solo")
    invoice = {"id": "in_1", "object": "invoice", "customer": subscription.stripe_customer_id,
               "subscription": subscription.stripe_subscription_id,
               "billing_reason": "subscription_cycle"}  # fmt: skip
    assert webhook("invoice.payment_failed", invoice, "evt_failed").status_code == 200
    webhook("invoice.payment_failed", invoice, "evt_failed")  # duplicate delivery: ignored
    org.refresh_from_db()
    assert org.status == "past_due"
    assert event_types(org).count("subscription.past_due") == 1

    webhook("invoice.paid", invoice, "evt_paid")
    org.refresh_from_db()
    assert org.status == "active"
    with tenant_context(org):
        assert Subscription.objects.get().past_due_since is None
        grants = UsageCreditLedger.objects.filter(reason="grant", ref="in_1")
        assert grants.count() == 1  # a new period: the allowance is renewed


def test_suspended_for_non_payment_restores_on_payment(org):
    subscription = subscribe(org, "solo")
    with tenant_context(org):
        services.mark_past_due("in_2")
        assert services.suspend_for_non_payment()
    org.refresh_from_db()
    assert org.status == "suspended"
    portal_user = role_api(org, "client")
    assert portal_user.get("/api/v1/portal/me").status_code == 403  # portals paused
    webhook("invoice.paid", {"id": "in_2", "object": "invoice",
                             "customer": subscription.stripe_customer_id,
                             "subscription": subscription.stripe_subscription_id})  # fmt: skip
    org.refresh_from_db()
    assert org.status == "active"


def test_unknown_customers_and_bad_signatures_are_ignored(org):
    assert webhook("invoice.paid", {"id": "in_x", "customer": "cus_nobody"}).status_code == 200
    from django.test import Client

    response = Client().post("/webhooks/stripe/platform", data="{}",
                             content_type="application/json",
                             HTTP_STRIPE_SIGNATURE="forged")  # fmt: skip
    assert response.status_code == 400


# --- seats and revenue share (FR-04-4, T05) -----------------------------------------------------


def test_seat_quantities_follow_active_tutors(org):
    Plan.objects.filter(key="team").update(seat_mode="active")
    subscription = subscribe(org, "team")
    with tenant_context(org):
        for _ in range(5):
            TutorProfileFactory(organisation=org, status="active")
        assert services.sync_seats() == 5
    price = f"tt:team:{subscription.currency}:month:active_tutor"
    assert fake_sub(subscription)["items"][price] == 3  # 2 included


def test_delivered_seat_mode_counts_tutors_with_completed_lessons(org):
    from tutortrack.catalogue.tests.factories import ServiceFactory
    from tutortrack.jobs import services as jobs
    from tutortrack.people.tests.factories import ClientFactory, StudentFactory
    from tutortrack.scheduling import services as scheduling
    from tutortrack.scheduling.models import Lesson
    from tutortrack.subscriptions import selectors

    subscription = subscribe(org, "team")
    with tenant_context(org):
        busy, idle = (TutorProfileFactory(organisation=org, status="active") for _ in range(2))
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        service = ServiceFactory(organisation=org)
        job = jobs.create_job(client=client, service=service, students=[{"student": student}],
                              tutors=[{"tutor": busy}], status="active")  # fmt: skip
        start = now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        lesson = scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=service, job=job,
            attendees=[{"student": student}], tutors=[{"tutor": busy}],
            timezone="Europe/London", override_conflicts=True,
        ).lesson  # fmt: skip
        Lesson.objects.filter(pk=lesson.pk).update(status="completed")
        Subscription.objects.update(current_period_start=start - timedelta(days=1))
        subscription.refresh_from_db()
        assert selectors.billable_tutors(subscription) == 1
        assert idle.pk != busy.pk


def test_revenue_share_is_reported_once_a_day(org, monkeypatch):
    subscription = subscribe(org, "agency_payg")
    monkeypatch.setattr(
        "tutortrack.payments.selectors.processed_totals",
        lambda start, end: {"GBP": Decimal("1234.56")},
    )
    day = (now() - timedelta(days=1)).date()
    with tenant_context(org):
        report = services.report_revenue(day)
        services.report_revenue(day)
    assert report is not None
    assert report.quantity == 123456
    usage = [u for u in FakeGateway.usage if u["customer"] == subscription.stripe_customer_id]
    assert len(usage) == 1


# --- credits (FR-04-8) --------------------------------------------------------------------------


@pytest.fixture
def sms_meter():
    channels.set_credit_meter(SmsCreditMeter())
    yield
    channels.set_credit_meter(channels._Unlimited())


def test_sms_credits_hard_stop_and_low_warning(org, sms_meter):
    subscribe(org, "solo")
    with tenant_context(org):
        meter = channels.credit_meter()
        assert credits.account("sms").balance == 50
        assert meter.consume(29, country="GB")
        assert meter.consume(1, country="FR")  # 2 credits abroad
        assert credits.account("sms").balance == 19
        assert "credits.low" in event_types(org)
        assert not meter.consume(20, country="GB")  # hard stop
        credits.update_settings("sms", allow_overage=True)
        assert meter.consume(20, country="GB")
        acct = credits.account("sms")
        assert (acct.included_balance, acct.purchased_balance) == (0, -1)
        # Next period: the overage is charged and the allowance renewed.
        credits.reset_allowances(ref="period-2")
        acct.refresh_from_db()
        assert (acct.included_balance, acct.purchased_balance) == (50, 0)


def test_top_up_charges_the_card_and_auto_top_up_refills(org):
    subscribe(org, "solo")
    api = owner_api(org)
    response = api.post("/api/v1/subscription/credits/sms/top-up", {"credits": 500})
    assert response.status_code == 200, response.content
    assert (response.json()["status"], response.json()["account"]["balance"]) == ("paid", 550)
    assert api.post("/api/v1/subscription/credits/sms/top-up",
                    {"credits": 7}).status_code == 422  # fmt: skip

    api.patch(
        "/api/v1/subscription/credits/sms",
        {"auto_top_up": True, "top_up_pack": 500, "low_threshold": 100},
        format="json",
    )
    from django.test import TestCase

    with tenant_context(org), TestCase.captureOnCommitCallbacks(execute=True):
        assert credits.consume("sms", 460, ref="bulk")
    with tenant_context(org):
        assert credits.account("sms").balance == 590  # 90 left + 500 bought automatically
        assert CreditAccount.objects.get(credit_type="sms").auto_top_up


def test_top_up_without_a_card_goes_to_checkout(org):
    trial(org)
    response = owner_api(org).post("/api/v1/subscription/credits/sms/top-up", {"credits": 500})
    assert response.json()["status"] == "redirect"
    url = response.json()["url"]
    owner_api(org).post("/api/v1/subscription/checkout-session/complete",
                        {"session_id": session_id(url)})  # fmt: skip
    with tenant_context(org):
        assert credits.account("sms").purchased_balance == 500


def test_failed_top_up_is_reported(org, monkeypatch):
    subscribe(org, "solo")
    monkeypatch.setattr(FakeGateway, "fail_charges", True)
    response = owner_api(org).post("/api/v1/subscription/credits/sms/top-up", {"credits": 500})
    assert response.status_code == 422
    assert "declined" in response.json()["detail"]


# --- API, permissions and isolation -------------------------------------------------------------


def test_billing_page_data(org):
    subscribe(org, "team")
    api = owner_api(org)
    sub = api.get("/api/v1/subscription").json()
    assert (sub["plan"], sub["status"], sub["has_payment_method"]) == ("team", "active", True)
    assert sub["card"]["last4"] == "4242"
    assert sub["can_manage"]
    plans = api.get("/api/v1/subscription/plans").json()
    team = next(p for p in plans if p["key"] == "team")
    assert team["currency"] == "GBP"
    assert team["limits"]["max_tutors"] == 15
    assert {p["component"] for p in team["prices"]} == {"base_fee", "active_tutor"}
    usage = api.get("/api/v1/subscription/usage").json()
    assert {u["key"] for u in usage["limits"]} >= {"max_tutors", "storage_gb"}
    assert usage["included_tutors"] == 2
    assert usage["next_invoice"]["currency"] == "GBP"
    assert {c["credit_type"] for c in usage["credits"]} == {"sms", "ai"}
    assert api.get("/api/v1/subscription/invoices").status_code == 200
    assert api.post("/api/v1/subscription/portal-session").json()["url"]


def test_entitlements_endpoint(org, api):
    open_ = api.get("/api/v1/entitlements").json()
    assert open_["plan"] is None
    assert open_["features"]["payroll"] is True
    subscribe(org, "solo")
    data = api.get("/api/v1/entitlements").json()
    assert (data["plan"], data["features"]["payroll"], data["limits"]["max_tutors"]) == (
        "solo", False, 1,
    )  # fmt: skip
    assert data["required_plans"]["payroll"] == "team"
    assert data["required_plans"]["multi_branch"] == "agency"


@pytest.mark.parametrize(
    ("role", "can_view", "can_manage"),
    [("owner", True, True), ("admin", True, False), ("finance", True, False),
     ("coordinator", False, False), ("branch_manager", False, False)],
)  # fmt: skip
def test_permissions(org, role, can_view, can_manage):
    trial(org)
    client = role_api(org, role)
    assert (client.get("/api/v1/subscription").status_code == 200) is can_view
    change = client.post("/api/v1/subscription/change-plan", {"plan": "team"})
    assert (change.status_code == 200) is can_manage


def test_each_organisation_sees_only_its_own_subscription(org, other_org):
    subscribe(org, "team")
    trial(other_org)
    with tenant_context(other_org):
        credits.consume("sms", 5, ref="theirs")
    mine = owner_api(org)
    assert mine.get("/api/v1/subscription").json()["plan"] == "team"
    ledger = mine.get("/api/v1/subscription/credits/sms").json()["ledger"]
    assert all(e["delta"] != -5 for e in ledger)
    with tenant_context(org):
        assert Subscription.objects.count() == 1


def test_resolver_cache_is_invalidated_on_change(org):
    subscribe(org, "solo")
    with tenant_context(org):
        assert entitlements.snapshot()["plan"] == "solo"  # cached
        services.change_plan("team", "month")
        assert entitlements.snapshot()["plan"] == "team"
