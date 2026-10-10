"""E22-T01: the integration framework (OAuth + PKCE, encrypted tokens, refresh, health,
errors, disconnect, provider registry)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection as db

from tutortrack.comms.models import InAppNotification
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations import oauth, providers, services
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import AuthError, fake

pytestmark = pytest.mark.django_db


def member(org, role="tutor"):
    membership = MembershipFactory(organisation=org, role=role)
    return membership.user, client_for(org, membership.user)


def connect_google(org, user, who="sam"):
    with tenant_context(org):
        token, _state = oauth.make_state(
            organisation_id=org.pk,
            user_id=user.pk,
            provider="google",
            level="user",
            next_path="/",
        )
        return services.complete_oauth(user, code=f"fake-google-{who}", state=token)


def events(org, kind):
    with tenant_context(org):
        return [e.payload for e in OutboxEvent.objects.filter(event_type=kind)]


def test_providers_lists_capabilities_and_simulated_flag(org):
    _user, api = member(org)
    rows = {p["key"]: p for p in api.get("/api/v1/integrations/providers").json()}
    assert set(rows) >= {"google", "microsoft", "caldav", "zoom", "lessonspace"}
    assert rows["google"]["capabilities"] == ["calendar", "video"]
    assert rows["caldav"]["auth"] == "credentials"
    assert rows["caldav"]["credential_fields"] == ["username", "password", "server_url"]
    assert all(p["simulated"] for p in rows.values())  # no keys in tests


def test_oauth_flow_with_pkce_connects_and_encrypts_tokens(org):
    """Start → provider → callback (root host) → app completes while signed in."""
    user, api = member(org)
    response = api.post(
        "/api/v1/integrations/oauth/start",
        {"provider": "google", "level": "user", "next": "/portal/tutor/calendar"},
        format="json",
    )
    assert response.status_code == 200, response.content
    url = response.json()["authorize_url"]  # the fake consents immediately
    assert url.startswith(oauth.callback_url())
    callback = client_for(org).get(urlsplit(url).path + "?" + urlsplit(url).query)
    assert callback.status_code == 302
    target = urlsplit(callback["Location"])
    assert target.path == "/portal/tutor/calendar"
    params = {k: v[0] for k, v in parse_qs(target.query).items()}
    done = api.post("/api/v1/integrations/oauth/complete", params, format="json")
    assert done.status_code == 201, done.content
    body = done.json()
    assert body["status"] == "active"
    assert body["provider"] == "google"
    assert "access_token" not in body
    assert "refresh_token" not in body
    with tenant_context(org):
        conn = IntegrationConnection.objects.get(pk=body["id"])
        assert conn.access_token.startswith("fake-access-")
        assert conn.user == user
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT access_token, refresh_token FROM integrations_integrationconnection "
                "WHERE id = %s",
                [conn.pk],
            )
            raw = cursor.fetchone()
        assert "fake" not in raw[0]  # Fernet ciphertext at rest
        assert "fake" not in raw[1]
    assert events(org, "integration.connected")[0]["data"]["capabilities"] == [
        "calendar",
        "video",
    ]


def test_completion_is_bound_to_the_user_who_started(org):
    user, _api = member(org)
    _other, other_api = member(org)
    with tenant_context(org):
        token, _ = oauth.make_state(organisation_id=org.pk, user_id=user.pk, provider="google",
                                    level="user", next_path="/")  # fmt: skip
    response = other_api.post(
        "/api/v1/integrations/oauth/complete",
        {"code": "fake-google-x", "state": token},
        format="json",
    )
    assert response.status_code == 403
    tampered = other_api.post(
        "/api/v1/integrations/oauth/complete",
        {"code": "fake-google-x", "state": token + "x"},
        format="json",
    )
    assert tampered.status_code == 422


def test_pkce_verifier_is_derived_and_challenge_is_s256():
    verifier = oauth.verifier_for("nonce")
    assert 43 <= len(verifier) <= 128
    assert oauth.verifier_for("nonce") == verifier != oauth.verifier_for("other")
    assert len(oauth.challenge_for(verifier)) == 43


def test_org_level_connections_need_manage_permission(org):
    _user, tutor_api = member(org, "tutor")
    response = tutor_api.post(
        "/api/v1/integrations/oauth/start", {"provider": "zoom", "level": "organisation"},
        format="json",
    )  # fmt: skip
    assert response.status_code == 403
    _admin, admin_api = member(org, "admin")
    response = admin_api.post(
        "/api/v1/integrations/oauth/start", {"provider": "zoom", "level": "organisation"},
        format="json",
    )  # fmt: skip
    assert response.status_code == 200
    bad = admin_api.post(
        "/api/v1/integrations/oauth/start", {"provider": "google", "level": "organisation"},
        format="json",
    )  # fmt: skip
    assert bad.status_code == 422  # Google connects per person


def test_caldav_connects_with_an_encrypted_app_password(org):
    _user, api = member(org)
    wrong = api.post(
        "/api/v1/integrations/connections",
        {"provider": "caldav", "username": "sam@icloud.com", "password": "wrong-one"},
        format="json",
    )
    assert wrong.status_code == 422
    response = api.post(
        "/api/v1/integrations/connections",
        {"provider": "caldav", "username": "sam@icloud.com", "password": "abcd-efgh-ijkl"},
        format="json",
    )
    assert response.status_code == 201, response.content
    with tenant_context(org):
        conn = IntegrationConnection.objects.get(pk=response.json()["id"])
        assert conn.secret == "abcd-efgh-ijkl"
        assert services.credentials(conn).username == "sam@icloud.com"


def test_reconnecting_the_same_account_updates_in_place(org):
    user, _api = member(org)
    first = connect_google(org, user, "sam")
    second = connect_google(org, user, "sam")
    assert first.pk == second.pk
    assert events(org, "integration.connected")[-1]["data"]["reconnected"] is True
    other = connect_google(org, user, "alex")  # a different account replaces it
    with tenant_context(org):
        assert IntegrationConnection.objects.get(pk=first.pk).status == "disconnected"
        assert other.pk != first.pk


def test_tokens_refresh_before_expiry(org):
    user, _api = member(org)
    conn = connect_google(org, user)
    with tenant_context(org):
        conn.expires_at = now() + timedelta(seconds=30)
        old = conn.access_token
        conn.save()
        creds = services.credentials(conn)
        conn.refresh_from_db()
        assert creds.access_token == conn.access_token != old
        assert conn.expires_at > now() + timedelta(minutes=30)


def test_revoked_grant_needs_reconnect_and_tells_the_owner(org):
    user, api = member(org)
    conn = connect_google(org, user)
    fake.revoke(conn.external_account_id)
    with tenant_context(org):
        conn.expires_at = now() - timedelta(minutes=1)
        conn.save()
        with pytest.raises(AuthError):
            services.credentials(conn)
        conn.refresh_from_db()
        assert conn.status == "needs_reconnect"
        assert conn.error
    assert events(org, "integration.error")[0]["data"]["status"] == "needs_reconnect"
    row = api.get(f"/api/v1/integrations/connections/{conn.pk}").json()
    assert row["status"] == "needs_reconnect"
    assert row["error"]


def test_errors_surface_and_a_success_clears_them(org, django_capture_on_commit_callbacks):
    user, _api = member(org)
    conn = connect_google(org, user)
    with tenant_context(org):
        with django_capture_on_commit_callbacks(execute=True):
            services.record_failure(conn, providers.ProviderError("Google is down"))
        conn.refresh_from_db()
        assert conn.status == "error"
        assert conn.error_count == 1
        assert InAppNotification.objects.filter(user=user).exists()
        checked = services.check(conn)
        assert checked.status == "active"
        assert checked.error == ""


def test_health_check_endpoint_and_disconnect(org):
    user, api = member(org)
    conn = connect_google(org, user)
    assert api.post(f"/api/v1/integrations/connections/{conn.pk}/check").json()["status"] == (
        "active"
    )
    response = api.post(f"/api/v1/integrations/connections/{conn.pk}/disconnect")
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    with tenant_context(org):
        conn.refresh_from_db()
        assert conn.access_token == ""
        assert conn.refresh_token == ""
    assert events(org, "integration.disconnected")
    assert api.get("/api/v1/integrations/connections").json()["results"] == []


def test_people_only_see_and_manage_their_own_connections(org):
    owner, _api = member(org)
    _someone, someone_api = member(org)
    conn = connect_google(org, owner)
    assert someone_api.get(f"/api/v1/integrations/connections/{conn.pk}").status_code == 404
    _admin, admin_api = member(org, "admin")
    rows = admin_api.get("/api/v1/integrations/connections").json()["results"]
    assert [r["id"] for r in rows] == [str(conn.pk)]
    assert rows[0]["user"]["id"] == str(owner.pk)
    mine = admin_api.get("/api/v1/integrations/connections?mine=1").json()["results"]
    assert mine == []


class TestConnectionIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/integrations/connections"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return IntegrationConnection.objects.create(provider="zoom", level="organisation")
