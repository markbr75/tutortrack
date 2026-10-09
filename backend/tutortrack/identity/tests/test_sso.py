"""E03-T07: Google / Microsoft sign-in (OIDC with PKCE)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from tutortrack.identity import sso
from tutortrack.identity.models import SocialAccount, User
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db
ROOT = "app.tutortrack.test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def google(settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = "client-123"
    settings.GOOGLE_CLIENT_SECRET = "secret"
    settings.APP_URL = "https://app.tutortrack.test"
    monkeypatch.setattr(
        sso, "_jwks_client", lambda url: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=KEY.public_key())
        ),
    )  # fmt: skip


def id_token(expected_nonce: str, **claims: object) -> str:
    payload = {
        "iss": "https://accounts.google.com",
        "aud": "client-123",
        "sub": "google-sub-1",
        "email": "sam@example.com",
        "email_verified": True,
        "given_name": "Sam",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": expected_nonce,
        **claims,
    }
    return jwt.encode(payload, KEY, algorithm="RS256", headers={"kid": "k1"})


def start(client: APIClient, **params: str):
    response = client.get("/api/v1/auth/sso/google/start", params)
    assert response.status_code == 302
    query = parse_qs(urlparse(response["Location"]).query)
    return query


def finish(client, monkeypatch, query, **claims):
    nonce, state = query["nonce"][0], query["state"][0]
    captured = {}

    def fake_post(url, data):
        captured.update(data)
        return {"id_token": id_token(nonce, **claims)}

    monkeypatch.setattr(sso, "_post_form", fake_post)
    response = client.get("/api/v1/auth/sso/google/callback", {"code": "abc", "state": state})
    return response, captured


def test_start_redirects_with_pkce_and_state_cookie():
    client = APIClient(HTTP_HOST=ROOT)
    query = start(client, next="/calendar")
    assert query["client_id"] == ["client-123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://app.tutortrack.test/api/v1/auth/sso/google/callback"]
    assert sso.STATE_COOKIE in client.cookies
    assert client.cookies[sso.STATE_COOKIE]["httponly"]


def test_existing_user_signs_in_and_account_is_linked(monkeypatch):
    user = UserFactory(email="sam@example.com")
    client = APIClient(HTTP_HOST=ROOT)
    response, sent = finish(client, monkeypatch, start(client, next="/calendar"))
    assert response.status_code == 302
    assert response["Location"] == "https://app.tutortrack.test/calendar"
    assert "code_verifier" in sent
    assert sent["code"] == "abc"
    assert client.get("/api/v1/me").json()["user"]["email"] == "sam@example.com"
    account = SocialAccount.objects.get(user=user)
    assert (account.provider, account.subject) == ("google", "google-sub-1")

    # Next time the linked subject is used even if the email changed at Google.
    other = APIClient(HTTP_HOST=ROOT)
    response, _ = finish(other, monkeypatch, start(other), email="new@example.com")
    assert other.get("/api/v1/me").json()["user"]["id"] == str(user.pk)


def test_continues_to_the_organisation_with_a_handoff(org, monkeypatch):
    user = MembershipFactory(organisation=org, user__email="sam@example.com").user
    client = APIClient(HTTP_HOST=ROOT)
    response, _ = finish(client, monkeypatch, start(client, org=str(org.pk), next="/settings"))
    location = urlparse(response["Location"])
    assert location.netloc == "brightminds.tutortrack.test"
    assert location.path == "/auth/continue"
    token = parse_qs(location.query)["handoff"][0]
    tenant = APIClient(HTTP_HOST="brightminds.tutortrack.test")
    assert tenant.post("/api/v1/auth/handoff", {"token": token}, format="json").status_code == 200
    assert tenant.get("/api/v1/me").json()["user"]["id"] == str(user.pk)


@pytest.mark.parametrize(
    ("claims", "error"),
    [
        ({"email_verified": False}, "email_unverified"),
        ({"aud": "someone-else"}, "id_token"),
        ({"iss": "https://evil.example"}, "issuer"),
        ({"nonce": "replayed"}, "nonce"),
        ({"exp": int(time.time()) - 3600}, "id_token"),
    ],
)
def test_bad_tokens_are_rejected(monkeypatch, claims, error):
    UserFactory(email="sam@example.com")
    client = APIClient(HTTP_HOST=ROOT)
    response, _ = finish(client, monkeypatch, start(client), **claims)
    assert response["Location"] == f"https://app.tutortrack.test/login?error=sso_{error}"
    assert client.get("/api/v1/me").status_code == 403


def test_state_must_match_this_browser(monkeypatch):
    UserFactory(email="sam@example.com")
    attacker = APIClient(HTTP_HOST=ROOT)
    query = start(attacker)
    victim = APIClient(HTTP_HOST=ROOT)  # no state cookie
    monkeypatch.setattr(
        sso, "_post_form", lambda url, data: {"id_token": id_token(query["nonce"][0])}
    )
    response = victim.get(
        "/api/v1/auth/sso/google/callback", {"code": "abc", "state": query["state"][0]}
    )
    assert response["Location"].endswith("error=sso_state")


def test_unknown_people_need_signup_intent(monkeypatch):
    client = APIClient(HTTP_HOST=ROOT)
    response, _ = finish(client, monkeypatch, start(client))
    assert response["Location"].endswith("error=sso_no_account")
    assert not User.objects.filter(email="sam@example.com").exists()

    response, _ = finish(client, monkeypatch, start(client, intent="signup"))
    assert response["Location"] == "https://app.tutortrack.test/signup"
    user = User.objects.get(email="sam@example.com")
    assert user.email_verified_at is not None
    assert not user.has_usable_password()


def test_users_with_2fa_still_need_their_code(monkeypatch):
    import pyotp

    from tutortrack.identity import auth

    user = UserFactory(email="sam@example.com")
    device, _ = auth.start_totp_setup(user)
    auth.confirm_totp(user, str(device.pk), pyotp.TOTP(device.secret).now())
    client = APIClient(HTTP_HOST=ROOT)
    response, _ = finish(client, monkeypatch, start(client))
    assert response["Location"] == "https://app.tutortrack.test/login?mfa=1"
    assert client.get("/api/v1/me").status_code == 403


def test_disabled_providers_are_404(settings):
    settings.MICROSOFT_CLIENT_ID = ""
    client = APIClient(HTTP_HOST=ROOT)
    assert client.get("/api/v1/auth/sso/microsoft/start").status_code == 404
    keys = [p["key"] for p in client.get("/api/v1/auth/sso/providers").json()]
    assert keys == ["google"]


def test_microsoft_issuer_uses_the_tenant_id(settings):
    settings.MICROSOFT_CLIENT_ID = "ms-client"
    settings.MICROSOFT_CLIENT_SECRET = "s"
    provider = sso.get_provider("microsoft")
    token = jwt.encode(
        {"iss": "https://login.microsoftonline.com/tid-1/v2.0", "tid": "tid-1", "aud": "ms-client",
         "sub": "x", "iat": int(time.time()), "exp": int(time.time()) + 60, "nonce": "n"},
        KEY, algorithm="RS256",
    )  # fmt: skip
    assert sso.verify_id_token(provider, token, "n")["tid"] == "tid-1"
