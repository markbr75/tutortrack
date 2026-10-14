"""G6: impossible-travel alerts (FR-29-2) and global account deletion (FR-03-9, FR-29-4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient

from tutortrack.core.context import tenant_context
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.time import now
from tutortrack.identity import account_deletion
from tutortrack.identity.models import (
    AccountDeletion,
    LoginEvent,
    Membership,
    MFADevice,
    User,
    UserSession,
)
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory, ContactFactory
from tutortrack.privacy.models import DataSubjectRequest, ErasureRecord, LegalHold
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db
HOST = "brightminds.tutortrack.test"


def login(country: str = "", agent: str = "Laptop", email: str = "sam@example.com"):
    headers = {"HTTP_CF_IPCOUNTRY": country} if country else {}
    client = APIClient(HTTP_HOST=HOST, HTTP_USER_AGENT=agent, **headers)
    response = client.post(
        "/api/v1/auth/login", {"email": email, "password": TEST_PASSWORD}, format="json"
    )
    assert response.status_code == 200, response.json()
    return client


@pytest.fixture
def person(org):
    return MembershipFactory(organisation=org, role="admin", user__email="sam@example.com").user


@pytest.fixture
def owner(org):
    return MembershipFactory(organisation=org, role="owner", user__email="olu@example.com").user


# --- impossible travel ---------------------------------------------------------------------------


def test_sign_in_records_the_cdn_country(person):
    login("gb")
    assert LoginEvent.objects.get(user=person).country == "GB"


def test_unknown_country_values_are_ignored(person):
    login("XX")
    login("T1")
    assert set(LoginEvent.objects.filter(user=person).values_list("country", flat=True)) == {""}


def test_another_country_too_soon_alerts_the_person_and_the_owners(
    org, person, owner, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        login("GB")
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        login("AU")
    alert = OutboxEvent.objects.get(event_type="security.alert")
    assert alert.organisation_id == org.pk
    assert alert.payload["data"] == {"kind": "impossible_travel", "detail": "GB -> AU within 2h"}
    to_person = [m for m in mail.outbox if m.to == ["sam@example.com"]]
    assert len(to_person) == 1
    assert "AU" in to_person[0].body
    assert "GB" in to_person[0].body


def test_same_country_or_outside_the_window_is_fine(person, django_capture_on_commit_callbacks):
    login("GB")
    login("GB", agent="Phone")
    LoginEvent.objects.filter(user=person).update(created_at=now() - timedelta(hours=3))
    with django_capture_on_commit_callbacks(execute=True):
        login("FR")
    assert not OutboxEvent.objects.filter(event_type="security.alert").exists()


@override_settings(
    GEOIP_COUNTRY_HEADER="", GEOIP_LOOKUP="tutortrack.identity.tests.test_g6_security.FakeLookup"
)
def test_optional_geoip_lookup_is_used_without_the_header(person):
    from tutortrack.identity.travel import _lookup

    _lookup.cache_clear()
    try:
        login("GB")
        assert LoginEvent.objects.get(user=person).country == "NZ"
    finally:
        _lookup.cache_clear()


class FakeLookup:
    def country(self, ip: str) -> str:
        return "nz"


# --- account deletion ----------------------------------------------------------------------------


def test_preview_lists_organisations_and_blocks_the_last_owner(org, owner):
    client = APIClient(HTTP_HOST=HOST)
    client.force_login(owner)
    body = client.get("/api/v1/me/account-deletion").json()
    assert [o["name"] for o in body["organisations"]] == [org.name]
    assert body["blockers"][0]["reason"] == "last_owner"
    refused = client.post("/api/v1/me/account-deletion", {"password": TEST_PASSWORD}, format="json")
    assert refused.status_code == 422
    assert refused.json()["type"].endswith("account-deletion-blocked")
    assert User.objects.get(pk=owner.pk).is_active


def test_a_wrong_password_deletes_nothing(person):
    client = APIClient(HTTP_HOST=HOST)
    client.force_login(person)
    response = client.post("/api/v1/me/account-deletion", {"password": "wrong"}, format="json")
    assert response.status_code == 422
    assert "password" in response.json()["errors"]
    assert User.objects.get(pk=person.pk).email == "sam@example.com"


def test_deleting_an_account_erases_it_in_every_organisation(
    org, other_org, person, django_capture_on_commit_callbacks
):
    # The same person is also a parent in another organisation, which reviews requests.
    MembershipFactory(organisation=other_org, role="client", user=person)
    with tenant_context(other_org):
        settings_service.update_settings("privacy", {"privacy.account_deletion": "review"})
        family = ClientFactory(organisation=other_org)
        ContactFactory(organisation=other_org, client=family, first_name="Sam", user=person)
    login("GB")
    MFADevice.objects.create(user=person, name="Phone", secret="x", confirmed_at=now())
    client = APIClient(HTTP_HOST=HOST)
    client.force_login(person)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/v1/me/account-deletion",
            {"password": TEST_PASSWORD, "reason": "Leaving"},
            format="json",
        )
    assert response.status_code == 200, response.json()
    outcomes = {o["organisation_id"]: o for o in response.json()["organisations"]}
    assert outcomes[str(org.pk)]["outcome"] == "erased"
    assert outcomes[str(other_org.pk)]["outcome"] == "request_logged"
    assert outcomes[str(other_org.pk)]["reference"].startswith("DSAR-")
    # The login is anonymised; everything that signs in is gone.
    user = User.objects.get(pk=person.pk)
    assert user.email.endswith("@deleted.invalid")
    assert not user.is_active
    assert (user.first_name, user.last_name) == ("", "")
    assert not user.has_usable_password()
    assert not LoginEvent.objects.filter(user=person).exists()
    assert not MFADevice.objects.filter(user=person).exists()
    assert not UserSession.objects.filter(user=person).exists()
    deletion = AccountDeletion.objects.get()
    assert deletion.email_hash == account_deletion.email_hash("sam@example.com")
    assert deletion.completed_at is not None
    with tenant_context(org):
        membership = Membership.objects.get(user=person)
        assert membership.status == "removed"
        erasure = ErasureRecord.objects.get(subject_id=str(person.pk))
        assert (erasure.reason, erasure.status) == ("account", "completed")
        assert AuditEntry.objects.filter(action="account_deleted").exists()
    with tenant_context(other_org):
        request = DataSubjectRequest.objects.get()
        assert (request.kind, request.subject_type) == ("erasure", "identity.user")
        assert Membership.objects.get(user=person).status == "removed"
    assert OutboxEvent.objects.filter(
        event_type="user.account_deleted", organisation_id__isnull=True
    ).exists()
    # Signed out, and the old password no longer works.
    assert client.get("/api/v1/me").status_code in (401, 403)
    old = APIClient(HTTP_HOST=HOST).post(
        "/api/v1/auth/login", {"email": "sam@example.com", "password": TEST_PASSWORD}, format="json"
    )
    assert old.status_code in (400, 401)


def test_a_legal_hold_turns_the_erasure_into_a_request(org, person):
    with tenant_context(org):
        LegalHold.objects.create(
            subject_type="identity.user",
            subject_id=str(person.pk),
            reason="Dispute",
            placed_at=now(),
        )
    record = account_deletion.delete_account(person, password=TEST_PASSWORD)
    assert record.organisations[0]["outcome"] == "request_logged"
    with tenant_context(org):
        assert DataSubjectRequest.objects.filter(kind="erasure").exists()


def test_platform_staff_cannot_delete_their_account_here(org):
    staff = UserFactory(is_platform_staff=True)
    assert account_deletion.blockers(staff)[0].reason == "platform_staff"


def test_a_co_owner_can_delete_their_account(org, owner):
    second = MembershipFactory(organisation=org, role="owner").user
    assert account_deletion.blockers(second) == []
    account_deletion.delete_account(second, password=TEST_PASSWORD)
    with tenant_context(org):
        assert Membership.objects.get(user=second).status == "removed"
        assert Membership.objects.get(user=owner).status == "active"
