"""E03-T04/T05/T09: permission registry, built-in roles, data scopes, field permissions and
tutor access toggles."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.permission_registry import all_permissions, expand
from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.core.testing import client_for, result_ids
from tutortrack.core.tests.factories import GizmoFactory, WidgetFactory
from tutortrack.core.tests.testapp.models import Gizmo
from tutortrack.identity import rbac
from tutortrack.identity.models import Membership
from tutortrack.identity.roles import ROLES, Grant
from tutortrack.identity.services import set_branch_scope
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.tenancy import settings_service
from tutortrack.tenancy.models import Branch
from tutortrack.tenancy.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db


def member(org, role, **kwargs):
    return MembershipFactory(organisation=org, role=role, **kwargs).user


# --- registry and roles ---------------------------------------------------------------------------


def test_registry_collects_app_permissions():
    perms = all_permissions()
    assert {"audit.view", "org.close", "org.settings.manage", "team.invite"} <= set(perms)
    assert perms["team.invite"].category == "team"
    assert expand("org.*") == [
        "org.branch.manage", "org.close", "org.settings.manage", "org.settings.view",
    ]  # fmt: skip


def test_every_builtin_grant_is_well_formed():
    for role in ROLES.values():
        for grant in role.grants:
            assert Grant.parse(f"{grant.pattern}:{grant.scope}") == grant


@pytest.mark.parametrize(
    ("role", "codename", "allowed"),
    [
        ("owner", "org.close", True),
        ("owner", "subscription.manage", True),
        ("admin", "org.close", False),
        ("admin", "subscription.manage", False),
        ("admin", "billing.invoice.issue", True),
        ("admin", "impersonation.write", False),
        ("coordinator", "people.client.edit", True),
        ("coordinator", "billing.invoice.view", True),
        ("coordinator", "billing.invoice.issue", False),
        ("coordinator", "billing.rates.view_pay", False),
        ("finance", "payroll.payrun.approve", True),
        ("finance", "scheduling.lesson.create", False),
        ("tutor", "scheduling.lesson.view", True),
        ("tutor", "billing.rates.view_charge", False),
        ("client", "portal.client.invoice.view", True),
        ("client", "org.settings.view", False),
    ],
)
def test_builtin_roles(org, role, codename, allowed):
    user = member(org, role)
    with tenant_context(org):
        assert has_perm(user, codename) is allowed


def test_permissions_never_carry_across_organisations(org, other_org):
    user = member(org, "owner")
    with tenant_context(other_org):
        assert has_perm(user, "org.settings.view") is False
    with tenant_context(org):
        assert has_perm(user, "org.settings.view") is True


def test_inactive_memberships_grant_nothing(org):
    user = member(org, "admin", status=Membership.Status.SUSPENDED)
    with tenant_context(org):
        assert has_perm(user, "org.settings.view") is False


def test_roles_and_permissions_endpoints(org):
    api = client_for(org, member(org, "admin"))
    roles = {r["key"]: r for r in api.get("/api/v1/roles").json()}
    assert set(roles) == set(ROLES)
    assert roles["owner"]["grants"] == ["*:all"]
    assert "org.close" in roles["admin"]["denies"]
    codes = {p["codename"] for p in api.get("/api/v1/permissions").json()}
    assert "team.invite" in codes


# --- data scopes ----------------------------------------------------------------------------------


def test_tutor_sees_only_their_own_records(org):
    """AC: a tutor fetching another tutor's lesson gets 404, not 403."""
    tutor_a, tutor_b = member(org, "tutor"), member(org, "tutor")
    mine = GizmoFactory(organisation=org, assignee=tutor_a)
    theirs = GizmoFactory(organisation=org, assignee=tutor_b)
    api = client_for(org, tutor_a)
    assert result_ids(api.get("/api/v1/test/gizmos")) == {str(mine.pk)}
    assert api.get(f"/api/v1/test/gizmos/{theirs.pk}").status_code == 404
    assert api.get(f"/api/v1/test/gizmos/{mine.pk}").status_code == 200
    with tenant_context(org):
        assert has_perm(tutor_a, "scheduling.lesson.view", mine) is True
        assert has_perm(tutor_a, "scheduling.lesson.view", theirs) is False


def test_roles_without_the_permission_see_nothing(org):
    GizmoFactory(organisation=org)
    client = member(org, "client")
    with tenant_context(org):
        assert not scope_queryset(client, Gizmo.objects.all(), "scheduling.lesson.view").exists()


def test_branch_scope_for_branch_managers(org):
    with tenant_context(org):
        main = Branch.objects.get(is_default=True)
    north = BranchFactory(organisation=org, code="N")
    membership = MembershipFactory(organisation=org, role="branch_manager")
    with tenant_context(org):
        set_branch_scope(membership, Membership.BranchScope.SELECTED, [north])
    in_main = GizmoFactory(organisation=org, branch=main)
    in_north = GizmoFactory(organisation=org, branch=north)
    user = membership.user
    with tenant_context(org):
        rbac.clear_cache(user)
        visible = scope_queryset(user, Gizmo.objects.all(), "scheduling.lesson.view")
        assert list(visible) == [in_north]
        assert has_perm(user, "scheduling.lesson.view", in_north) is True
        assert has_perm(user, "scheduling.lesson.view", in_main) is False
        assert has_perm(user, "org.settings.manage") is False


def test_superusers_are_unrestricted(org, superuser):
    GizmoFactory(organisation=org)
    with tenant_context(org):
        assert scope_queryset(superuser, Gizmo.objects.all(), "anything").count() == 1


# --- field permissions ----------------------------------------------------------------------------


def widget_fields(org, role):
    widget = WidgetFactory(organisation=org)
    response = client_for(org, member(org, role)).get(f"/api/v1/test/widgets/{widget.pk}")
    assert response.status_code == 200
    return set(response.json())


def test_tutors_never_see_charge_rates(org):
    """AC: a tutor never sees charge_rate (``price`` here) in any payload."""
    assert "price" not in widget_fields(org, "tutor")


def test_coordinators_without_view_pay_never_see_pay_rates(org):
    fields = widget_fields(org, "coordinator")
    assert "hourly_rate" not in fields
    assert "price" in fields


def test_admins_see_both_rates(org):
    assert {"price", "hourly_rate"} <= widget_fields(org, "admin")


def test_hidden_fields_cannot_be_written(org):
    widget = WidgetFactory(organisation=org, name="w")
    api = client_for(org, member(org, "coordinator"))
    api.patch(
        f"/api/v1/test/widgets/{widget.pk}",
        {"hourly_rate": {"amount": "99.0000", "currency": "GBP"}},
        format="json",
    )
    with tenant_context(org):
        widget.refresh_from_db()
    assert widget.hourly_rate is None


# --- tutor access toggles (FR-03-6) ---------------------------------------------------------------


def test_tutor_toggles_map_to_permissions(org):
    tutor = member(org, "tutor")
    with tenant_context(org):
        assert has_perm(tutor, "scheduling.lesson.create") is False
        assert has_perm(tutor, "scheduling.lesson.reschedule") is True  # default on
        assert has_perm(tutor, "people.contact.view_phone") is True  # "phone only" default
        assert has_perm(tutor, "people.contact.view_details") is False
        settings_service.update_settings(
            "tutor_access",
            {
                "tutor_access.create_lessons": True,
                "tutor_access.reschedule_lessons": False,
                "tutor_access.client_contact_details": "full",
            },
        )
        rbac.clear_cache(tutor)
        assert has_perm(tutor, "scheduling.lesson.create") is True
        assert has_perm(tutor, "scheduling.lesson.reschedule") is False
        assert has_perm(tutor, "people.contact.view_details") is True
        assert has_perm(tutor, "billing.rates.edit") is False  # never by default


def test_toggles_only_affect_tutors(org):
    coordinator = member(org, "coordinator")
    with tenant_context(org):
        settings_service.update_settings("tutor_access", {"tutor_access.edit_rates": True})
        assert has_perm(coordinator, "billing.rates.edit") is False
