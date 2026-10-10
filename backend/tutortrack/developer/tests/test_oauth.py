"""E27-T04: OAuth2 provider (authorisation code + PKCE, refresh, revoke, connected apps)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.developer import services
from tutortrack.developer.models import OAuthApplication, OAuthGrant, OAuthToken
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory

from .conftest import ROOT_HOST, bearer

pytestmark = pytest.mark.django_db
REDIRECT = "https://partner.example.com/callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def register(api, **overrides):
    body = {
        "name": "Partner CRM",
        "redirect_uris": [REDIRECT],
        "allowed_scopes": ["clients:read", "clients:write", "webhooks:write"],
        **overrides,
    }
    response = api.post("/api/v1/developer/oauth-apps", body)
    assert response.status_code == 201, response.content
    return response.json()


def authorize(api, app, *, challenge: str, scope: str = "clients:read", approve: bool = True):
    params = {
        "client_id": app["client_id"],
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": scope,
        "state": "xyz",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    consent = api.get("/api/v1/oauth/authorize", params)
    assert consent.status_code == 200, consent.content
    decision = api.post("/api/v1/oauth/authorize", {**params, "approve": approve})
    assert decision.status_code == 200, decision.content
    query = parse_qs(urlsplit(decision.json()["redirect_to"]).query)
    return consent.json(), query


def form_post(client, path, data):
    """OAuth endpoints take application/x-www-form-urlencoded bodies (RFC 6749)."""
    return client.post(
        path, urlencode(data), content_type="application/x-www-form-urlencoded",
        HTTP_HOST=ROOT_HOST,
    )  # fmt: skip


def token(client, **data):
    return form_post(client, "/api/v1/oauth/token", data)


def test_partner_apps_are_created_once():
    from tutortrack.developer.partners import ensure_partner_apps

    first = ensure_partner_apps()
    assert set(first) == {"zapier", "make"}
    assert all(secret and secret.startswith("ttsec_") for secret in first.values())
    assert ensure_partner_apps() == {"zapier": None, "make": None}
    zapier = OAuthApplication.objects.get(partner_key="zapier")
    assert zapier.owner_organisation_id is None
    assert zapier.published
    assert "webhooks:write" in zapier.allowed_scopes


def test_authorization_code_flow_with_pkce(api, client, org):
    ClientFactory(organisation=org)
    app = register(api)
    assert app["client_secret"].startswith("ttsec_")
    verifier, challenge = pkce()
    consent, query = authorize(api, app, challenge=challenge)
    assert consent["application"]["name"] == "Partner CRM"
    assert [s["key"] for s in consent["scopes"]] == ["clients:read"]
    assert query["state"] == ["xyz"]
    issued = token(
        client,
        grant_type="authorization_code",
        client_id=app["client_id"],
        client_secret=app["client_secret"],
        code=query["code"][0],
        redirect_uri=REDIRECT,
        code_verifier=verifier,
    )
    assert issued.status_code == 200, issued.content
    body = issued.json()
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "clients:read"
    assert issued["Cache-Control"] == "no-store"
    assert bearer(body["access_token"]).get("/api/v1/clients").status_code == 200
    # Scopes the user did not grant stay closed.
    assert bearer(body["access_token"]).post("/api/v1/clients", {}).status_code == 403
    # The connected app is listed for admins.
    rows = api.get("/api/v1/developer/connected-apps").json()["results"]
    assert rows[0]["application"]["client_id"] == app["client_id"]


def test_code_is_single_use_and_needs_the_verifier(api, client):
    app = register(api)
    verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge)
    base = {
        "grant_type": "authorization_code",
        "client_id": app["client_id"],
        "client_secret": app["client_secret"],
        "code": query["code"][0],
        "redirect_uri": REDIRECT,
    }
    wrong = token(client, **base, code_verifier="x" * 50)
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"
    good = token(client, **base, code_verifier=verifier)
    assert good.status_code == 200
    replay = token(client, **base, code_verifier=verifier)
    assert replay.json()["error"] == "invalid_grant"
    # A replayed code revokes what it issued.
    assert bearer(good.json()["access_token"]).get("/api/v1/clients").status_code == 401


def test_bad_client_secret_is_invalid_client(api, client):
    app = register(api)
    verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge)
    response = token(
        client, grant_type="authorization_code", client_id=app["client_id"],
        client_secret="ttsec_wrong", code=query["code"][0], redirect_uri=REDIRECT,
        code_verifier=verifier,
    )  # fmt: skip
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_public_clients_must_use_pkce(api):
    app = register(api, confidential=False)
    assert app["client_secret"] is None
    response = api.get(
        "/api/v1/oauth/authorize",
        {"client_id": app["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
         "scope": "clients:read"},
    )  # fmt: skip
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def test_unregistered_redirect_and_scope_are_refused(api):
    app = register(api)
    base = {"client_id": app["client_id"], "response_type": "code", "scope": "clients:read"}
    bad_redirect = api.get(
        "/api/v1/oauth/authorize", {**base, "redirect_uri": "https://evil.example/cb"}
    )
    assert bad_redirect.json()["error"] == "invalid_request"
    bad_scope = api.get(
        "/api/v1/oauth/authorize",
        {**base, "redirect_uri": REDIRECT, "scope": "invoices:read", "code_challenge": "a" * 43,
         "code_challenge_method": "S256"},
    )  # fmt: skip
    assert bad_scope.json()["error"] == "invalid_scope"


def test_denied_consent_redirects_with_error(api):
    app = register(api)
    _verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge, approve=False)
    assert query["error"] == ["access_denied"]


def test_refresh_rotates_and_reuse_revokes_everything(api, client):
    app = register(api)
    verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge)
    first = token(
        client, grant_type="authorization_code", client_id=app["client_id"],
        client_secret=app["client_secret"], code=query["code"][0], redirect_uri=REDIRECT,
        code_verifier=verifier,
    ).json()  # fmt: skip
    refresh = {
        "grant_type": "refresh_token",
        "client_id": app["client_id"],
        "client_secret": app["client_secret"],
    }
    second = token(client, **refresh, refresh_token=first["refresh_token"])
    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    reuse = token(client, **refresh, refresh_token=first["refresh_token"])
    assert reuse.json()["error"] == "invalid_grant"
    assert bearer(second.json()["access_token"]).get("/api/v1/clients").status_code == 401


def test_revocation_endpoint(api, client):
    app = register(api)
    verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge)
    issued = token(
        client, grant_type="authorization_code", client_id=app["client_id"],
        client_secret=app["client_secret"], code=query["code"][0], redirect_uri=REDIRECT,
        code_verifier=verifier,
    ).json()  # fmt: skip
    response = form_post(
        client, "/api/v1/oauth/revoke",
        {"token": issued["access_token"], "client_id": app["client_id"],
         "client_secret": app["client_secret"]},
    )  # fmt: skip
    assert response.status_code == 200
    assert bearer(issued["access_token"]).get("/api/v1/clients").status_code == 401
    unknown = form_post(
        client, "/api/v1/oauth/revoke", {"token": "nope", "client_id": app["client_id"]}
    )
    assert unknown.status_code == 200


def test_admin_disconnects_an_app(api, client, org):
    app = register(api)
    verifier, challenge = pkce()
    _consent, query = authorize(api, app, challenge=challenge)
    issued = token(
        client, grant_type="authorization_code", client_id=app["client_id"],
        client_secret=app["client_secret"], code=query["code"][0], redirect_uri=REDIRECT,
        code_verifier=verifier,
    ).json()  # fmt: skip
    grant_id = api.get("/api/v1/developer/connected-apps").json()["results"][0]["id"]
    assert api.post(f"/api/v1/developer/connected-apps/{grant_id}/revoke").status_code == 204
    assert bearer(issued["access_token"]).get("/api/v1/clients").status_code == 401
    with tenant_context(org):
        assert not OAuthToken.objects.filter(revoked_at__isnull=True).exists()


def test_rotate_secret_and_delete_app(api):
    app = register(api)
    rotated = api.post(f"/api/v1/developer/oauth-apps/{app['id']}/rotate-secret").json()
    assert rotated["client_secret"] != app["client_secret"]
    assert api.delete(f"/api/v1/developer/oauth-apps/{app['id']}").status_code == 204
    assert api.get("/api/v1/developer/oauth-apps").json()["results"] == []


def test_other_tenants_private_app_is_unknown_here(api, other_org):
    with tenant_context(other_org), transaction.atomic():
        theirs, _secret = services.register_application(
            name="Theirs", redirect_uris=[REDIRECT], allowed_scopes=["clients:read"]
        )
    response = api.get(
        "/api/v1/oauth/authorize",
        {"client_id": theirs.client_id, "redirect_uri": REDIRECT, "response_type": "code",
         "scope": "clients:read"},
    )  # fmt: skip
    assert response.json()["error"] == "invalid_client"


def test_partner_apps_show_in_the_marketplace(api, org):
    services.register_application(
        name="Make", redirect_uris=["https://www.integromat.com/oauth/cb/app"],
        allowed_scopes=["clients:read"], owner_organisation_id=None, partner_key="make",
        published=True, description="Automate with Make",
    )  # fmt: skip
    rows = api.get("/api/v1/developer/marketplace").json()
    make = next(r for r in rows if r["key"] == "make")
    assert make["kind"] == "partner"
    assert make["status"] == "available"
    stripe = next(r for r in rows if r["key"] == "stripe")
    assert stripe["status"] in ("available", "connected")
    assert {r["category"] for r in rows} >= {"payments", "accounting", "calendar", "messaging"}


class TestOAuthAppIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/developer/oauth-apps"

    def make_object(self, organisation):
        with tenant_context(organisation), transaction.atomic():
            app, _secret = services.register_application(
                name="App", redirect_uris=[REDIRECT], allowed_scopes=["clients:read"]
            )
        return app


class TestConnectedAppIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/developer/connected-apps"

    def make_object(self, organisation):
        user = UserFactory()
        MembershipFactory(organisation=organisation, user=user)
        app = OAuthApplication.objects.create(
            name="P", client_id=f"ttapp_{organisation.slug}", redirect_uris=[REDIRECT],
            allowed_scopes=[], owner_organisation_id=None,
        )  # fmt: skip
        with tenant_context(organisation):
            return OAuthGrant.objects.create(application=app, user=user, scopes=["clients:read"])
