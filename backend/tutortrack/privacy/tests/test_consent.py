"""E29-T04: consent types and records (FR-29-3)."""

from __future__ import annotations

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.privacy import services
from tutortrack.privacy.models import ConsentRecord, ConsentType

pytestmark = pytest.mark.django_db


@pytest.fixture
def consent_types(org):
    with tenant_context(org):
        services.ensure_default_types()
    return org


@pytest.fixture
def parent(org):
    return MembershipFactory(organisation=org, role="client").user


def status(api, **params):
    return {s["key"]: s for s in api.get("/api/v1/consents/status", params).json()}


def test_new_organisations_get_default_consent_types():
    from tutortrack.tenancy.services import create_organisation

    org = create_organisation(name="Fresh Tutors", owner=None)
    dispatch_batch()
    with tenant_context(org):
        keys = set(ConsentType.objects.values_list("key", flat=True))
    assert {"terms", "privacy-policy", "marketing-email", "photo-video"} <= keys


def test_people_give_and_withdraw_their_own_consent(org, consent_types, parent):
    api = client_for(org, parent)
    initial = {s["key"]: s for s in api.get("/api/v1/me/consents").json()}
    assert initial["marketing-email"]["granted"] is None
    assert initial["terms"]["needs_reconsent"] is True  # required and never given
    assert "photo-video" not in initial  # applies to students only

    granted = api.post(
        "/api/v1/me/consents", {"consent_type": "marketing-email", "granted": True}, format="json"
    )
    assert {s["key"]: s for s in granted.json()}["marketing-email"]["granted"] is True
    withdrawn = api.post(
        "/api/v1/me/consents", {"consent_type": "marketing-email", "granted": False}, format="json"
    )
    assert {s["key"]: s for s in withdrawn.json()}["marketing-email"]["granted"] is False

    with tenant_context(org):
        history = list(
            ConsentRecord.objects.filter(subject_id=str(parent.pk)).values_list("granted", "method")
        )
    assert history == [(False, "portal"), (True, "portal")]  # newest first, nothing overwritten
    types = list(OutboxEvent.objects.values_list("event_type", flat=True))
    assert {"consent.granted", "consent.withdrawn"} <= set(types)
    withdrawn_event = OutboxEvent.objects.get(event_type="consent.withdrawn")
    assert withdrawn_event.payload["data"]["category"] == "marketing_email"


def test_new_versions_require_reconsent(org, consent_types, parent):
    with tenant_context(org):
        services.record_consent(
            subject_type="identity.user", subject_id=str(parent.pk), key="privacy-policy",
            granted=True, method="portal", given_by=parent,
        )  # fmt: skip
        assert services.is_granted("identity.user", str(parent.pk), "privacy-policy")
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    ct_id = admin.get("/api/v1/consent-types").json()["results"]
    privacy = next(c for c in ct_id if c["key"] == "privacy-policy")
    bumped = admin.post(f"/api/v1/consent-types/{privacy['id']}/new-version")
    assert bumped.json()["version"] == 2
    with tenant_context(org):
        assert not services.is_granted("identity.user", str(parent.pk), "privacy-policy")
    row = status(admin, subject_type="identity.user", subject_id=str(parent.pk))["privacy-policy"]
    assert (row["version"], row["current_version"], row["needs_reconsent"]) == (1, 2, True)


def test_staff_record_consent_on_behalf_with_evidence(org, consent_types, parent):
    coordinator = MembershipFactory(organisation=org, role="coordinator").user
    api = client_for(org, coordinator)
    response = api.post(
        "/api/v1/consents",
        {"subject_type": "identity.user", "subject_id": str(parent.pk),
         "consent_type": "marketing-sms", "granted": True, "given_by_name": "Paper form 12/09"},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["method"], body["given_by"], body["given_by_name"]) == (
        "staff", str(coordinator.pk), "Paper form 12/09",
    )  # fmt: skip
    listed = api.get("/api/v1/consents", {"subject_id": str(parent.pk)}).json()["results"]
    assert [r["consent_type"] for r in listed] == ["marketing-sms"]


def test_validation(org, consent_types, parent):
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    base = {"subject_type": "identity.user", "subject_id": str(parent.pk), "granted": True}
    assert (
        admin.post("/api/v1/consents", {**base, "consent_type": "nope"}, format="json").status_code
        == 404
    )
    # photo-video applies to students, not users.
    assert (
        admin.post(
            "/api/v1/consents", {**base, "consent_type": "photo-video"}, format="json"
        ).status_code
        == 422
    )
    # Someone who is not in this organisation.
    stranger = {**base, "subject_id": str(UserFactory().pk), "consent_type": "terms"}
    assert admin.post("/api/v1/consents", stranger, format="json").status_code == 404


def test_permissions(org, consent_types, parent):
    tutor = client_for(org, MembershipFactory(organisation=org, role="tutor").user)
    assert tutor.get("/api/v1/consents").status_code == 403
    coordinator = client_for(org, MembershipFactory(organisation=org, role="coordinator").user)
    assert (
        coordinator.post(
            "/api/v1/consent-types", {"key": "x", "name": "X", "category": "other"}, format="json"
        ).status_code
        == 403
    )
    admin = client_for(org, MembershipFactory(organisation=org, role="admin").user)
    created = admin.post(
        "/api/v1/consent-types",
        {"key": "newsletter", "name": "Newsletter", "category": "marketing_email"},
        format="json",
    )
    assert created.status_code == 201


class TestConsentTypeIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/consent-types"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return ConsentType.objects.create(key="k", name="K", category="other")


class TestConsentRecordIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/consents"

    def make_object(self, organisation):
        user = MembershipFactory(organisation=organisation).user
        with tenant_context(organisation):
            services.ensure_default_types()
            return services.record_consent(
                subject_type="identity.user", subject_id=str(user.pk), key="terms",
                granted=True, method="staff",
            )  # fmt: skip

    def test_detail_of_other_organisation_is_404(self, org, other_org):  # no detail route
        pytest.skip("consent records are listed per subject, not fetched by id")
