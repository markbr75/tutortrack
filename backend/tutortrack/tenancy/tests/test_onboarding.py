"""E02-T07: onboarding wizard backend (FR-02-6)."""

from __future__ import annotations

import pytest

from tutortrack.core import flags
from tutortrack.core.context import tenant_context
from tutortrack.core.models import FeatureFlag, OutboxEvent
from tutortrack.core.testing import client_for
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.tenancy import services, settings_service
from tutortrack.tenancy.models import Branch, OrganisationSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return UserFactory()


@pytest.fixture
def new_org(owner):
    """An organisation fresh from signup (sole trader)."""
    from tutortrack.tenancy.signup import sign_up

    return sign_up(user=owner, business_name="Sam Tutoring", country="GB").organisation


@pytest.fixture
def api(new_org, owner):
    return client_for(new_org, owner)


def step(api, name, payload=None, **extra):
    return api.post(f"/api/v1/onboarding/{name}", payload or extra, format="json")


def statuses(body):
    return {s["key"]: s["status"] for s in body["steps"]}


def test_initial_state_for_a_sole_trader(api):
    body = api.get("/api/v1/onboarding/state").json()
    assert body["current_step"] == "business"
    assert body["completed_at"] is None
    # Inviting tutors only applies to teams and agencies.
    assert list(statuses(body)) == [
        "business", "locale", "branding", "service", "students", "payments", "invoicing",
    ]  # fmt: skip
    assert set(statuses(body).values()) == {"pending"}


def test_business_step_sets_mode_and_feature_defaults(api, new_org):
    FeatureFlag.objects.create(key="multi_branch", enabled_globally=False)
    body = step(api, "business", business_type="agency", team_size="6-20").json()
    new_org.refresh_from_db()
    assert (new_org.business_type, new_org.mode) == ("agency", "multi")
    assert flags.is_enabled("multi_branch", new_org.pk)
    assert "tutors" in statuses(body)
    assert body["current_step"] == "locale"
    assert body["answers"]["business"] == {"business_type": "agency", "team_size": "6-20"}


def test_locale_step_updates_the_organisation(api, new_org):
    body = step(
        api, "locale", locale="en-US", default_currency="usd", timezone="America/Chicago"
    ).json()
    new_org.refresh_from_db()
    assert (new_org.locale, new_org.default_currency, new_org.timezone) == (
        "en-US", "USD", "America/Chicago",
    )  # fmt: skip
    assert statuses(body)["locale"] == "completed"


GBP = {"locale": "en-GB", "default_currency": "GBP"}
MATHS = {"subject": "Maths", "duration_minutes": 60, "price": {"amount": "40", "currency": "GBP"}}


@pytest.mark.parametrize(
    ("name", "payload", "field"),
    [
        ("locale", {**GBP, "timezone": "Nowhere"}, "timezone"),
        ("locale", {**GBP, "default_currency": "XXX1", "timezone": "UTC"}, "default_currency"),
        ("branding", {"primary_colour": "red"}, "primary_colour"),
        ("service", {**MATHS, "price": {"amount": "0", "currency": "GBP"}}, "price"),
        ("service", {**MATHS, "duration_minutes": 1}, "duration_minutes"),
        ("invoicing", {"invoicing_style": "barter"}, "invoicing_style"),
    ],
)
def test_invalid_step_payloads(api, name, payload, field):
    response = step(api, name, payload)
    assert response.status_code == 400
    assert field in response.json()["errors"]


def test_branding_logo_must_be_an_uploaded_file(api):
    import uuid

    response = step(api, "branding", logo=str(uuid.uuid4()))
    assert response.status_code == 422


def test_service_step_is_recorded_and_announced(api, new_org):
    payload = {
        "subject": "Maths",
        "level": "GCSE",
        "duration_minutes": 60,
        "price": {"amount": "40.00", "currency": "GBP"},
    }
    body = step(api, "service", payload).json()
    assert body["answers"]["service"] == payload
    event = OutboxEvent.objects.filter(event_type="onboarding.step_completed").latest("occurred_at")
    assert event.organisation_id == new_org.pk
    assert event.payload["data"] == {"step": "service", "skipped": False, "answers": payload}


def test_invoicing_step_sets_the_billing_setting(api, new_org):
    step(api, "invoicing", invoicing_style="monthly_advance")
    with tenant_context(new_org):
        assert settings_service.get_setting("billing.invoicing_style") == "monthly_advance"


def test_steps_can_be_skipped_and_revisited(api):
    body = step(api, "business", skip=True).json()
    assert statuses(body)["business"] == "skipped"
    assert body["current_step"] == "locale"
    body = step(api, "business", business_type="sole_trader").json()
    assert statuses(body)["business"] == "completed"


def test_tutors_step_only_applies_to_teams(api, new_org):
    response = step(api, "tutors", emails=["a@example.com"])
    assert response.status_code == 422
    services.update_organisation(new_org, business_type="team")
    assert step(api, "tutors", emails=["a@example.com"]).status_code == 200


def test_completing_the_wizard(api, new_org, owner):
    """AC: completing the wizard leaves the org, default branch, owner membership and
    settings in place and announces the outcome (service and trial come from E06/E04
    handlers of the onboarding/organisation events)."""
    step(api, "business", business_type="sole_trader")
    body = api.post("/api/v1/onboarding/complete").json()
    assert body["completed_at"] is not None
    assert body["current_step"] == ""
    assert statuses(body)["business"] == "completed"
    assert statuses(body)["invoicing"] == "skipped"

    with tenant_context(new_org):
        assert Branch.objects.filter(is_default=True).exists()
        assert Membership.objects.get(user=owner).role == Membership.Role.OWNER
        assert OrganisationSettings.objects.exists()
    types = set(
        OutboxEvent.objects.filter(organisation_id=new_org.pk).values_list("event_type", flat=True)
    )
    assert {"organisation.created", "onboarding.step_completed", "onboarding.completed"} <= types

    assert step(api, "locale", skip=True).status_code == 422  # finished
    assert api.post("/api/v1/onboarding/complete").status_code == 200  # idempotent


def test_unknown_step_is_404(api):
    assert step(api, "dance").status_code == 404


def test_only_managers_can_change_onboarding(new_org):
    tutor = MembershipFactory(organisation=new_org, role=Membership.Role.TUTOR).user
    assert step(client_for(new_org, tutor), "business", skip=True).status_code == 403


def test_onboarding_state_is_per_organisation(new_org, org, superuser):
    step(client_for(new_org, superuser), "business", skip=True)
    other = client_for(org, superuser).get("/api/v1/onboarding/state").json()
    assert set(statuses(other).values()) == {"pending"}
