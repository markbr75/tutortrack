"""E03-T01/T02/T06: password login, sessions, password reset, magic link, lockout, MFA."""

from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

import pyotp
import pytest
from django.core import mail
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now
from tutortrack.identity import auth
from tutortrack.identity.models import LoginEvent, LoginToken, MFADevice, UserSession
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory, UserFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db
HOST = "brightminds.tutortrack.test"


@pytest.fixture
def client(org):
    return APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="Browser A")


@pytest.fixture
def person(org):
    return MembershipFactory(organisation=org, role="admin", user__email="sam@example.com").user


def login(client, email="sam@example.com", password=TEST_PASSWORD, **extra):
    return client.post(
        "/api/v1/auth/login", {"email": email, "password": password, **extra}, format="json"
    )


def link_from_mail(pattern: str) -> str:
    return re.search(pattern, mail.outbox[-1].body).group(1)


# --- password login and sessions ------------------------------------------------------------------


def test_password_login_and_me(client, person, org):
    response = login(client)
    assert response.status_code == 200, response.json()
    assert response.json()["mfa_required"] is False
    assert response.json()["user"]["email"] == "sam@example.com"

    me = client.get("/api/v1/me").json()
    assert me["user"]["email"] == "sam@example.com"
    assert me["organisation"]["slug"] == org.slug
    assert me["membership"]["role"] == "admin"
    assert me["permissions"]["org.settings.manage"] == "all"
    assert "org.close" not in me["permissions"]  # owner only
    assert me["impersonator"] is None
    assert "csrftoken" in client.cookies
    session = UserSession.objects.get(user=person)
    assert session.method == "password"
    assert OutboxEvent.objects.filter(event_type="user.logged_in").exists()


def test_errors_are_uniform_and_attempts_recorded(client, person):
    wrong = login(client, password="nope")
    unknown = login(client, email="nobody@example.com", password="nope")
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json()["title"] == unknown.json()["title"] == "Incorrect email or password"
    assert LoginEvent.objects.filter(success=False).count() == 2


def test_progressive_lockout(client, person):
    for _ in range(5):
        assert login(client, password="nope").status_code == 400
    locked = login(client)  # even the right password waits
    assert locked.status_code == 429
    assert int(locked["Retry-After"]) > 0
    # After the delay the right password works and resets the counter.
    LoginEvent.objects.update(created_at=now() - timedelta(minutes=2))
    assert login(client).status_code == 200
    assert auth.lockout_seconds("sam@example.com") == 0


def test_logout_revokes_the_session(client, person):
    login(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 403
    assert UserSession.objects.get(user=person).revoked_at is not None


def test_sessions_list_and_revoke(person):
    a, b = (
        APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="A"),
        APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="B"),
    )
    login(a)
    login(b)
    sessions = a.get("/api/v1/me/sessions").json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["is_current"])
    assert a.delete(f"/api/v1/me/sessions/{other['id']}").status_code == 204
    assert b.get("/api/v1/me").status_code == 403  # signed out remotely
    assert a.get("/api/v1/me").status_code == 200

    c = APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="C")
    login(c)
    assert a.post("/api/v1/me/sessions/revoke-all").json() == {"revoked": 1}
    assert c.get("/api/v1/me").status_code == 403
    assert a.get("/api/v1/me").status_code == 200


def test_idle_sessions_expire_unless_remembered(person):
    short, remembered = APIClient(HTTP_HOST=HOST), APIClient(HTTP_HOST=HOST)
    login(short)
    login(remembered, remember=True)
    UserSession.objects.update(last_seen_at=now() - timedelta(hours=9))
    assert short.get("/api/v1/me").status_code == 403
    assert remembered.get("/api/v1/me").status_code == 200


def test_organisation_idle_timeout_is_shorter(client, person, org):
    with tenant_context(org):
        settings_service.update_settings("security", {"security.staff_idle_timeout_hours": 1})
    login(client)
    UserSession.objects.update(last_seen_at=now() - timedelta(hours=2))
    response = client.get("/api/v1/branches")
    assert response.status_code == 401
    assert response.json()["type"].endswith("session-expired")


def test_new_device_alert(person, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        login(APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="Laptop"))
        login(APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="Laptop"))
    assert mail.outbox == []  # first ever login and a known device: no alert
    with django_capture_on_commit_callbacks(execute=True):
        login(APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT="Phone"))
    assert len(mail.outbox) == 1
    assert "new device" in mail.outbox[0].body
    assert "Phone" in mail.outbox[0].body


# --- passwords ------------------------------------------------------------------------------------


def test_password_reset_flow(client, person, django_capture_on_commit_callbacks):
    other_device = APIClient(HTTP_HOST=HOST)
    login(other_device)
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            client.post(
                "/api/v1/auth/password/reset", {"email": "SAM@example.com"}, format="json"
            ).status_code
            == 202
        )
    uid, token = re.search(r"uid=(\S+)&token=(\S+)", mail.outbox[0].body).groups()
    new = "violet-harbour-lantern-42"
    confirm = {"uid": uid, "token": token, "new_password": new}
    assert (
        client.post("/api/v1/auth/password/reset/confirm", confirm, format="json").status_code
        == 204
    )
    # Single use, every session signed out, new password works.
    assert (
        client.post("/api/v1/auth/password/reset/confirm", confirm, format="json").status_code
        == 400
    )
    assert other_device.get("/api/v1/me").status_code == 403
    assert login(client, password=new).status_code == 200


def test_password_reset_for_unknown_email_is_silent(client):
    response = client.post(
        "/api/v1/auth/password/reset", {"email": "no@example.com"}, format="json"
    )
    assert response.status_code == 202
    assert mail.outbox == []


def test_weak_passwords_are_rejected(client, person):
    login(client)
    response = client.post(
        "/api/v1/me/password",
        {"current_password": TEST_PASSWORD, "new_password": "password1"},
        format="json",
    )
    assert response.status_code == 422
    assert "new_password" in response.json()["errors"]


def test_change_password_keeps_this_session_only(client, person):
    other = APIClient(HTTP_HOST=HOST)
    login(client)
    login(other)
    body = {"current_password": TEST_PASSWORD, "new_password": "violet-harbour-lantern-42"}
    assert client.post("/api/v1/me/password", body, format="json").status_code == 204
    assert client.get("/api/v1/me").status_code == 200
    assert other.get("/api/v1/me").status_code == 403
    wrong = client.post(
        "/api/v1/me/password",
        {"current_password": "nope", "new_password": "violet-harbour-lantern-43"},
        format="json",
    )
    assert wrong.status_code == 400


def test_pwned_passwords_are_rejected(settings):
    from django.core.exceptions import ValidationError

    from tutortrack.identity.password_validation import PwnedPasswordValidator

    settings.PWNED_PASSWORDS_CHECK = True
    # SHA-1("violet-harbour-lantern-42") suffix reported as breached.
    import hashlib

    digest = hashlib.sha1(b"violet-harbour-lantern-42").hexdigest().upper()  # noqa: S324
    fake = mock.MagicMock()
    fake.__enter__.return_value.read.return_value = f"{digest[5:]}:12\r\nABCDEF:0".encode()
    with (
        mock.patch("urllib.request.urlopen", return_value=fake) as urlopen,
        pytest.raises(ValidationError),
    ):
        PwnedPasswordValidator().validate("violet-harbour-lantern-42")
    assert urlopen.call_args.args[0].full_url.endswith(digest[:5])  # only the prefix is sent
    with mock.patch("urllib.request.urlopen", side_effect=OSError):
        PwnedPasswordValidator().validate("violet-harbour-lantern-42")  # outage: allowed


# --- magic link -----------------------------------------------------------------------------------


def test_magic_link_login(client, person, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            client.post(
                "/api/v1/auth/magic-link",
                {"email": "sam@example.com", "next": "/calendar"},
                format="json",
            ).status_code
            == 202
        )
    assert f"http://{HOST}/login/magic?token=" in mail.outbox[0].body
    token = link_from_mail(r"token=([^&\s]+)")
    response = client.post("/api/v1/auth/magic-link/verify", {"token": token}, format="json")
    assert response.status_code == 200
    assert response.json()["mfa_required"] is False
    assert client.get("/api/v1/me").status_code == 200
    # Single use.
    again = APIClient(HTTP_HOST=HOST)
    assert (
        again.post("/api/v1/auth/magic-link/verify", {"token": token}, format="json").status_code
        == 400
    )


def test_magic_link_expires(client, person, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/api/v1/auth/magic-link", {"email": "sam@example.com"}, format="json")
    token = link_from_mail(r"token=([^&\s]+)")
    LoginToken.objects.update(expires_at=now() - timedelta(seconds=1))
    assert (
        client.post("/api/v1/auth/magic-link/verify", {"token": token}, format="json").status_code
        == 400
    )


def test_magic_link_for_unknown_email_is_silent(client):
    assert (
        client.post(
            "/api/v1/auth/magic-link", {"email": "x@example.com"}, format="json"
        ).status_code
        == 202
    )
    assert mail.outbox == []


# --- MFA ------------------------------------------------------------------------------------------


def enrol_totp(client) -> tuple[str, list[str]]:
    setup = client.post("/api/v1/me/mfa/totp").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/TutorTrack:")
    assert setup["qr_svg"].startswith("<svg")
    code = pyotp.TOTP(setup["secret"]).now()
    confirmed = client.post(
        "/api/v1/me/mfa/totp/confirm",
        {"device_id": setup["device_id"], "code": code},
        format="json",
    )
    assert confirmed.status_code == 200, confirmed.json()
    return setup["secret"], confirmed.json()["recovery_codes"]


def test_totp_enrolment_and_two_step_login(client, person):
    login(client)
    secret, codes = enrol_totp(client)
    assert len(codes) == 10
    assert client.get("/api/v1/me").json()["user"]["has_mfa"] is True
    # The secret is encrypted at rest.
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT secret FROM identity_mfadevice")
        assert cursor.fetchone()[0] != secret

    fresh = APIClient(HTTP_HOST=HOST)
    first = login(fresh)
    assert first.json() == {"mfa_required": True, "user": None}
    assert fresh.get("/api/v1/me").status_code == 403  # not signed in yet
    MFADevice.objects.update(last_used_step=None)  # the enrolment used the current step
    code = pyotp.TOTP(secret).now()
    assert fresh.post("/api/v1/auth/mfa/verify", {"code": code}, format="json").status_code == 200
    assert fresh.get("/api/v1/me").status_code == 200
    assert UserSession.objects.filter(user=person, mfa_verified=True).exists()

    # The same code can't be replayed.
    replay = APIClient(HTTP_HOST=HOST)
    login(replay)
    assert replay.post("/api/v1/auth/mfa/verify", {"code": code}, format="json").status_code == 400


def test_recovery_codes_work_once(client, person):
    login(client)
    _, codes = enrol_totp(client)
    for expected in (200, 400):
        fresh = APIClient(HTTP_HOST=HOST)
        login(fresh)
        response = fresh.post("/api/v1/auth/mfa/verify", {"code": codes[0]}, format="json")
        assert response.status_code == expected


def test_mfa_verify_needs_a_pending_login(client):
    response = client.post("/api/v1/auth/mfa/verify", {"code": "123456"}, format="json")
    assert response.status_code == 400
    assert response.json()["type"].endswith("mfa-not-pending")


def test_disable_mfa_needs_password(client, person):
    login(client)
    enrol_totp(client)
    assert (
        client.post("/api/v1/me/mfa/disable", {"password": "nope"}, format="json").status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/me/mfa/disable", {"password": TEST_PASSWORD}, format="json"
        ).status_code
        == 204
    )
    assert login(APIClient(HTTP_HOST=HOST)).json()["mfa_required"] is False


def test_enforced_2fa_blocks_staff_until_enrolled(client, person, org):
    with tenant_context(org):
        settings_service.update_settings("security", {"security.require_mfa_for_staff": True})
    login(client)
    blocked = client.get("/api/v1/branches")
    assert blocked.status_code == 403
    assert blocked.json()["type"].endswith("mfa-enrolment-required")
    assert client.get("/api/v1/me").status_code == 200  # can still reach account settings
    enrol_totp(client)
    assert client.get("/api/v1/branches").status_code == 200


def test_enforced_2fa_does_not_apply_to_clients(org):
    with tenant_context(org):
        settings_service.update_settings("security", {"security.require_mfa_for_staff": True})
    parent = MembershipFactory(organisation=org, role="client").user
    api = APIClient(HTTP_HOST=HOST)
    login(api, email=parent.email)
    response = api.get("/api/v1/branches")
    assert response.json()["type"].endswith("permission-denied")  # not mfa-enrolment-required


def test_users_without_membership_can_still_sign_in_on_root():
    UserFactory(email="lone@example.com")
    api = APIClient(HTTP_HOST="app.tutortrack.test")
    assert login(api, email="lone@example.com").status_code == 200
    me = api.get("/api/v1/me").json()
    assert me["organisation"] is None
    assert me["permissions"] == {}
