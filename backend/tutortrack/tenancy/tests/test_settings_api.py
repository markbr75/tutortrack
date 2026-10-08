"""E02-T05: settings registry, organisation/branch settings, org profile and branch APIs."""

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import FeatureFlag, OutboxEvent
from tutortrack.core.testing import TenantIsolationTestMixin, client_for, result_ids
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.tenancy import settings_service
from tutortrack.tenancy.models import Branch, Organisation, OrganisationDomain
from tutortrack.tenancy.settings_registry import SettingsRegistry, registry
from tutortrack.tenancy.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db


def member_api(org, role=Membership.Role.ADMIN):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


@pytest.fixture
def north(org):
    return BranchFactory(organisation=org, code="N", name="North")


# --- registry -------------------------------------------------------------------------------------


def test_registry_rejects_bad_definitions():
    reg = SettingsRegistry()
    with pytest.raises(ValueError, match="area"):
        reg.register("nodot", type="int", default=1)
    with pytest.raises(ValueError, match="type"):
        reg.register("x.y", type="float", default=1.0)
    with pytest.raises(Exception, match="greater than or equal"):
        reg.register("x.z", type="int", default=0, min_value=1)  # invalid default
    reg.register("x.a", type="int", default=1)
    with pytest.raises(ValueError, match="already registered"):
        reg.register("x.a", type="int", default=2)


def test_general_and_billing_areas_are_registered():
    assert {"general", "billing"} <= set(registry.areas())
    keys = [d.key for d in registry.area("general")]
    assert keys == [
        "general.business_hours",
        "general.default_lesson_duration",
        "general.terminology",
    ]


# --- service --------------------------------------------------------------------------------------


def test_resolution_is_branch_then_org_then_default(tenant, north):
    key = "general.default_lesson_duration"
    assert settings_service.get_setting(key) == 60
    settings_service.update_settings("general", {key: 45})
    assert settings_service.get_setting(key) == 45
    assert settings_service.get_setting(key, branch=north) == 45
    settings_service.update_settings("general", {key: 90}, branch=north)
    assert settings_service.get_setting(key, branch=north) == 90
    assert settings_service.get_setting(key) == 45
    settings_service.update_settings("general", {key: None}, branch=north)
    assert settings_service.get_setting(key, branch=north) == 45
    settings_service.update_settings("general", {key: None})
    assert settings_service.get_setting(key) == 60


def test_updates_publish_settings_updated(tenant):
    settings_service.update_settings("billing", {"billing.invoicing_style": "packages"})
    event = OutboxEvent.objects.get(event_type="organisation.settings_updated")
    assert event.payload["data"] == {
        "area": "billing",
        "branch_id": None,
        "keys": ["billing.invoicing_style"],
    }
    # No change, no event.
    settings_service.update_settings("billing", {"billing.invoicing_style": "packages"})
    assert OutboxEvent.objects.filter(event_type="organisation.settings_updated").count() == 1


def test_settings_are_per_organisation(org, other_org):
    with tenant_context(org):
        settings_service.update_settings("general", {"general.default_lesson_duration": 30})
    with tenant_context(other_org):
        assert settings_service.get_setting("general.default_lesson_duration") == 60


# --- settings API ---------------------------------------------------------------------------------


def test_get_area_returns_values_and_schema(org):
    response = member_api(org).get("/api/v1/settings/general")
    assert response.status_code == 200
    body = response.json()
    assert body["area"] == "general"
    assert body["values"]["general.default_lesson_duration"] == 60
    assert body["values"]["general.terminology"]["tutor"] == {
        "singular": "Tutor",
        "plural": "Tutors",
    }
    schema = {s["key"]: s for s in body["schema"]}
    assert schema["general.default_lesson_duration"]["min_value"] == 5
    assert schema["general.business_hours"]["scope"] == "branch"


def test_terminology_override(org):
    api = member_api(org)
    response = api.patch(
        "/api/v1/settings/general",
        {
            "values": {
                "general.terminology": {"tutor": {"singular": "Teacher", "plural": "Teachers"}}
            }
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    terms = response.json()["values"]["general.terminology"]
    assert terms["tutor"] == {"singular": "Teacher", "plural": "Teachers"}
    assert terms["client"] == {"singular": "Client", "plural": "Clients"}  # defaults kept


DURATION, TERMS, HOURS = (
    "general.default_lesson_duration",
    "general.terminology",
    "general.business_hours",
)
OVERLAP = [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}]


@pytest.mark.parametrize(
    ("values", "bad_key"),
    [
        ({DURATION: 2}, DURATION),
        ({DURATION: "abc"}, DURATION),
        ({"general.nope": 1}, "general.nope"),
        ({TERMS: {"teacher": {}}}, TERMS),
        ({TERMS: {"tutor": {"singular": "", "plural": "x"}}}, TERMS),
        ({HOURS: {"mon": [{"start": "10:00", "end": "09:00"}]}}, HOURS),
        ({HOURS: {"mon": OVERLAP}}, HOURS),
    ],
)
def test_invalid_values_are_rejected_per_key(org, values, bad_key):
    response = member_api(org).patch("/api/v1/settings/general", {"values": values}, format="json")
    assert response.status_code == 400
    assert bad_key in response.json()["errors"]


def test_branch_overrides_via_api(org, north):
    api = member_api(org)
    url = f"/api/v1/settings/general?branch={north.pk}"
    response = api.patch(url, {"values": {"general.default_lesson_duration": 30}}, format="json")
    assert response.status_code == 200
    assert response.json()["overrides"] == ["general.default_lesson_duration"]
    assert response.json()["values"]["general.default_lesson_duration"] == 30
    assert (
        api.get("/api/v1/settings/general").json()["values"]["general.default_lesson_duration"]
        == 60
    )

    org_only = api.patch(
        url, {"values": {"general.terminology": {}}}, format="json"
    )  # organisation-scope setting
    assert org_only.status_code == 400


def test_unknown_area_and_foreign_branch_are_404(org, other_org):
    api = member_api(org)
    assert api.get("/api/v1/settings/nope").status_code == 404
    foreign = BranchFactory(organisation=other_org, code="X")
    assert api.get(f"/api/v1/settings/general?branch={foreign.pk}").status_code == 404
    assert api.get("/api/v1/settings/general?branch=not-a-uuid").status_code == 404


def test_settings_permissions(org):
    tutor = member_api(org, Membership.Role.TUTOR)
    assert tutor.get("/api/v1/settings/general").status_code == 403
    manager = member_api(org, Membership.Role.BRANCH_MANAGER)
    assert manager.get("/api/v1/settings/general").status_code == 200
    assert (
        manager.patch(
            "/api/v1/settings/general",
            {"values": {"general.default_lesson_duration": 30}},
            format="json",
        ).status_code
        == 403
    )


# --- organisation profile API ---------------------------------------------------------------------


def test_get_and_patch_organisation(org):
    api = member_api(org, Membership.Role.OWNER)
    body = api.get("/api/v1/organisation").json()
    assert body["slug"] == org.slug
    assert body["url"] == f"https://{org.slug}.tutortrack.test"

    response = api.patch(
        "/api/v1/organisation",
        {"legal_name": "Bright Minds Ltd", "primary_colour": "#1d4ed8", "status": "active"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    org.refresh_from_db()
    assert (org.legal_name, org.primary_colour) == ("Bright Minds Ltd", "#1d4ed8")
    assert response.json()["status"] == org.status  # read-only, ignored


def test_patch_organisation_validation(org):
    api = member_api(org)
    for payload in (
        {"timezone": "Mars/Base"},
        {"primary_colour": "blue"},
        {"address": {"street": "x"}},
        {"slug": "www"},
    ):
        response = api.patch("/api/v1/organisation", payload, format="json")
        assert response.status_code in (400, 422), payload


def test_changing_slug_via_api_redirects_old_host(org):
    api = member_api(org)
    response = api.patch("/api/v1/organisation", {"slug": "bright-two"}, format="json")
    assert response.status_code == 200
    assert OrganisationDomain.objects.filter(hostname="brightminds").exists()
    assert Organisation.objects.get(pk=org.pk).slug == "bright-two"


def test_tutors_cannot_edit_the_organisation(org):
    tutor = member_api(org, Membership.Role.TUTOR)
    assert tutor.patch("/api/v1/organisation", {"name": "x"}, format="json").status_code == 403


# --- branches API ---------------------------------------------------------------------------------


@pytest.fixture
def multi_branch():
    FeatureFlag.objects.update_or_create(key="multi_branch", defaults={"enabled_globally": True})


def test_branch_crud(org, multi_branch):
    api = member_api(org)
    created = api.post(
        "/api/v1/branches",
        {"name": "Leeds", "code": "lds", "timezone": "Europe/London"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    branch_id = created.json()["id"]
    assert created.json()["code"] == "LDS"
    assert created.json()["currency"] == org.default_currency

    patched = api.patch(f"/api/v1/branches/{branch_id}", {"name": "Leeds Central"}, format="json")
    assert patched.json()["name"] == "Leeds Central"

    archived = api.delete(f"/api/v1/branches/{branch_id}")
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert branch_id not in result_ids(api.get("/api/v1/branches"))
    assert branch_id in result_ids(api.get("/api/v1/branches?include_archived=true"))


def test_creating_branches_requires_the_feature(org):
    response = member_api(org).post(
        "/api/v1/branches", {"name": "Leeds", "code": "L"}, format="json"
    )
    assert response.status_code == 403
    assert response.json()["type"].endswith("feature-disabled")


def test_default_branch_cannot_be_archived_via_api(org):
    api = member_api(org)
    with tenant_context(org):
        default = Branch.objects.get(is_default=True)
    assert api.delete(f"/api/v1/branches/{default.pk}").status_code == 422


def test_branch_list_respects_branch_scope(org, north):
    from tutortrack.identity.services import set_branch_scope

    membership = MembershipFactory(organisation=org, role=Membership.Role.BRANCH_MANAGER)
    with tenant_context(org):
        set_branch_scope(membership, Membership.BranchScope.SELECTED, [north])
    response = client_for(org, membership.user).get("/api/v1/branches")
    assert result_ids(response) == {str(north.pk)}


def test_only_branch_managers_with_permission_can_change_branches(org, multi_branch):
    manager = member_api(org, Membership.Role.BRANCH_MANAGER)
    assert manager.get("/api/v1/branches").status_code == 200
    assert (
        manager.post("/api/v1/branches", {"name": "X", "code": "X"}, format="json").status_code
        == 403
    )


class TestBranchIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/branches"

    def make_object(self, organisation):
        return BranchFactory(organisation=organisation)
