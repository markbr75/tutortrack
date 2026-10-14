"""Gap batch G2 (FR-03-2): Sign in with Apple against a fake Apple.

The fake signs ID tokens with its own RSA key (served instead of Apple's JWKS) and checks
the client secret we send: an ES256 JWT from our team, signed with the team's key."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from rest_framework.test import APIClient

from tutortrack.identity import sso
from tutortrack.identity.models import SocialAccount, User
from tutortrack.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
ROOT = "app.tutortrack.test"
APPLE_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEAM_KEY = ec.generate_private_key(ec.SECP256R1())
TEAM_KEY_PEM = TEAM_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()


@pytest.fixture(autouse=True)
def apple(settings, monkeypatch):
    settings.APPLE_CLIENT_ID = "app.tutortrack.signin"
    settings.APPLE_TEAM_ID = "TEAM123456"
    settings.APPLE_KEY_ID = "KEY1234567"
    settings.APPLE_PRIVATE_KEY = TEAM_KEY_PEM
    settings.APP_URL = "https://app.tutortrack.test"
    monkeypatch.setattr(
        sso,
        "_jwks_client",
        lambda url: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(
                key=APPLE_SIGNING_KEY.public_key()
            )
        ),
    )


def id_token(nonce: str, **claims: object) -> str:
    payload = {
        "iss": "https://appleid.apple.com",
        "aud": "app.tutortrack.signin",
        "sub": "001234.apple-user",
        "email": "abc123@privaterelay.appleid.com",
        "email_verified": "true",
        "is_private_email": "true",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": nonce,
        **claims,
    }
    return jwt.encode(payload, APPLE_SIGNING_KEY, algorithm="RS256", headers={"kid": "apple1"})


def start(client: APIClient, **params: str) -> dict[str, list[str]]:
    response = client.get("/api/v1/auth/sso/apple/start", params)
    assert response.status_code == 302
    assert response["Location"].startswith("https://appleid.apple.com/auth/authorize?")
    return parse_qs(urlparse(response["Location"]).query)


def fake_apple(monkeypatch, nonce: str, **claims: object) -> dict[str, str]:
    """Apple's token endpoint: checks our ES256 client secret, returns an ID token."""
    sent: dict[str, str] = {}

    def token_endpoint(url: str, data: dict[str, str]) -> dict[str, str]:
        assert url == "https://appleid.apple.com/auth/token"
        sent.update(data)
        secret = jwt.decode(
            data["client_secret"],
            TEAM_KEY.public_key(),
            algorithms=["ES256"],
            audience="https://appleid.apple.com",
        )
        assert secret["iss"] == "TEAM123456"
        assert secret["sub"] == "app.tutortrack.signin"
        assert jwt.get_unverified_header(data["client_secret"])["kid"] == "KEY1234567"
        return {"id_token": id_token(nonce, **claims)}

    monkeypatch.setattr(sso, "_post_form", token_endpoint)
    return sent


def form_post(client: APIClient, data: dict[str, str]):
    """Apple posts the code back as an HTML form (response_mode=form_post)."""
    return client.post(
        "/api/v1/auth/sso/apple/callback",
        urlencode(data),
        content_type="application/x-www-form-urlencoded",
    )


def test_apple_is_offered_when_configured():
    keys = [p["key"] for p in APIClient(HTTP_HOST=ROOT).get("/api/v1/auth/sso/providers").json()]
    assert "apple" in keys


def test_start_asks_for_name_and_email_with_form_post():
    client = APIClient(HTTP_HOST=ROOT)
    query = start(client)
    assert query["scope"] == ["openid name email"]
    assert query["response_mode"] == ["form_post"]
    assert query["client_id"] == ["app.tutortrack.signin"]
    assert "code_challenge" not in query  # Apple's token endpoint doesn't take PKCE


def test_new_person_signs_up_with_apple_and_name_from_the_first_post(monkeypatch):
    client = APIClient(HTTP_HOST=ROOT)
    query = start(client, intent="signup")
    sent = fake_apple(monkeypatch, query["nonce"][0])
    response = form_post(
        client,
        {
            "code": "c1",
            "state": query["state"][0],
            "user": json.dumps({"name": {"firstName": "Ada", "lastName": "Lovelace"}}),
        },
    )
    assert response.status_code == 302
    assert response["Location"] == "https://app.tutortrack.test/signup"
    assert sent["code"] == "c1"
    assert "code_verifier" not in sent
    user = User.objects.get(email="abc123@privaterelay.appleid.com")
    assert (user.first_name, user.last_name) == ("Ada", "Lovelace")
    assert user.email_verified_at is not None
    assert SocialAccount.objects.filter(user=user, provider="apple").exists()


def test_existing_user_matched_by_verified_email(monkeypatch):
    user = UserFactory(email="sam@example.com")
    client = APIClient(HTTP_HOST=ROOT)
    query = start(client, next="/calendar")
    fake_apple(monkeypatch, query["nonce"][0], email="sam@example.com", email_verified=True)
    response = form_post(client, {"code": "c", "state": query["state"][0]})
    assert response["Location"] == "https://app.tutortrack.test/calendar"
    assert client.get("/api/v1/me").json()["user"]["id"] == str(user.pk)


def test_unverified_email_and_wrong_state_are_refused(monkeypatch):
    UserFactory(email="sam@example.com")
    client = APIClient(HTTP_HOST=ROOT)
    query = start(client)
    fake_apple(monkeypatch, query["nonce"][0], email="sam@example.com", email_verified="false")
    response = form_post(client, {"code": "c", "state": query["state"][0]})
    assert response["Location"].endswith("error=sso_email_unverified")

    query = start(client)
    fake_apple(monkeypatch, query["nonce"][0])
    response = form_post(client, {"code": "c", "state": "forged"})
    assert response["Location"].endswith("error=sso_state")


def test_google_callback_does_not_accept_posts(settings):
    settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET = "g", "s"
    client = APIClient(HTTP_HOST=ROOT)
    assert client.post("/api/v1/auth/sso/google/callback", {"code": "c"}).status_code == 404


def test_apple_needs_every_credential(settings):
    settings.APPLE_PRIVATE_KEY = ""
    assert sso.get_provider("apple") is None
    assert APIClient(HTTP_HOST=ROOT).get("/api/v1/auth/sso/apple/start").status_code == 404
