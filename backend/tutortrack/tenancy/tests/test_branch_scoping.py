"""E02-T04: branch-scoped models and membership branch scopes (FR-02-2)."""

import pytest

from tutortrack.core.context import branch_scope, tenant_context
from tutortrack.core.exceptions import CrossBranchWrite
from tutortrack.core.testing import TenantIsolationTestMixin, client_for, result_ids
from tutortrack.core.tests.factories import GizmoFactory
from tutortrack.core.tests.testapp.models import Gizmo
from tutortrack.identity.models import Membership
from tutortrack.identity.services import set_branch_scope
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.tenancy.models import Branch
from tutortrack.tenancy.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def branches(org):
    with tenant_context(org):
        main = Branch.objects.get(is_default=True)
    return main, BranchFactory(organisation=org, code="N", name="North")


def test_records_default_to_the_default_branch(tenant, branches):
    main, _ = branches
    gizmo = Gizmo.objects.create(name="Whiteboard")
    assert gizmo.branch_id == main.pk


def test_manager_filters_to_the_branch_scope(tenant, branches):
    main, north = branches
    a = GizmoFactory(organisation=tenant, branch=main)
    b = GizmoFactory(organisation=tenant, branch=north)
    assert set(Gizmo.objects.all()) == {a, b}  # unrestricted
    with branch_scope([north.pk]):
        assert list(Gizmo.objects.all()) == [b]
        assert not Gizmo.objects.filter(pk=a.pk).exists()
        assert Gizmo.objects.count() == 1
    with branch_scope([]):
        assert not Gizmo.objects.exists()


def test_cannot_write_into_a_branch_outside_scope(tenant, branches):
    main, north = branches
    with branch_scope([north.pk]):
        Gizmo.objects.create(name="ok", branch=north)
        with pytest.raises(CrossBranchWrite):
            Gizmo.objects.create(name="nope", branch=main)
        with pytest.raises(CrossBranchWrite):
            Gizmo.objects.create(name="defaults to main")


def scoped_member(org, branch):
    membership = MembershipFactory(organisation=org, role=Membership.Role.BRANCH_MANAGER)
    with tenant_context(org):
        set_branch_scope(membership, Membership.BranchScope.SELECTED, [branch])
    return membership.user


def test_branch_restricted_member_sees_only_their_branch_via_api(org, branches):
    """AC: a branch-restricted admin sees only records in their branches."""
    main, north = branches
    in_main = GizmoFactory(organisation=org, branch=main)
    in_north = GizmoFactory(organisation=org, branch=north)
    api = client_for(org, scoped_member(org, north))

    response = api.get("/api/v1/test/gizmos")
    assert response.status_code == 200
    assert result_ids(response) == {str(in_north.pk)}
    assert api.get(f"/api/v1/test/gizmos/{in_main.pk}").status_code == 404
    assert api.get(f"/api/v1/test/gizmos/{in_north.pk}").status_code == 200

    everyone = MembershipFactory(organisation=org).user
    assert result_ids(client_for(org, everyone).get("/api/v1/test/gizmos")) == {
        str(in_main.pk),
        str(in_north.pk),
    }


def test_branch_restricted_member_cannot_create_in_other_branch(org, branches):
    main, north = branches
    api = client_for(org, scoped_member(org, north))
    ok = api.post("/api/v1/test/gizmos", {"name": "a", "branch": str(north.pk)}, format="json")
    assert ok.status_code == 201
    denied = api.post("/api/v1/test/gizmos", {"name": "b", "branch": str(main.pk)}, format="json")
    assert denied.status_code == 403
    assert denied.json()["type"].endswith("cross-branch-write")


def test_selected_scope_requires_a_branch(org):
    from tutortrack.core.exceptions import BusinessRuleViolation

    membership = MembershipFactory(organisation=org)
    with tenant_context(org), pytest.raises(BusinessRuleViolation):
        set_branch_scope(membership, Membership.BranchScope.SELECTED, [])


class TestGizmoIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/test/gizmos"

    def make_object(self, organisation):
        return GizmoFactory(organisation=organisation)
