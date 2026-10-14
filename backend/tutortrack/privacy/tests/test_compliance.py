"""E29-T11 data residency, DPA and sub-processors; E29-T12 security.txt."""

from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.privacy import compliance
from tutortrack.privacy.models import DPAAcceptance, SubprocessorNotice
from tutortrack.tenancy import regions

pytestmark = pytest.mark.django_db


def test_owners_accept_the_current_dpa(org, owner_api):
    status = owner_api.get("/api/v1/dpa").json()
    assert status["version"] == compliance.DPA_VERSION
    assert status["accepted"] is False
    wrong = owner_api.post(
        "/api/v1/dpa",
        {"version": "2001-01", "signer_name": "Sam", "company_name": "Bright Minds Ltd"},
        format="json",
    )
    assert wrong.status_code == 422
    accepted = owner_api.post(
        "/api/v1/dpa",
        {
            "version": compliance.DPA_VERSION,
            "signer_name": "Sam Patel",
            "signer_title": "Director",
            "company_name": "Bright Minds Ltd",
        },
        format="json",
    ).json()
    assert accepted["accepted"] is True
    assert accepted["acceptance"]["signer_name"] == "Sam Patel"
    with tenant_context(org):
        assert DPAAcceptance.objects.get().ip is not None


def test_admins_cannot_sign_the_dpa(org, admin_member):
    assert client_for(org, admin_member).get("/api/v1/dpa").status_code == 403


def test_the_subprocessor_list_is_public_and_filterable_by_region():
    api = APIClient()
    everything = api.get("/api/v1/subprocessors").json()
    assert everything["version"] == compliance.SUBPROCESSORS_VERSION
    names = {s["name"] for s in everything["subprocessors"]}
    assert {"Amazon Web Services", "Stripe", "Twilio"} <= names
    us = api.get("/api/v1/subprocessors?region=us").json()["subprocessors"]
    assert "GoCardless" not in {s["name"] for s in us}


def test_subprocessor_changes_are_announced_once(org, owner, django_capture_on_commit_callbacks):
    with tenant_context(org), django_capture_on_commit_callbacks(execute=True):
        assert compliance.notify_subprocessor_change() is True
        assert compliance.notify_subprocessor_change() is False
    with tenant_context(org):
        assert SubprocessorNotice.objects.get().version == compliance.SUBPROCESSORS_VERSION
        assert Message.objects.filter(type_key="privacy_subprocessors_changed").exists()


def test_security_txt_is_served():
    response = APIClient().get("/.well-known/security.txt")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    text = response.content.decode()
    assert "Contact: mailto:" in text
    assert "Expires: " in text
    assert "Policy: " in text


# --- regional stacks ----------------------------------------------------------------------------


def test_a_single_stack_serves_every_region():
    assert regions.describe("US")["serves_here"] is True


@override_settings(TT_REGION="uk")
def test_the_uk_stack_sends_us_signups_to_the_us_region():
    info = regions.describe("us")
    assert info == {
        "country": "US",
        "region": "us",
        "region_name": "United States",
        "serves_here": False,
        "signup_url": "https://us.tutortrack.app/signup?country=US",
    }
    assert regions.describe("GB")["serves_here"] is True
    assert regions.describe("DE")["region"] == "eu"
    api = APIClient()
    assert api.get("/api/v1/signup/region?country=US").json()["serves_here"] is False
    assert api.get("/api/v1/signup/region?country=1").status_code == 422


@override_settings(TT_REGION="uk")
def test_signup_on_the_wrong_stack_is_refused_with_the_right_address(monkeypatch):
    monkeypatch.setattr("tutortrack.tenancy.api.signup.verify_turnstile", lambda *a: True)
    response = APIClient().post(
        "/api/v1/signup",
        {
            "business_name": "Austin Tutors",
            "country": "US",
            "first_name": "Ana",
            "email": "ana@example.com",
            "password": "a-long-passphrase-123",
        },
        format="json",
    )
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["region"] == "us"
    assert body["signup_url"].startswith("https://us.tutortrack.app/signup")
    from tutortrack.identity.models import User

    assert not User.objects.filter(email="ana@example.com").exists()
