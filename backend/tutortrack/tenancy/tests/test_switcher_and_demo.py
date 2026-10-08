"""E02-T08: org switcher (FR-02-7) and demo-data mode with one-click wipe (FR-02-6)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.core.tests.testapp.models import Gadget, Gizmo
from tutortrack.core.time import now
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.tenancy import demo
from tutortrack.tenancy.models import DemoRecord, Organisation
from tutortrack.tenancy.tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db


# --- switcher -------------------------------------------------------------------------------------


def test_lists_my_organisations_most_recent_first(org, other_org):
    user = UserFactory()
    MembershipFactory(
        organisation=org, user=user, role="owner", last_active_at=now() - timedelta(1)
    )
    MembershipFactory(organisation=other_org, user=user, role="tutor", last_active_at=now())
    unrelated = OrganisationFactory(slug="unrelated")
    MembershipFactory(organisation=unrelated)  # someone else's

    response = client_for(org, user).get("/api/v1/me/organisations")
    assert response.status_code == 200
    rows = response.json()
    # Visiting org just now made it the most recent.
    assert [r["slug"] for r in rows] == [org.slug, other_org.slug]
    assert rows[0]["role"] == "owner"
    assert rows[0]["is_current"] is True
    assert rows[1]["is_current"] is False
    assert rows[1]["url"] == f"https://{other_org.slug}.tutortrack.test"


def test_switcher_works_on_the_root_host_and_hides_closed_orgs(org, other_org):
    user = UserFactory()
    MembershipFactory(organisation=org, user=user)
    MembershipFactory(organisation=other_org, user=user)
    Organisation.objects.filter(pk=other_org.pk).update(status=Organisation.Status.CANCELLED)
    client = APIClient(HTTP_HOST="app.tutortrack.test")
    client.force_login(user)
    assert [r["slug"] for r in client.get("/api/v1/me/organisations").json()] == [org.slug]


def test_switcher_excludes_inactive_memberships(org):
    membership = MembershipFactory(organisation=org, status=Membership.Status.REMOVED)
    client = APIClient(HTTP_HOST="app.tutortrack.test")
    client.force_login(membership.user)
    assert client.get("/api/v1/me/organisations").json() == []


def test_switcher_requires_sign_in():
    assert APIClient().get("/api/v1/me/organisations").status_code == 403


# --- demo data ------------------------------------------------------------------------------------


@pytest.fixture
def providers():
    """Two sample providers standing in for E05+ (people, lessons...)."""
    before = dict(demo._providers)
    wiped: list[int] = []

    @demo.demo_provider(order=10)
    def gadgets(ctx: demo.DemoContext) -> None:
        for name in ("Projector", "Whiteboard"):
            ctx.track(Gadget.objects.create(name=name))

    def wipe_gizmos(records: list[DemoRecord]) -> None:
        wiped.append(len(records))
        Gizmo.objects.filter(pk__in=[r.object_id for r in records]).delete()

    @demo.demo_provider(order=20, wipe=wipe_gizmos)
    def gizmos(ctx: demo.DemoContext) -> None:
        ctx.track(Gizmo.objects.create(name="Demo gizmo"))

    yield wiped
    demo._providers.clear()
    demo._providers.update(before)


def test_load_and_wipe_demo_data(org, providers):
    api = client_for(org, MembershipFactory(organisation=org, role="owner").user)
    with tenant_context(org):
        Gadget.objects.create(name="Real gadget")

    loaded = api.post("/api/v1/demo-data")
    assert loaded.status_code == 201
    assert loaded.json() == {"has_demo_data": True, "records": 3}
    assert Organisation.objects.get(pk=org.pk).has_demo_data
    assert api.get("/api/v1/organisation").json()["has_demo_data"] is True
    assert api.post("/api/v1/demo-data").status_code == 422  # already loaded

    wiped = api.delete("/api/v1/demo-data")
    assert wiped.json() == {"has_demo_data": False, "records": 3}
    assert providers == [1]  # the custom wipe handled its own record
    with tenant_context(org):
        assert list(Gadget.objects.values_list("name", flat=True)) == ["Real gadget"]
        assert not Gizmo.objects.exists()
        assert not DemoRecord.objects.exists()
    assert not Organisation.objects.get(pk=org.pk).has_demo_data


def test_demo_data_stays_in_its_organisation(org, other_org, providers):
    with tenant_context(org):
        demo.load_demo_data()
    with tenant_context(other_org):
        assert not Gadget.objects.exists()
        assert demo.wipe_demo_data() == 0
    with tenant_context(org):
        assert Gadget.objects.count() == 2


def test_demo_data_needs_manage_permission(org, providers):
    tutor = MembershipFactory(organisation=org, role=Membership.Role.TUTOR).user
    assert client_for(org, tutor).post("/api/v1/demo-data").status_code == 403
