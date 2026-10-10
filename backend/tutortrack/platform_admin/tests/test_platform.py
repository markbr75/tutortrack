"""E30 part 1: platform console access, tenants and actions, flags, operations, notices,
support access and the per-tenant dump."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APIClient

from tutortrack.core import flags
from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, FeatureFlag, OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.models import SupportSession, UserSession
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.subscriptions import services as subscriptions
from tutortrack.subscriptions.models import EntitlementOverride, Subscription
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "platform"])


def platform_client(user: Any, *, mfa: bool = True) -> APIClient:
    client = APIClient(HTTP_HOST=settings.TENANT_BASE_DOMAIN)
    client.force_login(user)
    if mfa:
        UserSession.objects.filter(user=user).update(mfa_verified=True)
    return client


@pytest.fixture
def staff() -> Any:
    return UserFactory(is_platform_staff=True, first_name="Pat", last_name="Support")


@pytest.fixture
def console(staff: Any) -> APIClient:
    return platform_client(staff)


@pytest.fixture
def owner(org: Any) -> Any:
    with tenant_context(org):
        return MembershipFactory(organisation=org, role="owner")


# --- access (T01) -------------------------------------------------------------------------------


def test_only_platform_staff_with_2fa_from_allowed_networks(org, staff):
    assert platform_client(UserFactory()).get("/api/v1/platform/tenants").status_code == 403
    no_mfa = platform_client(staff, mfa=False)
    assert no_mfa.get("/api/v1/platform/tenants").status_code == 403
    me = no_mfa.get("/api/v1/platform/me").json()
    assert (me["is_platform_staff"], me["mfa_verified"]) == (True, False)
    assert platform_client(staff).get("/api/v1/platform/tenants").status_code == 200


def test_network_allowlist(staff, settings):
    settings.PLATFORM_IP_ALLOWLIST = ["10.0.0.0/8"]
    client = platform_client(staff)
    assert client.get("/api/v1/platform/tenants", REMOTE_ADDR="192.168.1.5").status_code == 403
    assert client.get("/api/v1/platform/tenants", REMOTE_ADDR="10.1.2.3").status_code == 200


# --- tenants (T01/T02) --------------------------------------------------------------------------


def test_tenant_list_spans_organisations(org, other_org, console):
    subscriptions.start_trial(org)
    subscriptions.start_trial(other_org)
    with tenant_context(other_org):
        Subscription.objects.update(plan=subscriptions.get_plan("team"), status="active", seats=5)
    rows = console.get("/api/v1/platform/tenants").json()["results"]
    assert {r["slug"] for r in rows} == {"brightminds", "othertutors"}
    team = next(r for r in rows if r["slug"] == "othertutors")
    assert (team["plan"], team["subscription_status"]) == ("team", "active")
    assert team["mrr"] == {"amount": "57.00", "currency": "GBP"}  # £39 + 3 tutors x £6
    only = console.get("/api/v1/platform/tenants", {"plan": "team"}).json()["results"]
    assert [r["slug"] for r in only] == ["othertutors"]
    found = console.get("/api/v1/platform/tenants", {"search": "bright"}).json()["results"]
    assert [r["slug"] for r in found] == ["brightminds"]


def test_tenant_detail(org, owner, console):
    subscriptions.start_trial(org)
    detail = console.get(f"/api/v1/platform/tenants/{org.pk}").json()
    assert detail["organisation"]["slug"] == "brightminds"
    assert detail["subscription"]["status"] == "trialing"
    assert [m["role"] for m in detail["members"]] == ["owner"]
    assert "max_tutors" in detail["usage"]


def test_tenant_actions_are_applied_and_audited_in_the_tenant(org, owner, staff, console):
    subscriptions.start_trial(org)
    base = f"/api/v1/platform/tenants/{org.pk}"
    with tenant_context(org):
        ends = Subscription.objects.get().trial_ends_at
    assert console.post(f"{base}/extend-trial", {"days": 7, "reason": "Demo"}).status_code == 200
    with tenant_context(org):
        assert Subscription.objects.get().trial_ends_at == ends + timedelta(days=7)

    granted = console.put(f"{base}/overrides", {"key": "payroll", "enabled": True,
                                                "reason": "Pilot"}, format="json")  # fmt: skip
    assert granted.json()["overrides"][0]["key"] == "payroll"
    assert console.delete(f"{base}/overrides/payroll").json()["overrides"] == []

    assert console.post(f"{base}/suspend", {"reason": "Abuse report"}).status_code == 200
    org.refresh_from_db()
    assert org.status == "suspended"
    console.post(f"{base}/unsuspend")
    org.refresh_from_db()
    assert org.status == "trial"

    changed = console.post(f"{base}/change-plan", {"plan": "enterprise", "note": "Contract #42",
                                                   "activate": True})  # fmt: skip
    assert changed.json()["subscription"]["plan"] == "enterprise"
    assert changed.json()["subscription"]["status"] == "active"

    assert console.post(f"{base}/resend-verification").json()["count"] == 1
    assert console.post(f"{base}/export", {"reason": "Owner asked"}).status_code == 202
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="organisation.export_requested").exists()
        actions = set(AuditEntry.objects.filter(actor_id=staff.pk).values_list("action", flat=True))
    assert {"extend_trial", "suspend", "platform_set_plan", "export_requested"} <= actions


def test_scheduling_deletion_needs_the_subdomain(org, console):
    base = f"/api/v1/platform/tenants/{org.pk}"
    wrong = console.post(f"{base}/schedule-deletion", {"reason": "Owner's written request",
                                                       "confirm_slug": "nope"})  # fmt: skip
    assert wrong.status_code == 422
    console.post(f"{base}/schedule-deletion", {"reason": "Owner's written request",
                                               "confirm_slug": "brightminds"})  # fmt: skip
    org.refresh_from_db()
    assert org.status == "cancelled"


def test_overrides_need_a_reason(org, console):
    subscriptions.start_trial(org)
    response = console.put(
        f"/api/v1/platform/tenants/{org.pk}/overrides",
        {"key": "payroll", "enabled": True, "reason": ""},
        format="json",
    )
    assert response.status_code == 400
    with tenant_context(org):
        assert not EntitlementOverride.objects.exists()


# --- feature flags (T03) ------------------------------------------------------------------------


def test_flag_targeting_by_plan_rollout_and_organisation(org, other_org, console):
    created = console.post(
        "/api/v1/platform/flags", {"key": "new-calendar", "plan_keys": ["team"]}, format="json"
    )
    assert created.status_code == 201
    assert not flags.is_enabled("new-calendar", org.pk)
    console.put("/api/v1/platform/flags/new-calendar/overrides",
                {"organisation": str(org.pk), "enabled": True, "reason": "Beta"},
                format="json")  # fmt: skip
    assert flags.is_enabled("new-calendar", org.pk)
    assert not flags.is_enabled("new-calendar", other_org.pk)
    console.patch("/api/v1/platform/flags/new-calendar", {"rollout_percent": 100}, format="json")
    assert flags.is_enabled("new-calendar", other_org.pk)
    listed = console.get("/api/v1/platform/flags").json()
    assert listed[0]["overrides"][0]["organisation_name"] == "Bright Minds"
    console.delete(f"/api/v1/platform/flags/new-calendar/overrides/{org.pk}")
    assert FeatureFlag.objects.get(key="new-calendar").overrides.count() == 0


def test_rollout_is_stable_per_organisation():
    import uuid

    ids = [uuid.uuid4() for _ in range(400)]
    at_20 = {i for i in ids if flags.in_rollout("x", i, 20)}
    at_50 = {i for i in ids if flags.in_rollout("x", i, 50)}
    assert at_20 <= at_50
    assert 40 < len(at_20) < 120


# --- operations (T04) ---------------------------------------------------------------------------


def test_dead_letters_are_listed_and_replayed(org, console):
    event = OutboxEvent.objects.create(
        organisation=org, event_type="lesson.completed", payload={}, attempts=8,
        last_error="boom", dead_lettered_at=now(),
    )  # fmt: skip
    ops = console.get("/api/v1/platform/operations").json()
    assert ops["dead_letters"] == 1
    assert ops["dead_letters_by_type"] == [{"event_type": "lesson.completed", "count": 1}]
    listed = console.get("/api/v1/platform/dead-letters").json()["results"]
    assert listed[0]["organisation_name"] == "Bright Minds"
    replayed = console.post("/api/v1/platform/dead-letters/replay", {"ids": [str(event.pk)]},
                            format="json")  # fmt: skip
    assert replayed.json()["count"] == 1
    event.refresh_from_db()
    assert (event.dead_lettered_at, event.attempts) == (None, 0)


def test_metrics_are_written_in_embedded_metric_format(capsys):
    from tutortrack.platform_admin.tasks import emit_metrics

    emit_metrics(environment="test")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TutorTrack"
    assert line["Environment"] == "test"
    assert "OutboxLagSeconds" in line


# --- notices (T06) ------------------------------------------------------------------------------


def test_outage_banner_reaches_every_app(org, console):
    created = console.post("/api/v1/platform/notices",
                           {"message": "Payments are delayed", "severity": "warning",
                            "starts_at": now().isoformat()}, format="json")  # fmt: skip
    assert created.status_code == 201
    status = client_for(org).get("/api/v1/status").json()
    assert [n["message"] for n in status["notices"]] == ["Payments are delayed"]
    console.patch(f"/api/v1/platform/notices/{created.json()['id']}",
                  {"ends_at": now().isoformat()}, format="json")  # fmt: skip
    assert client_for(org).get("/api/v1/status").json()["notices"] == []


# --- plans (FR-30-1) ----------------------------------------------------------------------------


def test_plans_can_be_edited(console):
    subscriptions.get_plan("solo")
    plans = console.get("/api/v1/platform/plans").json()
    assert {p["key"] for p in plans} >= {"solo", "team"}
    updated = console.patch("/api/v1/platform/plans/solo",
                            {"trial_days": 14, "entitlements": {"max_tutors": 2}},
                            format="json")  # fmt: skip
    assert (updated.json()["trial_days"], updated.json()["entitlements"]["max_tutors"]) == (14, 2)


# --- support access (T05) -----------------------------------------------------------------------


def start(console: APIClient, org: Any, membership: Any, **extra: Any) -> Any:
    return console.post(
        f"/api/v1/platform/tenants/{org.pk}/support-sessions",
        {"membership_id": str(membership.pk), "reason": "Ticket 123: invoice totals",
         "ticket": "123", **extra}, format="json",
    )  # fmt: skip


def test_support_session_is_read_only_and_visible_to_the_owner(org, owner, staff, console):
    response = start(console, org, owner)
    assert response.status_code == 200, response.content
    url = response.json()["url"]
    assert url.startswith(org.base_url + "/api/v1/support/enter?token=")
    browser = client_for(org)
    path = url.removeprefix(org.base_url)
    entered = browser.get(path)
    assert entered.status_code == 302
    me = browser.get("/api/v1/me").json()
    assert me["impersonator"]["email"] == staff.email
    assert me["user"]["email"] == owner.user.email
    blocked = browser.post("/api/v1/tutors", {"email": "x@example.com", "first_name": "X"})
    assert blocked.status_code == 403
    assert client_for(org).get(path).status_code == 404  # single use

    owner_view = client_for(org, owner.user).get("/api/v1/support-access").json()
    assert owner_view["sessions"][0]["reason"] == "Ticket 123: invoice totals"
    browser.post("/api/v1/impersonate/stop")
    with tenant_context(org):
        assert SupportSession.objects.get().ended_at is not None
        assert AuditEntry.objects.filter(action="support_access").exists()


def test_organisations_can_require_a_grant_and_allow_writes(org, owner, console):
    with tenant_context(org):
        settings_service.update_settings(
            "security", {"security.support_access_requires_grant": True}
        )
    assert start(console, org, owner).status_code == 403
    owner_api = client_for(org, owner.user)
    grant = owner_api.post("/api/v1/support-access/grants", {"days": 3, "allow_write": True})
    assert grant.status_code == 201
    assert start(console, org, owner, write=True).status_code == 200
    owner_api.post(f"/api/v1/support-access/grants/{grant.json()['id']}/revoke")
    assert start(console, org, owner).status_code == 403


def test_support_access_needs_a_reason(org, owner, console):
    response = console.post(
        f"/api/v1/platform/tenants/{org.pk}/support-sessions",
        {"membership_id": str(owner.pk), "reason": "x"},
        format="json",
    )
    assert response.status_code == 422


def test_admins_see_support_access_but_only_owners_grant(org):
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin")
    api = client_for(org, admin.user)
    assert api.get("/api/v1/support-access").status_code == 200
    assert api.post("/api/v1/support-access/grants", {"days": 1}).status_code == 403


# --- per-tenant dump (T07) ----------------------------------------------------------------------


def test_tenant_dump_contains_only_that_organisation(org, other_org, owner, tmp_path):
    with tenant_context(other_org):
        MembershipFactory(organisation=other_org, role="owner")
    out = tmp_path / "brightminds.json"
    call_command("tenant_dump", "brightminds", output=str(out))
    rows = json.loads(out.read_text())
    orgs = {r["fields"].get("organisation") for r in rows if "organisation" in r["fields"]}
    assert orgs == {str(org.pk)}
    assert any(r["model"] == "identity.membership" for r in rows)
