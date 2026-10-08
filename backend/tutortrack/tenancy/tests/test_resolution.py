"""E02-T02: tenant resolution middleware (FR-02-3, FR-02-7)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory

from tutortrack.core.context import current_branch_ids, current_organisation_id
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.models import Membership
from tutortrack.identity.services import set_branch_scope
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.tenancy import services
from tutortrack.tenancy.middleware import TenantMiddleware
from tutortrack.tenancy.models import Branch, OrganisationDomain
from tutortrack.tenancy.resolution import SESSION_KEY
from tutortrack.tenancy.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db
BASE = "tutortrack.test"


def run(host: str, *, user: Any = None, headers: dict[str, str] | None = None, path: str = "/x"):
    """Run the middleware and capture what the view would see."""
    seen: dict[str, Any] = {}

    def view(request):
        seen.update(
            organisation=request.organisation,
            membership=request.membership,
            org_id=current_organisation_id(),
            branch_ids=current_branch_ids(),
        )
        return HttpResponse("ok")

    request = RequestFactory().get(path, HTTP_HOST=host, headers=headers or {})
    request.user = user or AnonymousUser()
    request.session = SessionStore()
    response = TenantMiddleware(view)(request)
    return response, seen, request


def test_subdomain_resolves_the_organisation(org):
    response, seen, _ = run(f"{org.slug}.{BASE}")
    assert response.status_code == 200
    assert seen["organisation"] == org
    assert seen["org_id"] == org.pk
    assert current_organisation_id() is None  # reset after the request


def test_unknown_subdomain_is_404_problem():
    response, seen, _ = run(f"nobody-here.{BASE}", path="/api/v1/features")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/problem+json"
    assert seen == {}


def test_former_slug_redirects_with_308_for_90_days(org):
    services.change_slug(org, "bright-renamed")
    response, _, _ = run(f"brightminds.{BASE}:8443", path="/api/v1/lessons?x=1")
    assert response.status_code == 308
    assert response["Location"] == f"http://bright-renamed.{BASE}:8443/api/v1/lessons?x=1"

    OrganisationDomain.objects.filter(hostname="brightminds").update(
        redirect_until=now() - timedelta(seconds=1)
    )
    assert run(f"brightminds.{BASE}")[0].status_code == 404


def test_verified_custom_domain_resolves_first(org):
    OrganisationDomain.objects.create(
        organisation=org, hostname="learn.example.com", type="custom", verified_at=now()
    )
    OrganisationDomain.objects.create(
        organisation=org, hostname="pending.example.com", type="custom"
    )
    assert run("learn.example.com")[1]["organisation"] == org
    assert run("pending.example.com")[1]["organisation"] is None


def test_reserved_labels_fall_through_to_the_root_chain(org):
    response, seen, _ = run(f"app.{BASE}")
    assert response.status_code == 200
    assert seen["organisation"] is None


def test_header_selects_organisation_for_members_only(org, other_org):
    membership = MembershipFactory(organisation=org)
    user = membership.user
    by_id = run(f"app.{BASE}", user=user, headers={"X-Organisation": str(org.pk)})[1]
    by_slug = run(f"app.{BASE}", user=user, headers={"X-Organisation": org.slug})[1]
    assert by_id["organisation"] == org
    assert by_slug["membership"] == membership

    # Not a member of other_org, unknown ids and anonymous callers all get a 404.
    assert (
        run(f"app.{BASE}", user=user, headers={"X-Organisation": str(other_org.pk)})[0].status_code
        == 404
    )
    assert run(f"app.{BASE}", user=user, headers={"X-Organisation": "nope"})[0].status_code == 404
    assert run(f"app.{BASE}", headers={"X-Organisation": str(org.pk)})[0].status_code == 404


def test_header_is_ignored_on_a_tenant_subdomain(org, other_org):
    user = MembershipFactory(organisation=other_org).user
    seen = run(f"{org.slug}.{BASE}", user=user, headers={"X-Organisation": str(other_org.pk)})[1]
    assert seen["organisation"] == org
    assert seen["membership"] is None  # not a member of org


def test_root_host_uses_the_last_active_organisation(org, other_org):
    user = UserFactory()
    MembershipFactory(organisation=org, user=user, last_active_at=now() - timedelta(days=2))
    MembershipFactory(organisation=other_org, user=user, last_active_at=now())
    assert run(f"app.{BASE}", user=user)[1]["organisation"] == other_org

    # Visiting org's subdomain remembers it in the session and on the membership.
    _, _, request = run(f"{org.slug}.{BASE}", user=user)
    assert request.session[SESSION_KEY] == str(org.pk)
    assert run(f"app.{BASE}", user=user)[1]["organisation"] == org


def test_membership_is_attached_and_branch_scope_applied(org):
    with_scope = MembershipFactory(organisation=org)
    north = BranchFactory(organisation=org, code="N")
    from tutortrack.core.context import tenant_context

    with tenant_context(org):
        set_branch_scope(with_scope, Membership.BranchScope.SELECTED, [north])
    seen = run(f"{org.slug}.{BASE}", user=with_scope.user)[1]
    assert seen["membership"] == with_scope
    assert seen["branch_ids"] == frozenset({north.pk})

    everyone = MembershipFactory(organisation=org)
    assert run(f"{org.slug}.{BASE}", user=everyone.user)[1]["branch_ids"] is None


def test_inactive_memberships_do_not_count(org):
    membership = MembershipFactory(organisation=org, status=Membership.Status.SUSPENDED)
    assert run(f"{org.slug}.{BASE}", user=membership.user)[1]["membership"] is None


def test_api_rejects_non_members_but_not_platform_staff(org, user, superuser):
    assert client_for(org, user).get("/api/v1/audit").status_code == 403
    assert client_for(org, superuser).get("/api/v1/audit").status_code == 200


def test_permissions_never_leak_across_organisations(org, other_org):
    """FR-02-7: an admin in one organisation has no access in another."""
    import uuid

    owner = MembershipFactory(organisation=org, role=Membership.Role.OWNER).user
    url = f"/api/v1/files/{uuid.uuid4()}"
    assert client_for(org, owner).get(url).status_code == 404  # past the org check
    assert client_for(other_org, owner).get(url).status_code == 403


def test_health_checks_skip_resolution():
    response, _, _ = run(f"nobody-here.{BASE}", path="/healthz")
    assert response.status_code == 200


def test_default_branch_exists_for_factory_orgs(org):
    from tutortrack.core.context import tenant_context

    with tenant_context(org):
        assert Branch.objects.filter(is_default=True).count() == 1
