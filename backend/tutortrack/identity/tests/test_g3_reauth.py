"""Gap G3: step-up re-authentication (password, authenticator code, passkey options) used
before showing full bank details (E12 §6)."""

from __future__ import annotations

import pyotp
import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.core.time import now
from tutortrack.identity.models import LoginEvent, MFADevice
from tutortrack.identity.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def test_authenticator_code_confirms_and_bad_codes_are_recorded(org):
    membership = MembershipFactory(organisation=org, role="finance")
    user = membership.user
    secret = pyotp.random_base32()
    MFADevice.objects.create(user=user, name="Phone", secret=secret, confirmed_at=now())
    api = client_for(org, user)
    status = api.get("/api/v1/auth/reauthenticate").json()
    assert status == {"recent": False, "methods": ["password", "totp"]}
    wrong = api.post("/api/v1/auth/reauthenticate", {"code": "000000"}, format="json")
    assert wrong.status_code == 403
    assert wrong.json()["type"].endswith("reauthentication-failed")
    assert LoginEvent.objects.filter(user=user, method="reauth", success=False).exists()
    ok = api.post("/api/v1/auth/reauthenticate", {"code": pyotp.TOTP(secret).now()}, format="json")
    assert ok.status_code == 200
    assert ok.json()["recent"] is True
    with tenant_context(org):
        from tutortrack.core.models import AuditEntry

        assert AuditEntry.objects.filter(action="reauthenticate").exists()


def test_nothing_given_is_refused(org):
    api = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    assert api.post("/api/v1/auth/reauthenticate", {}, format="json").status_code == 403


def test_passkey_options_hold_a_challenge(org):
    api = client_for(org, MembershipFactory(organisation=org, role="finance").user)
    options = api.post("/api/v1/auth/reauthenticate/options")
    assert options.status_code == 200, options.content
    assert options.json()["challenge"]


def test_signed_out_people_cant_reauthenticate(org):
    assert client_for(org).get("/api/v1/auth/reauthenticate").status_code in (401, 403)
