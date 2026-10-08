"""E02-T06: signup, email verification, Turnstile, rate limiting and session handoff."""

from __future__ import annotations

import re
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.identity.models import Membership, User
from tutortrack.identity.tests.factories import TEST_PASSWORD, UserFactory
from tutortrack.identity.tokens import email_verification_token
from tutortrack.tenancy.models import Branch, OnboardingState, Organisation, OrganisationSettings

pytestmark = pytest.mark.django_db

PAYLOAD = {
    "first_name": "Sam",
    "last_name": "Patel",
    "email": "Sam@Example.com",
    "password": "a-long-passphrase-123",
    "business_name": "Sam Patel Tutoring",
    "country": "GB",
    "timezone": "Europe/London",
}


@pytest.fixture
def root():
    return APIClient(HTTP_HOST="app.tutortrack.test")


def signup(client, django_capture_on_commit_callbacks, **overrides):
    with django_capture_on_commit_callbacks(execute=True):
        return client.post("/api/v1/signup", {**PAYLOAD, **overrides}, format="json")


def handoff_from(response) -> str:
    return parse_qs(urlparse(response.json()["continue_url"]).query)["handoff"][0]


def test_signup_creates_user_organisation_and_owner(root, django_capture_on_commit_callbacks):
    response = signup(root, django_capture_on_commit_callbacks)
    assert response.status_code == 201, response.json()
    body = response.json()

    user = User.objects.get(email="sam@example.com")
    org = Organisation.objects.get(pk=body["organisation"]["id"])
    assert body["user"] == {"id": str(user.pk), "email": user.email, "email_verified": False}
    assert body["organisation"]["slug"] == "sam-patel-tutoring"
    assert body["continue_url"].startswith(
        "https://sam-patel-tutoring.tutortrack.test/onboarding?handoff="
    )
    assert (org.status, org.created_by, org.timezone) == ("trial", user, "Europe/London")
    with tenant_context(org):
        assert Branch.objects.filter(is_default=True).count() == 1
        assert Membership.objects.get().role == Membership.Role.OWNER
        assert OrganisationSettings.objects.exists()
        assert OnboardingState.objects.get().current_step == "business"
    assert OutboxEvent.objects.filter(
        organisation_id=org.pk, event_type="organisation.created"
    ).exists()
    # Signed in on the root host straight away.
    assert root.get("/api/v1/features").status_code == 200


def test_signup_sends_a_working_verification_email(root, django_capture_on_commit_callbacks):
    signup(root, django_capture_on_commit_callbacks)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["sam@example.com"]
    token = re.search(r"verify-email\?token=(\S+)", message.body).group(1)

    response = APIClient().post("/api/v1/signup/verify-email", {"token": token}, format="json")
    assert response.status_code == 200
    assert User.objects.get(email="sam@example.com").email_verified_at is not None


def test_verification_tokens_are_tamper_proof_and_bound_to_the_email(settings):
    user = UserFactory()
    token = email_verification_token(user)
    client = APIClient()
    bad = client.post("/api/v1/signup/verify-email", {"token": token + "x"}, format="json")
    assert bad.status_code == 400
    assert bad.json()["type"].endswith("invalid-token")

    user.email = "changed@example.com"
    user.save()
    assert (
        client.post("/api/v1/signup/verify-email", {"token": token}, format="json").status_code
        == 400
    )

    settings.EMAIL_VERIFICATION_MAX_AGE_SECONDS = -1
    fresh = email_verification_token(user)
    assert (
        client.post("/api/v1/signup/verify-email", {"token": fresh}, format="json").status_code
        == 400
    )


def test_resend_verification(django_capture_on_commit_callbacks):
    client = APIClient()
    client.force_login(UserFactory())
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/api/v1/signup/resend-verification").status_code == 202
    assert len(mail.outbox) == 1
    assert APIClient().post("/api/v1/signup/resend-verification").status_code == 403


@pytest.mark.parametrize("missing", ["email", "password", "first_name", "business_name"])
def test_required_fields(root, missing, django_capture_on_commit_callbacks):
    response = signup(root, django_capture_on_commit_callbacks, **{missing: ""})
    assert response.status_code == 400
    assert missing in response.json()["errors"]


def test_weak_password_is_rejected(root, django_capture_on_commit_callbacks):
    response = signup(root, django_capture_on_commit_callbacks, password="password")
    assert response.status_code == 422
    assert "password" in response.json()["errors"]
    assert not User.objects.filter(email="sam@example.com").exists()


def test_existing_email_must_sign_in_instead(root, django_capture_on_commit_callbacks):
    UserFactory(email="sam@example.com")
    response = signup(root, django_capture_on_commit_callbacks)
    assert response.status_code == 422
    assert "email" in response.json()["errors"]
    assert Organisation.objects.count() == 0


def test_reserved_slug_is_rejected(root, django_capture_on_commit_callbacks):
    response = signup(root, django_capture_on_commit_callbacks, slug="admin")
    assert response.status_code == 422
    assert response.json()["type"].endswith("invalid-slug")
    assert not User.objects.filter(email="sam@example.com").exists()  # rolled back


def test_signed_in_user_adds_a_second_organisation(org, django_capture_on_commit_callbacks):
    user = UserFactory(email_verified_at="2026-01-01T00:00:00Z")
    client = APIClient(HTTP_HOST="app.tutortrack.test")
    client.force_login(user)
    response = signup(
        client, django_capture_on_commit_callbacks, email="", password="", business_name="Second Co"
    )
    assert response.status_code == 201, response.json()
    assert response.json()["user"]["id"] == str(user.pk)
    from tutortrack.identity.selectors import memberships_for_user

    assert [m.organisation.name for m in memberships_for_user(user)] == ["Second Co"]
    assert mail.outbox == []  # already verified


def test_turnstile_is_enforced_when_configured(root, settings, django_capture_on_commit_callbacks):
    settings.TURNSTILE_SECRET_KEY = "secret"
    failed = signup(root, django_capture_on_commit_callbacks, turnstile_token="")
    assert failed.status_code == 400
    assert failed.json()["type"].endswith("captcha-failed")

    fake = mock.MagicMock()
    fake.__enter__.return_value.read.return_value = b'{"success": true}'
    with mock.patch("urllib.request.urlopen", return_value=fake) as urlopen:
        ok = signup(root, django_capture_on_commit_callbacks, turnstile_token="tok")
    assert ok.status_code == 201
    sent = urlopen.call_args.args[0]
    assert sent.full_url.startswith("https://challenges.cloudflare.com/")
    assert b"response=tok" in sent.data


def test_turnstile_outage_fails_closed(root, settings, django_capture_on_commit_callbacks):
    settings.TURNSTILE_SECRET_KEY = "secret"
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        response = signup(root, django_capture_on_commit_callbacks, turnstile_token="tok")
    assert response.status_code == 400


def test_signup_is_rate_limited_per_ip(monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"signup": "2/hour"})
    statuses = [
        signup(
            APIClient(HTTP_HOST="app.tutortrack.test"),
            django_capture_on_commit_callbacks,
            email=f"u{i}@example.com",
            business_name=f"Co {i}",
        ).status_code
        for i in range(3)
    ]
    assert statuses == [201, 201, 429]


def test_handoff_signs_in_on_the_new_organisation_once(root, django_capture_on_commit_callbacks):
    response = signup(root, django_capture_on_commit_callbacks)
    token = handoff_from(response)
    slug = response.json()["organisation"]["slug"]
    tenant = APIClient(HTTP_HOST=f"{slug}.tutortrack.test")

    assert tenant.get("/api/v1/onboarding/state").status_code == 403
    exchanged = tenant.post("/api/v1/auth/handoff", {"token": token}, format="json")
    assert exchanged.status_code == 200
    assert tenant.get("/api/v1/onboarding/state").status_code == 200

    again = APIClient(HTTP_HOST=f"{slug}.tutortrack.test")
    assert again.post("/api/v1/auth/handoff", {"token": token}, format="json").status_code == 400


def test_handoff_is_bound_to_its_organisation(root, org, django_capture_on_commit_callbacks):
    token = handoff_from(signup(root, django_capture_on_commit_callbacks))
    other = APIClient(HTTP_HOST=f"{org.slug}.tutortrack.test")
    assert other.post("/api/v1/auth/handoff", {"token": token}, format="json").status_code == 400
    anonymous_root = APIClient(HTTP_HOST="app.tutortrack.test")
    assert (
        anonymous_root.post("/api/v1/auth/handoff", {"token": token}, format="json").status_code
        == 404
    )


def test_slug_check(org):
    client = APIClient()
    taken = client.get("/api/v1/signup/slug-check", {"slug": org.slug}).json()
    assert taken["available"] is False
    assert "taken" in taken["reason"]
    assert client.get("/api/v1/signup/slug-check", {"slug": "www"}).json()["available"] is False
    free = client.get("/api/v1/signup/slug-check", {"name": "Bright Minds"}).json()
    assert free == {
        "slug": "bright-minds",
        "available": True,
        "reason": None,
        "suggestion": "bright-minds",
    }


def test_signup_config_is_public(settings):
    settings.TURNSTILE_SITE_KEY = "site-key"
    response = APIClient().get("/api/v1/signup/config")
    assert response.json() == {"turnstile_site_key": "site-key"}


def test_existing_password_login_still_works_after_signup(root, django_capture_on_commit_callbacks):
    signup(root, django_capture_on_commit_callbacks)
    user = User.objects.get(email="sam@example.com")
    assert user.check_password(PAYLOAD["password"])
    assert not user.check_password(TEST_PASSWORD)
