"""E02-T09: close and suspend flows (FR-02-3, FR-02-8)."""

from __future__ import annotations

import pytest
from django.test import override_settings

from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory
from tutortrack.tenancy import lifecycle
from tutortrack.tenancy.models import Organisation

pytestmark = pytest.mark.django_db


def member(org, role):
    return MembershipFactory(organisation=org, role=role).user


def close(api, org, **overrides):
    payload = {"password": TEST_PASSWORD, "confirm_slug": org.slug, "reason": "Retiring"}
    return api.post("/api/v1/organisation/close", {**payload, **overrides}, format="json")


# --- close ----------------------------------------------------------------------------------------


def test_owner_closes_the_account(org):
    api = client_for(org, member(org, Membership.Role.OWNER))
    response = close(api, org)
    assert response.status_code == 200, response.json()
    org.refresh_from_db()
    assert org.status == Organisation.Status.CANCELLED
    assert org.closed_at is not None
    event = OutboxEvent.objects.get(organisation_id=org.pk, event_type="organisation.closed")
    assert event.payload["data"] == {"reason": "Retiring", "export_requested": True}
    with tenant_context(org):
        assert AuditEntry.objects.filter(action="close").exists()
    # The account is now gone for members.
    assert api.get("/api/v1/organisation").status_code == 410


def test_close_requires_owner_password_and_confirmation(org):
    admin_api = client_for(org, member(org, Membership.Role.ADMIN))
    assert close(admin_api, org).status_code == 403  # owner only

    owner_api = client_for(org, member(org, Membership.Role.OWNER))
    wrong_password = close(owner_api, org, password="nope")
    assert wrong_password.status_code == 403
    assert wrong_password.json()["type"].endswith("reauthentication-failed")
    wrong_slug = close(owner_api, org, confirm_slug="something-else")
    assert wrong_slug.status_code == 422
    assert "confirm_slug" in wrong_slug.json()["errors"]
    org.refresh_from_db()
    assert org.status == Organisation.Status.ACTIVE


def test_closed_orgs_are_410_but_sign_in_and_switcher_still_work(org):
    owner = member(org, Membership.Role.OWNER)
    Organisation.objects.filter(pk=org.pk).update(
        status=Organisation.Status.CANCELLED, closed_at=now()
    )
    api = client_for(org, owner)
    response = api.get("/api/v1/branches")
    assert response.status_code == 410
    assert response.json()["type"].endswith("organisation-closed")
    assert api.get("/api/v1/me/organisations").status_code == 200


# --- suspend --------------------------------------------------------------------------------------


@pytest.fixture
def suspended(org):
    return lifecycle.suspend_organisation(org, reason="Unpaid invoice")


def test_suspension_is_recorded_and_announced(org, suspended):
    assert suspended.status == Organisation.Status.SUSPENDED
    assert suspended.suspension_reason == "Unpaid invoice"
    assert OutboxEvent.objects.filter(
        organisation_id=org.pk, event_type="organisation.suspended"
    ).exists()
    assert not suspended.is_operational  # background jobs stop (fan_out_per_org)


def test_suspended_org_is_read_only_for_owners_and_admins(org, suspended):
    api = client_for(org, member(org, Membership.Role.OWNER))
    assert api.get("/api/v1/organisation").status_code == 200
    blocked = api.patch("/api/v1/organisation", {"name": "New"}, format="json")
    assert blocked.status_code == 423
    assert blocked.json()["type"].endswith("organisation-read-only")


@override_settings(SUSPENDED_ORG_WRITE_ALLOWLIST=["/api/v1/settings/billing"])
def test_billing_writes_stay_open_while_suspended(org, suspended):
    api = client_for(org, member(org, Membership.Role.ADMIN))
    response = api.patch(
        "/api/v1/settings/billing",
        {"values": {"billing.invoicing_style": "packages"}},
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.parametrize("role", [Membership.Role.TUTOR, Membership.Role.CLIENT])
def test_other_members_and_portal_users_are_locked_out(org, suspended, role):
    response = client_for(org, member(org, role)).get("/api/v1/branches")
    assert response.status_code == 403
    assert response.json()["type"].endswith("organisation-suspended")


def test_platform_staff_keep_full_access(org, suspended, superuser):
    api = client_for(org, superuser)
    assert api.patch("/api/v1/organisation", {"name": "Fixed"}, format="json").status_code == 200


def test_reactivation(org, suspended):
    lifecycle.reactivate_organisation(org)
    org.refresh_from_db()
    assert (org.status, org.suspension_reason, org.suspended_at) == ("active", "", None)
    api = client_for(org, member(org, Membership.Role.TUTOR))
    assert api.get("/api/v1/branches").status_code == 403  # tutors lack the permission...
    assert api.get("/api/v1/branches").json()["type"].endswith("permission-denied")  # ...only
    assert OutboxEvent.objects.filter(event_type="organisation.reactivated").exists()


def test_lifecycle_guards(org):
    with pytest.raises(BusinessRuleViolation):
        lifecycle.suspend_organisation(org, reason=" ")
    with pytest.raises(BusinessRuleViolation):
        lifecycle.reactivate_organisation(org)  # not suspended
    Organisation.objects.filter(pk=org.pk).update(status=Organisation.Status.CANCELLED)
    org.refresh_from_db()
    with pytest.raises(BusinessRuleViolation):
        lifecycle.suspend_organisation(org, reason="x")


def test_admin_actions_suspend_and_reactivate(org, superuser):
    from django.test import Client

    client = Client()
    client.force_login(superuser)
    url = "/django-admin/tenancy/organisation/"
    client.post(url, {"action": "suspend", "_selected_action": [str(org.pk)]})
    org.refresh_from_db()
    assert org.status == Organisation.Status.SUSPENDED
    client.post(url, {"action": "reactivate", "_selected_action": [str(org.pk)]})
    org.refresh_from_db()
    assert org.status == Organisation.Status.ACTIVE
