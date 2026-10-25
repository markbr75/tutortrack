"""E33-T03: the built-in workflow framework: install for new and existing organisations,
default upgrades, edited tracking, reset to default, switching off safely, permissions and
plans."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from tutortrack.automations import builtin_workflows, services
from tutortrack.automations.builtin_workflows import BuiltinWorkflow
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation, UpgradeRequired
from tutortrack.core.models import AuditEntry
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import MembershipFactory, UserFactory
from tutortrack.people.tests.factories import ClientFactory
from tutortrack.tenancy.tests.factories import OrganisationFactory

pytestmark = pytest.mark.django_db

TASK = {"type": "action", "action": "create_task",
        "config": {"title": "Welcome call with {{ client.name }}", "due_in_hours": 24}}  # fmt: skip
NOTE = {"type": "action", "action": "create_task", "config": {"title": "Second task"}}


def welcome() -> dict:
    return {"trigger_type": "event", "trigger_config": {"event": "client.created"},
            "steps": [TASK]}  # fmt: skip


def follow_up() -> dict:
    return {"trigger_type": "event", "trigger_config": {"event": "enquiry.received"},
            "steps": [TASK | {"config": {"title": "Call {{ enquiry.client.name }}"}}]}  # fmt: skip


WELCOME = BuiltinWorkflow(
    key="test_welcome", group="sales", name="Welcome a new family",
    description="A welcome call for every new family.", version=1, default=welcome,
    off_means="New families aren't welcomed automatically.",
)  # fmt: skip
FOLLOW_UP = BuiltinWorkflow(
    key="test_follow_up", group="sales", name="Enquiry follow-up",
    description="Call every new enquiry.", version=1, default=follow_up, can_switch_off=False,
)  # fmt: skip


@pytest.fixture
def shipped():
    """Only these two built-ins are shipped during the test."""
    before = builtin_workflows.all_builtins()
    for b in before:
        builtin_workflows.unregister(b.key)
    for b in (WELCOME, FOLLOW_UP):
        builtin_workflows.register(b)
    yield
    for b in builtin_workflows.all_builtins():
        builtin_workflows.unregister(b.key)
    for b in before:
        builtin_workflows.register(b)


def ship(builtin: BuiltinWorkflow) -> None:
    builtin_workflows.register(builtin)


def installed(org, key="test_welcome") -> Automation:
    with tenant_context(org):
        return Automation.objects.get(builtin_key=key)


def install(org) -> dict:
    with tenant_context(org):
        return services.install_builtins()


def api_as(org, role):
    return client_for(org, MembershipFactory(organisation=org, role=role).user)


# --- install --------------------------------------------------------------------------------


def test_builtins_install_once_switched_on_and_unedited(tenant, shipped):
    org = tenant
    assert install(org) == {"installed": 2, "upgraded": 0}
    welcome_wf = installed(org)
    assert (welcome_wf.kind, welcome_wf.builtin_version, welcome_wf.edited) == ("builtin", 1, False)
    assert welcome_wf.enabled
    assert welcome_wf.name == "Welcome a new family"
    assert welcome_wf.subject_type == "client"
    assert welcome_wf.steps == [TASK]
    assert welcome_wf.versions.count() == 1
    assert install(org) == {"installed": 0, "upgraded": 0}  # idempotent


def test_new_organisations_get_the_builtins(shipped):
    from tutortrack.tenancy.services import create_organisation

    result = create_organisation(name="Fresh Tutors", owner=UserFactory())
    org = getattr(result, "organisation", result)
    dispatch_batch()
    with tenant_context(org):
        keys = set(Automation.objects.filter(kind="builtin").values_list("builtin_key", flat=True))
    assert keys == {"test_welcome", "test_follow_up"}


def test_existing_organisations_get_them_from_the_sync_command(org, other_org, shipped):
    call_command("sync_builtin_workflows")
    for o in (org, other_org):
        with tenant_context(o):
            assert Automation.objects.filter(kind="builtin").count() == 2
    call_command("sync_builtin_workflows", organisation=org.slug)  # nothing new


def test_the_first_version_comes_from_the_organisations_settings(org, shipped):
    def from_settings() -> dict:
        return welcome() | {"steps": [TASK | {"config": {"title": "Ring them", "due_in_hours": 2}}]}

    ship(WELCOME.__class__(**{**WELCOME.__dict__, "first_version": from_settings}))
    install(org)
    welcome_wf = installed(org)
    assert welcome_wf.steps[0]["config"]["title"] == "Ring them"
    assert welcome_wf.edited  # differs from the default, so upgrades won't overwrite it


# --- upgrades and edits ---------------------------------------------------------------------


def test_unedited_builtins_move_to_a_newer_default_and_edited_ones_are_told(
    org, other_org, shipped
):
    install(org)
    install(other_org)
    with tenant_context(other_org):
        services.update_automation(installed(other_org), steps=[TASK, NOTE])
    improved = {**WELCOME.__dict__, "version": 2,
                "default": lambda: welcome() | {"steps": [TASK, TASK]}}  # fmt: skip
    ship(BuiltinWorkflow(**improved))

    assert install(org) == {"installed": 0, "upgraded": 1}
    upgraded = installed(org)
    assert (upgraded.builtin_version, upgraded.version, upgraded.edited) == (2, 2, False)
    assert upgraded.steps == [TASK, TASK]
    with tenant_context(org):
        assert AuditEntry.objects.filter(object_id=str(upgraded.pk), action="upgrade").exists()
        assert services.builtin_notices() == []

    assert install(other_org) == {"installed": 0, "upgraded": 0}
    kept = installed(other_org)
    assert kept.steps == [TASK, NOTE]
    assert kept.builtin_version == 1
    with tenant_context(other_org):
        assert services.update_available(kept)
        assert [n["notice"] for n in services.builtin_notices()] == ["update"]


def test_editing_marks_it_edited_and_matching_the_default_again_clears_it(tenant, shipped):
    services.install_builtins()
    welcome_wf = services.update_automation(
        installed(tenant), steps=[TASK, NOTE], name="Renamed", description=""
    )
    assert welcome_wf.edited
    assert welcome_wf.version == 2
    assert welcome_wf.name == "Welcome a new family"  # a built-in keeps its name
    assert welcome_wf.description == "A welcome call for every new family."
    welcome_wf = services.update_automation(welcome_wf, steps=[TASK])
    assert not welcome_wf.edited
    assert welcome_wf.version == 3
    enabled_only = services.set_enabled(welcome_wf, False)
    assert not enabled_only.edited
    assert enabled_only.version == 3


def test_a_builtin_keeps_its_kind_of_record(tenant, shipped):
    services.install_builtins()
    with pytest.raises(BusinessRuleViolation) as exc:
        services.update_automation(
            installed(tenant), trigger_config={"event": "enquiry.received"}, steps=[TASK]
        )
    assert "kind of record" in str(exc.value.detail)


# --- reset ------------------------------------------------------------------------------------


def test_reset_to_default_makes_a_new_version_and_runs_keep_theirs(tenant, shipped):
    services.install_builtins()
    edited = services.update_automation(installed(tenant), steps=[TASK, NOTE])
    client = ClientFactory(organisation=tenant)
    run = AutomationRun.objects.create(
        automation=edited, version=edited.versions.get(version=2), subject_type="client",
        subject_id=str(client.pk), run_key="r1", status="waiting",
    )  # fmt: skip

    reset = services.reset_to_default(edited)
    assert (reset.steps, reset.edited) == ([TASK], False)
    assert (reset.version, reset.builtin_version) == (3, 1)
    run.refresh_from_db()
    assert run.version.version == 2  # runs under way finish on the steps they started with
    assert AuditEntry.objects.filter(object_id=str(reset.pk), action="reset").exists()


def test_custom_workflows_have_no_default(tenant, shipped):
    custom = services.create_automation(
        name="Mine", trigger_type="event", trigger_config={"event": "client.created"},
        steps=[TASK],
    )  # fmt: skip
    with pytest.raises(BusinessRuleViolation):
        services.reset_to_default(custom)


def test_a_builtin_tutortrack_stopped_shipping_cant_be_reset(tenant, shipped):
    services.install_builtins()
    builtin_workflows.unregister("test_welcome")
    with pytest.raises(BusinessRuleViolation):
        services.reset_to_default(installed(tenant))


# --- switching off and deleting -------------------------------------------------------------


def test_switching_off_falls_back_and_home_says_so(tenant, shipped):
    services.install_builtins()
    services.set_enabled(installed(tenant), False)
    assert services.builtin_notices() == [{
        "id": installed(tenant).pk, "name": "Welcome a new family", "notice": "off",
        "message": "New families aren't welcomed automatically.",
    }]  # fmt: skip


def test_some_builtins_cant_be_switched_off(tenant, shipped):
    services.install_builtins()
    follow = installed(tenant, "test_follow_up")
    with pytest.raises(BusinessRuleViolation):
        services.set_enabled(follow, False)
    assert services.pause(follow).paused  # pausing is still possible


def test_builtins_cant_be_deleted(org, api, shipped):
    install(org)
    welcome_wf = installed(org)
    response = api.delete(f"/api/v1/automations/{welcome_wf.pk}")
    assert response.status_code == 422, response.content
    with tenant_context(org):
        assert Automation.objects.filter(pk=welcome_wf.pk).exists()


# --- authority, permissions and plans -------------------------------------------------------


def test_unedited_builtins_run_with_the_platforms_authority(tenant, shipped):
    services.install_builtins()
    welcome_wf = installed(tenant)
    assert services._authorised(welcome_wf, None, "growth.review.manage")
    welcome_wf.edited = True
    assert not services._authorised(welcome_wf, None, "growth.review.manage")
    coordinator = MembershipFactory(organisation=tenant, role="coordinator").user
    assert services._authorised(welcome_wf, coordinator, "growth.review.manage")
    assert not services._authorised(welcome_wf, coordinator, "billing.charge.create")


def test_finance_edits_builtins_only_with_the_actions_they_may_use(org, shipped):
    install(org)
    finance = api_as(org, "finance")
    welcome_wf = installed(org)
    charge = {"type": "action", "action": "create_charge",
              "config": {"description": "Welcome pack", "amount": 10}}  # fmt: skip
    ok = finance.patch(f"/api/v1/automations/{welcome_wf.pk}", {"steps": [TASK, charge]})
    assert ok.status_code == 200, ok.content
    assert ok.json()["edited"] is True

    follow = installed(org, "test_follow_up")
    assign = {"type": "action", "action": "assign_owner", "config": {"assignee": "owner"}}
    denied = finance.patch(f"/api/v1/automations/{follow.pk}", {"steps": [TASK, assign]})
    assert denied.status_code == 403
    reset = finance.post(f"/api/v1/automations/{welcome_wf.pk}/reset-to-default")
    assert reset.status_code == 200, reset.content
    assert reset.json()["edited"] is False

    custom = finance.post("/api/v1/automations", {
        "name": "Mine", "trigger_type": "event", "trigger_config": {"event": "client.created"},
        "steps": [TASK],
    }, format="json")  # fmt: skip
    assert custom.status_code == 403  # custom workflows need automation.manage


def test_staff_without_workflow_rights_cant_change_builtins(org, shipped):
    install(org)
    coordinator = api_as(org, "coordinator")
    welcome_wf = installed(org)
    assert coordinator.post(f"/api/v1/automations/{welcome_wf.pk}/disable").status_code == 403


def test_custom_workflows_follow_the_plan_and_builtins_dont_count(tenant, shipped, monkeypatch):
    def limit(key, organisation_id=None):
        return 1 if key == "automation_rules" else None

    monkeypatch.setattr(entitlements, "limit", limit)
    services.install_builtins()  # built-ins are on every plan
    services.create_automation(
        name="One", trigger_type="event", trigger_config={"event": "client.created"}, steps=[TASK]
    )
    with pytest.raises(UpgradeRequired):
        services.create_automation(
            name="Two", trigger_type="event", trigger_config={"event": "client.created"},
            steps=[TASK],
        )  # fmt: skip


# --- API --------------------------------------------------------------------------------------


def test_the_api_lists_builtins_with_their_default_and_notices(org, api, shipped):
    install(org)
    with tenant_context(org):
        services.update_automation(installed(org), steps=[TASK, NOTE])
    rows = api.get("/api/v1/automations", {"kind": "builtin"}).json()
    by_key = {r["builtin_key"]: r for r in rows}
    assert set(by_key) == {"test_welcome", "test_follow_up"}
    row = by_key["test_welcome"]
    assert (row["kind"], row["edited"], row["runs_under_way"]) == ("builtin", True, 0)
    assert row["builtin"] == {
        "group": "sales", "group_label": "Sales and onboarding", "latest_version": 1,
        "update_available": False, "can_switch_off": True,
        "off_means": "New families aren't welcomed automatically.",
    }  # fmt: skip
    assert by_key["test_follow_up"]["builtin"]["can_switch_off"] is False
    assert api.get("/api/v1/automations", {"kind": "custom"}).json() == []

    default = api.get(f"/api/v1/automations/{row['id']}/default").json()
    assert (default["version"], default["steps"]) == (1, [TASK])

    api.post(f"/api/v1/automations/{row['id']}/disable")
    notices = api.get("/api/v1/automations/notices").json()
    assert [(n["name"], n["notice"]) for n in notices] == [("Welcome a new family", "off")]


def test_every_shipped_builtin_is_a_valid_workflow():
    """Each organisation installs these from code, so a broken default must fail here."""
    org = OrganisationFactory()
    with tenant_context(org):
        for builtin in builtin_workflows.all_builtins():
            definition = builtin.definition()
            services.validate_definition(
                trigger_type=definition["trigger_type"],
                trigger_config=definition["trigger_config"],
                conditions_=definition["conditions"], steps=definition["steps"],
                stop_when=definition["stop_when"],
            )  # fmt: skip
            assert builtin.group in builtin_workflows.GROUPS
