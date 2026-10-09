"""E03-T03: memberships, invitations (staff, bulk), org switcher integration."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.core import mail
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.models import Invitation, Membership
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db
HOST = "brightminds.tutortrack.test"


@pytest.fixture
def owner(org):
    return MembershipFactory(organisation=org, role="owner").user


@pytest.fixture
def api(org, owner):
    return client_for(org, owner)


def invite(api, email="new@example.com", role="tutor", capture=None, **extra):
    def post():
        return api.post(
            "/api/v1/invitations", {"email": email, "role": role, **extra}, format="json"
        )

    if capture is None:
        return post()
    with capture(execute=True):
        return post()


def token_from_mail() -> str:
    return re.search(r"accept-invite\?token=(\S+)", mail.outbox[-1].body).group(1)


def test_invite_emails_a_link_on_the_organisation_address(api, django_capture_on_commit_callbacks):
    response = invite(api, capture=django_capture_on_commit_callbacks, title="Maths tutor")
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "pending"
    assert mail.outbox[0].to == ["new@example.com"]
    assert f"https://{HOST}/accept-invite?token=" in mail.outbox[0].body
    assert OutboxEvent.objects.filter(event_type="user.invited").exists()


def test_new_person_accepts_and_is_signed_in(api, org, django_capture_on_commit_callbacks):
    invite(api, capture=django_capture_on_commit_callbacks)
    token = token_from_mail()
    visitor = APIClient(HTTP_HOST=HOST)

    lookup = visitor.get("/api/v1/invitations/lookup", {"token": token}).json()
    assert lookup["email"] == "new@example.com"
    assert lookup["organisation_name"] == org.name
    assert lookup["account_exists"] is False

    accepted = visitor.post(
        "/api/v1/invitations/accept",
        {"token": token, "first_name": "Nia", "password": "violet-harbour-lantern-42"},
        format="json",
    )
    assert accepted.status_code == 201, accepted.json()
    assert accepted.json()["role"] == "tutor"
    me = visitor.get("/api/v1/me").json()
    assert me["membership"]["role"] == "tutor"
    assert me["user"]["email_verified"] is True
    assert OutboxEvent.objects.filter(event_type="user.joined").exists()
    # Used up.
    again = APIClient(HTTP_HOST=HOST).get("/api/v1/invitations/lookup", {"token": token})
    assert again.status_code == 404


def test_existing_user_accepts_while_signed_in(
    api, org, other_org, django_capture_on_commit_callbacks
):
    person = MembershipFactory(organisation=other_org, user__email="new@example.com").user
    invite(api, capture=django_capture_on_commit_callbacks, role="coordinator")
    token = token_from_mail()

    wrong = client_for(org, UserFactory())
    assert (
        wrong.post("/api/v1/invitations/accept", {"token": token}, format="json").status_code == 404
    )

    right = client_for(org, person)
    assert (
        right.post("/api/v1/invitations/accept", {"token": token}, format="json").status_code == 201
    )
    # Now a member of both organisations (org switcher).
    slugs = [o["slug"] for o in right.get("/api/v1/me/organisations").json()]
    assert set(slugs) == {org.slug, other_org.slug}


def test_existing_account_must_sign_in_rather_than_create(api, django_capture_on_commit_callbacks):
    UserFactory(email="new@example.com")
    invite(api, capture=django_capture_on_commit_callbacks)
    response = APIClient(HTTP_HOST=HOST).post(
        "/api/v1/invitations/accept",
        {"token": token_from_mail(), "first_name": "X", "password": "violet-harbour-lantern-42"},
        format="json",
    )
    assert response.status_code == 404


def test_expired_and_revoked_invitations(api, org, django_capture_on_commit_callbacks):
    invite(api, capture=django_capture_on_commit_callbacks)
    token = token_from_mail()
    with tenant_context(org):
        Invitation.objects.update(expires_at=now() - timedelta(seconds=1))
    assert (
        APIClient(HTTP_HOST=HOST).get("/api/v1/invitations/lookup", {"token": token}).status_code
        == 404
    )

    invitation_id = invite(api, email="other@example.com").json()["id"]
    assert api.delete(f"/api/v1/invitations/{invitation_id}").status_code == 204
    assert api.get(f"/api/v1/invitations/{invitation_id}").json()["status"] == "revoked"


def test_resend_rotates_the_token(api, django_capture_on_commit_callbacks):
    invitation_id = invite(api, capture=django_capture_on_commit_callbacks).json()["id"]
    old = token_from_mail()
    with django_capture_on_commit_callbacks(execute=True):
        resent = api.post(f"/api/v1/invitations/{invitation_id}/resend")
    assert resent.json()["sent_count"] == 2
    new = token_from_mail()
    visitor = APIClient(HTTP_HOST=HOST)
    assert visitor.get("/api/v1/invitations/lookup", {"token": old}).status_code == 404
    assert visitor.get("/api/v1/invitations/lookup", {"token": new}).status_code == 200


def test_invitation_rules(api, org):
    MembershipFactory(organisation=org, user__email="member@example.com")
    assert invite(api, email="member@example.com").status_code == 422
    assert invite(api).status_code == 201
    assert invite(api).status_code == 422  # already pending
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    assert invite(admin, email="boss@example.com", role="owner").status_code == 422
    assert invite(api, email="boss@example.com", role="owner").status_code == 201


def test_bulk_invite(api, org):
    MembershipFactory(organisation=org, user__email="member@example.com")
    response = api.post(
        "/api/v1/invitations/bulk",
        {"emails": ["a@example.com", "B@example.com", "a@example.com", "member@example.com"],
         "role": "tutor"},
        format="json",
    )  # fmt: skip
    assert response.json()["invited"] == ["a@example.com", "b@example.com"]
    assert set(response.json()["skipped"]) == {"member@example.com"}


def test_only_people_with_team_permissions_can_invite(org):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert invite(tutor).status_code == 403
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert coordinator.get("/api/v1/memberships").status_code == 200
    assert invite(coordinator).status_code == 403


# --- memberships ----------------------------------------------------------------------------------


def test_change_role_and_branch_scope(api, org):
    from tutortrack.tenancy.tests.factories import BranchFactory

    north = BranchFactory(organisation=org, code="N")
    membership = MembershipFactory(organisation=org, role="tutor")
    response = api.patch(
        f"/api/v1/memberships/{membership.pk}",
        {"role": "coordinator", "branch_scope": "selected", "branches": [str(north.pk)]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["role"] == "coordinator"
    assert response.json()["branches"] == [str(north.pk)]
    event = OutboxEvent.objects.get(event_type="membership.role_changed")
    assert event.payload["data"]["old_role"] == "tutor"


def test_last_owner_and_self_protection(api, org, owner):
    with tenant_context(org):
        me = Membership.objects.get(user=owner)
    assert (
        api.patch(f"/api/v1/memberships/{me.pk}", {"role": "admin"}, format="json").status_code
        == 422
    )
    assert api.delete(f"/api/v1/memberships/{me.pk}").status_code == 422
    second = MembershipFactory(organisation=org, role="owner")
    admin_api = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    # Admins can't touch owners.
    assert (
        admin_api.patch(
            f"/api/v1/memberships/{second.pk}", {"role": "tutor"}, format="json"
        ).status_code
        == 422
    )
    assert (
        api.patch(f"/api/v1/memberships/{second.pk}", {"role": "admin"}, format="json").status_code
        == 200
    )


def test_removed_members_lose_access(api, org):
    membership = MembershipFactory(organisation=org, role="coordinator")
    their_api = client_for(org, membership.user)
    assert their_api.get("/api/v1/branches").status_code == 200
    assert api.delete(f"/api/v1/memberships/{membership.pk}").status_code == 204
    assert their_api.get("/api/v1/branches").status_code == 403
    assert OutboxEvent.objects.filter(event_type="membership.deactivated").exists()
    ids = {m["id"] for m in api.get("/api/v1/memberships").json()["results"]}
    assert str(membership.pk) not in ids


def test_onboarding_tutor_step_sends_invitations(org, django_capture_on_commit_callbacks):
    from tutortrack.core.events.dispatcher import dispatch_batch
    from tutortrack.tenancy import onboarding, services

    services.update_organisation(org, business_type="team")
    with tenant_context(org):
        onboarding.submit_step("tutors", {"emails": ["t1@example.com", "t2@example.com"]})
    dispatch_batch()
    with tenant_context(org):
        assert set(Invitation.objects.values_list("email", flat=True)) == {
            "t1@example.com",
            "t2@example.com",
        }


class TestMembershipIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/memberships"

    def make_object(self, organisation):
        return MembershipFactory(organisation=organisation)


class TestInvitationIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/invitations"

    def make_object(self, organisation):
        with tenant_context(organisation):
            from tutortrack.identity.services import invite as do_invite

            return do_invite(f"x-{organisation.slug}@example.com", role="tutor")


def test_password_for_invited_user_works(api, django_capture_on_commit_callbacks):
    invite(api, capture=django_capture_on_commit_callbacks)
    APIClient(HTTP_HOST=HOST).post(
        "/api/v1/invitations/accept",
        {"token": token_from_mail(), "first_name": "Nia", "password": "violet-harbour-lantern-42"},
        format="json",
    )
    response = APIClient(HTTP_HOST=HOST).post(
        "/api/v1/auth/login",
        {"email": "new@example.com", "password": "violet-harbour-lantern-42"},
        format="json",
    )
    assert response.status_code == 200
    assert TEST_PASSWORD != "violet-harbour-lantern-42"
