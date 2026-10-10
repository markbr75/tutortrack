"""E27-T01/T02: public API surface, scopes, API keys, rate limits, versioning headers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.permission_registry import all_permissions, matches
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.developer import deprecations, scopes, services
from tutortrack.developer.models import ApiKey, CredentialRoute
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory
from tutortrack.tenancy.tests.factories import BranchFactory

from .conftest import bearer, make_key

pytestmark = pytest.mark.django_db


# --- scope catalogue ----------------------------------------------------------------------------


def test_every_scope_pattern_names_a_registered_permission():
    registered = list(all_permissions())
    for resource in scopes.RESOURCES.values():
        for pattern in (*resource.read, *resource.write):
            assert any(matches(pattern, c) for c in registered), pattern


def test_public_views_exist():
    from django.utils.module_loading import import_string

    for path in scopes.PUBLIC_VIEWS:
        assert import_string(f"tutortrack.{path}")


def test_write_scope_implies_read():
    assert scopes.has_scope(["clients:write"], "clients", write=False)
    assert not scopes.has_scope(["clients:read"], "clients", write=True)
    assert "people.client.create" in scopes.permission_patterns(["clients:write"])
    assert "people.client.create" not in scopes.permission_patterns(["clients:read"])


# --- API keys -----------------------------------------------------------------------------------


def test_create_key_shows_the_secret_once_and_stores_a_hash(api, org):
    response = api.post(
        "/api/v1/developer/api-keys", {"name": "CRM sync", "scopes": ["clients:read"]}
    )
    assert response.status_code == 201, response.content
    secret = response.json()["secret"]
    assert secret.startswith("ttk_")
    with tenant_context(org):
        key = ApiKey.objects.get(pk=response.json()["id"])
        assert secret not in key.secret_hash
        assert len(key.secret_hash) == 64
    assert CredentialRoute.objects.filter(prefix=key.prefix, organisation_id=org.pk).exists()
    listed = api.get("/api/v1/developer/api-keys").json()["results"][0]
    assert "secret" not in listed
    assert listed["display"].startswith("ttk_")


def test_unknown_scope_is_rejected(api):
    response = api.post("/api/v1/developer/api-keys", {"name": "x", "scopes": ["root:all"]})
    assert response.status_code == 400


def test_key_reads_public_endpoint_in_its_organisation(org, other_org, user, member):
    mine = ClientFactory(organisation=org)
    theirs = ClientFactory(organisation=other_org)
    _key, token = make_key(org, user, ["clients:read"])
    response = bearer(token).get("/api/v1/clients")
    assert response.status_code == 200, response.content
    ids = {row["id"] for row in response.json()["results"]}
    assert str(mine.pk) in ids
    assert str(theirs.pk) not in ids
    assert response["X-RateLimit-Limit"] == "600"
    assert "X-RateLimit-Remaining" in response
    assert "X-RateLimit-Reset" in response


def test_key_on_another_organisations_address_is_404(org, other_org, user, member):
    _key, token = make_key(org, user, ["clients:read"])
    response = bearer(token, host=f"{other_org.slug}.tutortrack.test").get("/api/v1/clients")
    assert response.status_code == 404


def test_missing_scope_and_read_only_scope(org, user, member):
    _key, token = make_key(org, user, ["clients:read"])
    client = bearer(token)
    denied = client.get("/api/v1/invoices")
    assert denied.status_code == 403
    assert denied.json()["required_scope"] == "invoices:read"
    write = client.post("/api/v1/clients", {"display_name": "New"})
    assert write.status_code == 403
    assert write.json()["required_scope"] == "clients:write"


def test_write_scope_allows_creating(org, user, member):
    _key, token = make_key(org, user, ["clients:write"])
    response = bearer(token).post("/api/v1/clients", {"display_name": "API family"})
    assert response.status_code == 201, response.content


def test_internal_endpoints_refuse_tokens(org, user, member):
    _key, token = make_key(org, user, list(scopes.ALL_SCOPES))
    for path in ("/api/v1/me", "/api/v1/developer/api-keys", "/api/v1/audit"):
        response = bearer(token).get(path)
        assert response.status_code == 403, path
        assert response.json()["type"].endswith("endpoint-not-public")


def test_scopes_narrow_but_never_widen_role_permissions(org):
    """A coordinator can't read invoices' finance-only parts, whatever the key's scopes."""
    coordinator = UserFactory()
    MembershipFactory(organisation=org, user=coordinator, role=Membership.Role.COORDINATOR)
    _key, token = make_key(org, coordinator, ["payments:read"])
    assert bearer(token).get("/api/v1/payments").status_code == 403  # role lacks it
    admin = UserFactory()
    MembershipFactory(organisation=org, user=admin, role=Membership.Role.ADMIN)
    _key, token = make_key(org, admin, ["payments:read"])
    assert bearer(token).get("/api/v1/payments").status_code == 200


def test_permission_layer_uses_scope_patterns(org, user, member):
    from tutortrack.core.permissions import has_perm

    user.token_permissions = scopes.permission_patterns(["clients:read"])
    with tenant_context(org):
        assert has_perm(user, "people.client.view")
        assert not has_perm(user, "people.client.create")
        assert not has_perm(user, "billing.invoice.view")
    del user.token_permissions


def test_revoked_expired_and_malformed_tokens_are_401(org, user, member):
    key, token = make_key(org, user, ["clients:read"])
    assert bearer("ttk_nonsense").get("/api/v1/clients").status_code == 401
    with tenant_context(org), transaction.atomic():
        services.revoke_api_key(key)
    response = bearer(token).get("/api/v1/clients")
    assert response.status_code == 401
    assert "Bearer" in response["WWW-Authenticate"]
    expired, token2 = make_key(org, user, ["clients:read"])
    with tenant_context(org):
        ApiKey.objects.filter(pk=expired.pk).update(expires_at=now() - timedelta(minutes=1))
    assert bearer(token2).get("/api/v1/clients").status_code == 401


def test_key_stops_when_its_user_leaves(org, user, member):
    _key, token = make_key(org, user, ["clients:read"])
    with tenant_context(org):
        Membership.objects.filter(pk=member.pk).update(status=Membership.Status.SUSPENDED)
    assert bearer(token).get("/api/v1/clients").status_code == 401


def test_ip_allowlist(org, user, member):
    _key, token = make_key(org, user, ["clients:read"], ip_allowlist=["203.0.113.0/24"])
    assert bearer(token, REMOTE_ADDR="198.51.100.7").get("/api/v1/clients").status_code == 401
    assert bearer(token, REMOTE_ADDR="203.0.113.9").get("/api/v1/clients").status_code == 200


def test_branch_scoped_key_sees_only_its_branch(org, user, member):
    north = BranchFactory(organisation=org)
    south = BranchFactory(organisation=org)
    in_north = ClientFactory(organisation=org, branch=north)
    in_south = ClientFactory(organisation=org, branch=south)
    _key, token = make_key(org, user, ["clients:read"], branch=north)
    ids = {r["id"] for r in bearer(token).get("/api/v1/clients").json()["results"]}
    assert str(in_north.pk) in ids
    assert str(in_south.pk) not in ids


def test_rotation_overlaps_then_old_key_expires(api, org, user):
    created = api.post(
        "/api/v1/developer/api-keys", {"name": "Rotate me", "scopes": ["clients:read"]}
    ).json()
    rotated = api.post(f"/api/v1/developer/api-keys/{created['id']}/rotate")
    assert rotated.status_code == 201
    assert rotated.json()["rotated_from"] == created["id"]
    assert bearer(created["secret"]).get("/api/v1/clients").status_code == 200  # overlap
    assert bearer(rotated.json()["secret"]).get("/api/v1/clients").status_code == 200
    with tenant_context(org):
        old = ApiKey.objects.get(pk=created["id"])
        assert old.expires_at is not None
        assert old.expires_at <= now() + timedelta(hours=24)
        ApiKey.objects.filter(pk=old.pk).update(expires_at=now() - timedelta(seconds=1))
    assert bearer(created["secret"]).get("/api/v1/clients").status_code == 401


def test_rate_limit_returns_429_with_retry_after(org, user, member, settings):
    settings.DEVELOPER_API = {**settings.DEVELOPER_API, "RATE_LIMIT_PER_MINUTE": 3}
    _key, token = make_key(org, user, ["clients:read"])
    client = bearer(token)
    statuses = [client.get("/api/v1/clients").status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    limited = client.get("/api/v1/clients")
    assert int(limited["Retry-After"]) >= 1
    assert limited["X-RateLimit-Remaining"] == "0"


def test_burst_limit_per_second():
    from tutortrack.developer import ratelimit

    verdicts = [ratelimit.hit("burst-test", 1000, at=1_000_000.2) for _ in range(101)]
    assert not verdicts[99].exceeded
    assert verdicts[100].exceeded
    assert verdicts[100].retry_after == 1


def test_session_auth_is_unchanged(api):
    assert api.get("/api/v1/me").status_code == 200
    assert api.get("/api/v1/clients").status_code == 200
    assert "X-RateLimit-Limit" not in api.get("/api/v1/clients")


def test_deprecated_endpoints_announce_sunset(api, monkeypatch):
    monkeypatch.setitem(
        deprecations.DEPRECATIONS,
        "people.api.views.ClientViewSet",
        deprecations.Deprecation(date(2026, 10, 1), date(2027, 4, 1), "https://docs.example/x"),
    )
    response = api.get("/api/v1/clients")
    assert response["Sunset"] == "Thu, 01 Apr 2027 00:00:00 GMT"
    assert response["Deprecation"].startswith("@")
    assert 'rel="deprecation"' in response["Link"]


def test_audit_actor_is_the_keys_user(org, user, member):
    from tutortrack.core.models import AuditEntry

    _key, token = make_key(org, user, ["clients:write"])
    created = bearer(token).post("/api/v1/clients", {"display_name": "Audited"}).json()
    with tenant_context(org):
        entry = AuditEntry.objects.filter(object_id=created["id"]).first()
        assert entry is not None
        assert entry.actor_id == user.pk


# --- docs portal --------------------------------------------------------------------------------


def test_public_schema_contains_only_public_operations(client):
    from tutortrack.developer import docs

    docs.clear_cache()
    response = client.get("/api/v1/developer/openapi.json", HTTP_HOST="tutortrack.test")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/clients" in paths
    assert "/api/v1/webhook-endpoints" in paths
    assert "/api/v1/me" not in paths
    assert "/api/v1/developer/api-keys" not in paths
    operation = paths["/api/v1/clients"]["get"]
    assert operation["x-visibility"] == "public"
    assert operation["x-scopes"] == ["clients:read"]


def test_postman_changelog_and_connectors(client, org, superuser):
    from tutortrack.developer.models import OAuthApplication

    services.register_application(
        name="Zapier", redirect_uris=["https://zapier.com/dashboard/auth/oauth/return/App/"],
        allowed_scopes=list(scopes.ALL_SCOPES), owner_organisation_id=None,
        partner_key="zapier", published=True,
    )  # fmt: skip
    host = {"HTTP_HOST": "tutortrack.test"}
    postman = client.get("/api/v1/developer/postman.json", **host).json()
    assert postman["auth"]["type"] == "bearer"
    assert any(folder["item"] for folder in postman["item"])
    assert client.get("/api/v1/developer/changelog", **host).json()[0]["change_kind"] == "added"
    zapier = client.get("/api/v1/developer/connectors/zapier", **host).json()
    app = OAuthApplication.objects.get(partner_key="zapier")
    assert zapier["authentication"]["client_id"] == app.client_id
    events = {t["event"] for t in zapier["triggers"]}
    assert {"enquiry.received", "lesson.completed", "invoice.paid"} <= events
    assert {a["key"] for a in zapier["actions"]} >= {"create_client", "add_tag", "create_charge"}
    assert client.get("/api/v1/developer/connectors/make", **host).status_code == 200
    assert client.get("/api/v1/developer/connectors/ifttt", **host).status_code == 404


def test_scope_catalogue_endpoint(api):
    rows = api.get("/api/v1/developer/scopes").json()
    keys = {r["key"] for r in rows}
    assert "clients:read" in keys
    assert "payroll:write" not in keys


# --- isolation ----------------------------------------------------------------------------------


class TestApiKeyIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/developer/api-keys"

    def make_object(self, organisation):
        user = UserFactory()
        MembershipFactory(organisation=organisation, user=user)
        key, _secret = make_key(organisation, user, ["clients:read"])
        return key


def test_member_without_permission_cannot_manage_keys(org):
    tutor = UserFactory()
    MembershipFactory(organisation=org, user=tutor, role=Membership.Role.TUTOR)
    assert client_for(org, tutor).get("/api/v1/developer/api-keys").status_code == 403
