"""E03-T10: impersonation with audit, read-only by default."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def tutor(org):
    return MembershipFactory(organisation=org, role="tutor")


def start(api, membership, write=False):
    return api.post(
        "/api/v1/impersonate", {"membership_id": str(membership.pk), "write": write}, format="json"
    )


def test_admin_views_as_a_tutor_read_only(org, tutor):
    admin = MembershipFactory(organisation=org, role="admin").user
    api = client_for(org, admin)
    assert start(api, tutor).status_code == 204

    me = api.get("/api/v1/me").json()
    assert me["user"]["id"] == str(tutor.user_id)
    assert me["membership"]["role"] == "tutor"
    assert me["impersonator"]["id"] == str(admin.pk)
    assert me["impersonator"]["write"] is False

    for write in (
        api.patch("/api/v1/me", {"first_name": "Hacked"}, format="json"),
        api.post("/api/v1/onboarding/business", {"skip": True}, format="json"),
    ):
        assert write.status_code == 403
        assert write.json()["type"].endswith("impersonation-read-only")
    tutor.user.refresh_from_db()
    assert tutor.user.first_name != "Hacked"

    assert api.post("/api/v1/impersonate/stop").status_code == 204
    assert api.get("/api/v1/me").json()["user"]["id"] == str(admin.pk)
    types = list(OutboxEvent.objects.values_list("event_type", flat=True))
    assert {"impersonation.started", "impersonation.ended"} <= set(types)


def test_actions_are_audited_with_the_impersonator(org, tutor):
    owner = MembershipFactory(organisation=org, role="owner").user
    api = client_for(org, owner)
    assert start(api, tutor, write=True).status_code == 204
    with tenant_context(org):
        entry = AuditEntry.objects.get(action="impersonation_start")
    assert entry.actor_id == owner.pk
    # Writes made while impersonating record both people (UserContextMiddleware puts the
    # impersonator in the request context; audit.record reads it).
    from tutortrack.core.context import request_context

    with request_context(user_id=tutor.user_id, impersonator_id=owner.pk), tenant_context(org):
        from tutortrack.core import audit

        recorded = audit.record(tutor, "touched")
    assert recorded.impersonator_id == owner.pk


def test_write_access_is_owner_only(org, tutor):
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    assert start(admin, tutor, write=True).status_code == 403
    owner = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    assert start(owner, tutor, write=True).status_code == 204


def test_only_tutors_clients_and_students_can_be_impersonated(org):
    owner = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    other_admin = MembershipFactory(organisation=org, role="admin")
    assert start(owner, other_admin).status_code == 422
    parent = MembershipFactory(organisation=org, role="client")
    assert start(owner, parent).status_code == 204


def test_tutors_cannot_impersonate(org, tutor):
    other = MembershipFactory(organisation=org, role="tutor")
    api = client_for(org, tutor.user)
    assert start(api, other).status_code == 403


def test_impersonation_stays_in_its_organisation(org, other_org, tutor):
    owner = MembershipFactory(organisation=org, role="owner").user
    MembershipFactory(organisation=other_org, user=owner, role="owner")
    api = client_for(org, owner)
    start(api, tutor)
    elsewhere = client_for(other_org)
    elsewhere.cookies = api.cookies  # same browser session on another subdomain
    response = elsewhere.get("/api/v1/branches")
    assert response.status_code == 403
    assert response.json()["type"].endswith("impersonation-other-organisation")


def test_cannot_impersonate_members_of_other_organisations(org, other_org):
    owner = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    stranger = MembershipFactory(organisation=other_org, role="tutor")
    assert start(owner, stranger).status_code == 422
