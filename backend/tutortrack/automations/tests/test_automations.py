"""E14-T01..T08: registry, conditions, definitions and versions, guardrails, actions, dry run,
schedules and date triggers, recipes."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, timedelta

import pytest

from tutortrack.automations import actions, conditions, recipes, registry, services
from tutortrack.automations.models import Automation, AutomationRun, AutomationRunStep
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.crm.services import tags_for
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db

MESSAGE = {"type": "action", "action": "send_message", "config": {
    "to": ["client"], "channels": ["email"], "subject": "Hello {{ student.first_name }}",
    "body": "Dear {{ recipient.first_name }}, {{ student.first_name }} is {{ student.status }}.",
}}  # fmt: skip


def api_as(org, role):
    membership = MembershipFactory(organisation=org, role=role)
    return client_for(org, membership.user), membership.user


@pytest.fixture
def family(org):
    with tenant_context(org):
        client = ClientFactory(organisation=org)
        contact = ContactFactory(
            organisation=org, client=client, first_name="Priya", email="priya@example.com"
        )
        client.primary_contact = contact
        client.save()
        student = StudentFactory(organisation=org, client=client, first_name="Arjun",
                                 status="active")  # fmt: skip
    return client, student


def make(org, steps=None, *, user=None, **fields):
    with tenant_context(org):
        return services.create_automation(
            name=fields.pop("name", "Test"),
            trigger_type=fields.pop("trigger_type", "event"),
            trigger_config=fields.pop("trigger_config", {"event": "student.status_changed"}),
            steps=steps or [MESSAGE],
            user=user,
            **fields,
        )


def envelope(org, student, *, actor=None, changes=None, event_id=None):
    return EventEnvelope(
        id=event_id or uuid.uuid4(), type="student.status_changed", version=1,
        occurred_at=now(), organisation_id=org.pk, branch_id=None,
        actor=actor or {"type": "user", "id": None},
        subject={"type": "student", "id": str(student.pk)},
        data={"old_status": "active", "new_status": "paused"}, changes=changes or {},
    )  # fmt: skip


# --- T02 conditions -----------------------------------------------------------------------------


def test_condition_operators():
    ctx = {
        "student": {"status": "Active", "tags": ["VIP", "Maths"], "age": "15",
                    "last": (now() - timedelta(days=40)).isoformat(), "school": ""},
        "event": {"changes": {"status": ["active", "paused"]}},
    }  # fmt: skip
    ev = conditions.evaluate
    assert ev({"field": "student.status", "op": "equals", "value": "active"}, ctx)
    assert ev({"field": "student.status", "op": "in", "value": ["paused", "active"]}, ctx)
    assert ev({"field": "student.tags", "op": "contains", "value": "vip"}, ctx)
    assert ev({"field": "student.age", "op": "gt", "value": 14}, ctx)
    assert not ev({"field": "student.age", "op": "lte", "value": "14.5"}, ctx)
    assert ev({"field": "student.school", "op": "is_empty"}, ctx)
    assert ev({"field": "student.last", "op": "older_than_days", "value": 30}, ctx)
    assert not ev({"field": "student.last", "op": "within_last_days", "value": 30}, ctx)
    assert ev({"field": "student.status", "op": "changed_to", "value": "paused"}, ctx)
    assert ev({"field": "student.status", "op": "changed_from", "value": "active"}, ctx)
    assert not ev({"field": "student.year_group", "op": "changed"}, ctx)
    assert ev({"any": [{"field": "student.status", "op": "equals", "value": "x"},
                       {"not": {"field": "student.tags", "op": "contains", "value": "Art"}}]},
              ctx)  # fmt: skip
    assert ev({}, ctx)
    with pytest.raises(conditions.InvalidCondition):
        ev({"field": "student.status", "op": "eval"}, ctx)
    assert conditions.validate(
        {"all": [{"field": "student.secret", "op": "equals", "value": 1}]}, {"student.status"}
    ) == ["Unknown field student.secret"]


# --- T01 definitions and versions ---------------------------------------------------------------


def test_create_validates_and_versions(org):
    api, _user = api_as(org, "admin")
    bad = api.post("/api/v1/automations", {
        "name": "x", "trigger_type": "event", "trigger_config": {"event": "nothing.happened"},
        "steps": [MESSAGE],
    }, format="json")  # fmt: skip
    assert bad.status_code == 422, bad.content
    unknown_field = api.post("/api/v1/automations", {
        "name": "x", "trigger_type": "event", "trigger_config": {"event": "student.created"},
        "conditions": {"field": "student.date_of_birthday", "op": "is_empty"},
        "steps": [MESSAGE],
    }, format="json")  # fmt: skip
    assert unknown_field.status_code == 422
    missing = api.post("/api/v1/automations", {
        "name": "x", "trigger_type": "event", "trigger_config": {"event": "student.created"},
        "steps": [{"type": "action", "action": "send_message", "config": {"to": ["client"]}}],
    }, format="json")  # fmt: skip
    assert missing.status_code == 422
    response = api.post("/api/v1/automations", {
        "name": "Welcome", "trigger_type": "event", "trigger_config": {"event": "student.created"},
        "steps": [MESSAGE],
    }, format="json")  # fmt: skip
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["subject_type"], body["version"], body["enabled"]) == ("student", 1, False)
    renamed = api.patch(f"/api/v1/automations/{body['id']}", {"name": "Hi"}, format="json")
    assert renamed.json()["version"] == 1
    edited = api.patch(
        f"/api/v1/automations/{body['id']}",
        {"steps": [MESSAGE, {"type": "wait", "days": 2}]},
        format="json",
    )
    assert edited.json()["version"] == 2
    with tenant_context(org):
        assert Automation.objects.get().versions.count() == 2
    assert api.post(f"/api/v1/automations/{body['id']}/enable").json()["enabled"] is True


def test_finance_actions_need_the_authors_permission(org, family):
    _api, coordinator = api_as(org, "coordinator")
    charge = {"type": "action", "action": "create_charge",
              "config": {"description": "Materials", "amount": "12.50"}}  # fmt: skip
    with pytest.raises(PermissionDenied):
        make(org, [charge], user=coordinator, trigger_config={"event": "student.created"})
    _api, admin = api_as(org, "admin")
    automation = make(org, [charge], user=admin, trigger_config={"event": "student.created"})
    assert automation.steps[0]["action"] == "create_charge"


def test_schema_lists_triggers_subjects_and_actions(org):
    api, _user = api_as(org, "admin")
    body = api.get("/api/v1/automation-schema").json()
    assert {"event": "lesson.completed", "label": "Lesson completed", "subject": "lesson"} in body[
        "triggers"
    ]
    student = next(s for s in body["subjects"] if s["key"] == "student")
    assert "student.client.auto_pay" in [f["path"] for f in student["fields"]]
    assert "date_of_birth" in student["date_fields"]
    assert {a["key"] for a in body["actions"]} >= {"send_message", "create_task", "webhook",
                                                   "late_fee", "offer_job"}  # fmt: skip
    assert "first_lesson_for_student" in body["predicates"]


# --- T03 guardrails -----------------------------------------------------------------------------


def test_guardrails(org, family):
    _client, student = family
    automation = make(org, enabled=True, conditions_={
        "field": "student.status", "op": "changed_to", "value": "paused",
    })  # fmt: skip
    with tenant_context(org):
        sid = str(student.pk)
        no_change = envelope(org, student)
        assert (
            services.prepare_run(automation, subject_id=sid, run_key="a", event=no_change) is None
        )
        event = envelope(org, student, changes={"status": ["active", "paused"]})
        run = services.prepare_run(automation, subject_id=sid, run_key=str(event.id), event=event)
        assert run is not None
        assert run.workflow_id == f"automation:{org.pk}:{automation.pk}:{sid}:{event.id}"
        # The same event again, and a second event the same day, don't run.
        assert services.prepare_run(automation, subject_id=sid, run_key=str(event.id),
                                    event=event) is None  # fmt: skip
        again = envelope(org, student, changes={"status": ["active", "paused"]})
        assert services.prepare_run(automation, subject_id=sid, run_key=str(again.id),
                                    event=again) is None  # fmt: skip
        # Loop detection: an event written by a run three automations deep is stopped.
        AutomationRun.objects.filter(pk=run.pk).update(causation_depth=3)
        automation.max_runs_per_record = 10
        looped = envelope(org, student, changes={"status": ["active", "paused"]},
                          actor={"type": "workflow", "id": run.workflow_id})  # fmt: skip
        stopped = services.prepare_run(automation, subject_id=sid, run_key=str(looped.id),
                                       event=looped)  # fmt: skip
        assert stopped.status == "skipped"
        assert stopped.causation_depth == 4
        assert "triggering each other" in stopped.error
        # The kill switch and disabled automations.
        from tutortrack.tenancy.settings_service import update_settings

        update_settings("automations", {"automations.enabled": False})
        later = envelope(org, student, changes={"status": ["active", "paused"]})
        assert services.prepare_run(automation, subject_id=sid, run_key=str(later.id),
                                    event=later) is None  # fmt: skip


def test_on_event_starts_matching_automations(org, family, monkeypatch):
    _client, student = family
    launched = []
    monkeypatch.setattr(services, "launch", lambda run, **kw: launched.append(run))
    make(org, enabled=True)
    make(org, enabled=False, name="Off")
    make(org, enabled=True, name="Other", trigger_config={"event": "student.created"})
    with tenant_context(org):
        runs = services.on_event(envelope(org, student))
    assert [r.automation.name for r in runs] == ["Test"]
    assert launched == runs


# --- T04/T07 actions ----------------------------------------------------------------------------


def _execute(org, automation, subject, step, key="0"):
    with tenant_context(org):
        run = services.prepare_run(automation, subject_id=str(subject.pk),
                                   run_key=f"manual:{uuid.uuid4()}", manual=True)  # fmt: skip
        return run, services.execute_step(str(run.pk), key, step)


def test_send_message_renders_for_each_recipient(org, family):
    _client, student = family
    automation = make(org)
    run, result = _execute(org, automation, student, MESSAGE)
    assert result["status"] == "completed", result
    with tenant_context(org):
        message = Message.objects.get(type_key="automation_message")
        assert message.to == "priya@example.com"
        assert message.subject == "Hello Arjun"
        assert "Dear Priya, Arjun is active." in message.body
        # Idempotent per run and step: running it again sends nothing more.
        services.execute_step(str(run.pk), "0", MESSAGE)
        assert Message.objects.filter(type_key="automation_message").count() == 1
        assert AutomationRunStep.objects.get(run=run).status == "completed"


def test_task_tag_and_field_actions(org, family):
    client, student = family
    _api, owner = api_as(org, "coordinator")
    with tenant_context(org):
        client.account_manager = owner.memberships.get()
        client.save()
    automation = make(org)
    task = {"type": "action", "action": "create_task",
            "config": {"title": "Call {{ student.client.name }}", "assignee": "owner",
                       "due_in_hours": 2}}  # fmt: skip
    _run, result = _execute(org, automation, student, task)
    assert result["status"] == "completed", result
    _run, result = _execute(
        org, automation, student, {"type": "action", "action": "add_tag", "config": {"tag": "VIP"}}
    )
    status_step = {"type": "action", "action": "update_field",
                   "config": {"field": "status", "value": "paused"}}  # fmt: skip
    _run, result = _execute(org, automation, student, status_step)
    assert result["status"] == "completed", result
    _run, bad = _execute(org, automation, student, {
        "type": "action", "action": "update_field", "config": {"field": "first_name", "value": "X"},
    })  # fmt: skip
    assert bad["status"] == "failed"
    assert "can't be changed" in bad["error"]
    with tenant_context(org):
        created = Task.objects.get()
        assert created.title == f"Call {client.display_name}"
        assert created.assignee == owner
        assert created.target_type == "people.student"
        assert [t.name for t in tags_for("people.student", [str(student.pk)])[str(student.pk)]] == [
            "VIP"
        ]
        student.refresh_from_db()
        assert student.status == "paused"


def test_round_robin_assigns_the_least_busy(org, family):
    _client, student = family
    _api, busy = api_as(org, "coordinator")
    _api, free = api_as(org, "coordinator")
    with tenant_context(org):
        Task.objects.create(title="Old", assignee=busy)
        ctx = actions.RunContext(automation=None, subject=registry.subject("student"),
                                 obj=student, context={}, key="k")  # fmt: skip
        assert actions._assignee(ctx, "round_robin:coordinator") == free


def test_signed_webhook(org, family, monkeypatch):
    _client, student = family
    automation = make(org)
    seen = {}

    class Reply:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(url, *, data, headers, method, timeout):
        seen.update(url=url, data=data, headers=headers, method=method)
        return Reply()

    monkeypatch.setattr("tutortrack.core.net.safe_urlopen", fake)
    step = {"type": "action", "action": "webhook", "config": {"url": "https://hooks.example.com/x"}}
    _run, result = _execute(org, automation, student, step)
    assert result == {"status": "completed", "result": {"status": 204}}
    stamp, mac = (p.split("=", 1)[1] for p in seen["headers"]["X-TutorTrack-Signature"].split(","))
    assert mac == actions.sign(automation.webhook_secret, int(stamp), seen["data"])
    assert b'"first_name": "Arjun"' in seen["data"]


def test_late_fee_and_revoked_permission(org, family):
    client, _student = family
    _api, admin = api_as(org, "admin")
    fee = {"type": "action", "action": "late_fee", "config": {"percent": "5", "minimum": "2"}}
    automation = make(org, [fee], user=admin, trigger_config={"event": "invoice.overdue"})
    with tenant_context(org):
        from tutortrack.billing.models import Charge, Invoice

        Automation.objects.filter(pk=automation.pk).update(created_by=admin)
        invoice = Invoice.objects.create(
            client=client,
            currency="GBP",
            status="issued",
            number="INV-1",
            balance_due=Money("101.10", "GBP"),
        )
    _run, result = _execute(org, automation, invoice, fee)
    assert result["status"] == "completed", result
    with tenant_context(org):
        charge = Charge.objects.get()
        assert charge.gross == Money("5.06", "GBP")  # 5% of 101.10, rounded half-up
        assert "INV-1" in charge.description
        admin.memberships.update(role="coordinator")
    _run, refused = _execute(org, automation, invoice, fee, key="1")
    assert refused["status"] == "failed"
    assert "no longer has permission" in refused["error"]


# --- FR-14-4 dry run ----------------------------------------------------------------------------


def test_dry_run_describes_without_doing(org, family):
    _client, student = family
    automation = make(org, [
        MESSAGE,
        {"type": "wait", "days": 1},
        {"type": "branch", "if": {"field": "student.status", "op": "equals", "value": "active"},
         "then": [{"type": "action", "action": "add_tag", "config": {"tag": "Keen"}}],
         "else": []},
    ])  # fmt: skip
    api, _user = api_as(org, "admin")
    response = api.post(f"/api/v1/automations/{automation.pk}/test",
                        {"subject_id": str(student.pk)}, format="json")  # fmt: skip
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["matched"] is True
    assert [s["key"] for s in body["steps"]] == ["0", "1", "2", "2.then.0"]
    assert "Hello Arjun" in body["steps"][0]["description"]
    assert body["steps"][1]["description"] == "Wait 24 hours"
    with tenant_context(org):
        assert not Message.objects.exists()
        assert not AutomationRun.objects.exists()


def test_manual_run(org, family, monkeypatch):
    _client, student = family
    monkeypatch.setattr(services, "launch", lambda run, **kw: None)
    automation = make(org, trigger_type="manual", trigger_config={"subject": "student"})
    api, _user = api_as(org, "admin")
    response = api.post(
        f"/api/v1/automations/{automation.pk}/run",
        {"subject_ids": [str(student.pk), str(uuid.uuid4())]},
        format="json",
    )
    assert response.json() == {"started": 1}
    runs = api.get(f"/api/v1/automations/{automation.pk}/runs").json()
    assert runs[0]["subject_id"] == str(student.pk)


# --- T06 schedule and date triggers -------------------------------------------------------------


def test_date_trigger_picks_anniversaries_and_fans_out(org, family, monkeypatch):
    client, student = family
    with tenant_context(org):
        student.date_of_birth = date(2012, 10, 17)
        student.save()
        StudentFactory(organisation=org, client=client, date_of_birth=date(2013, 3, 1))
    launched = []
    monkeypatch.setattr(services, "launch", lambda run, **kw: launched.append(run))
    birthday = make(org, trigger_type="date", enabled=True, trigger_config={
        "subject": "student", "field": "date_of_birth", "offset_days": -7, "anniversary": True,
        "time": "08:00",
    })  # fmt: skip
    with tenant_context(org):
        assert services.due_records(birthday, date(2026, 10, 10)) == [str(student.pk)]
        assert services.fan_out(str(birthday.pk), date(2026, 10, 10)) == 1
        assert services.fan_out(str(birthday.pk), date(2026, 10, 10)) == 0  # once a day
    assert launched[0].run_key == "schedule:2026-10-10"
    assert services._cron({"frequency": "weekly", "weekday": 0, "time": "08:30"}) == ["30 8 * * 1"]
    assert services._cron({"frequency": "monthly", "day": 31, "time": "07:00"}) == ["0 7 28 * *"]


def test_schedule_trigger_uses_conditions_as_the_query(org, family, monkeypatch):
    _client, student = family
    launched = []
    monkeypatch.setattr(services, "launch", lambda run, **kw: launched.append(run))
    dormant = recipes.recipe("dormant_students")
    automation = make(org, list(dormant.steps), trigger_type="schedule", enabled=True,
                      trigger_config=dict(dormant.trigger_config),
                      conditions_=dict(dormant.conditions))  # fmt: skip
    with tenant_context(org):
        assert services.fan_out(str(automation.pk)) == 0  # never had a lesson
    quiet = dataclasses.replace(
        registry.subject("student"),
        context=lambda s: {"status": "active",
                           "last_lesson_at": (now() - timedelta(days=45)).isoformat()},
    )  # fmt: skip
    monkeypatch.setitem(registry._subjects, "student", quiet)
    with tenant_context(org):
        assert services.fan_out(str(automation.pk)) == 1
    assert launched[0].subject_id == str(student.pk)


# --- T08 recipes --------------------------------------------------------------------------------


def test_every_recipe_installs(org):
    api, _user = api_as(org, "admin")
    listed = api.get("/api/v1/automation-recipes").json()
    assert len(listed) == len(recipes.RECIPES) >= 9
    for row in listed:
        response = api.post(f"/api/v1/automation-recipes/{row['key']}/install")
        assert response.status_code == 201, (row["key"], response.content)
        assert response.json()["enabled"] is False
    assert all(r["installed"] for r in api.get("/api/v1/automation-recipes").json())
    assert api.post("/api/v1/automation-recipes/nope/install").status_code == 404


# --- isolation ----------------------------------------------------------------------------------


class TestAutomationIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/automations"

    def make_object(self, organisation):
        return make(organisation)


class TestRunIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/automation-runs"

    def make_object(self, organisation):
        automation = make(
            organisation, trigger_type="manual", trigger_config={"subject": "student"}
        )
        with tenant_context(organisation):
            student = StudentFactory(organisation=organisation)
            return services.prepare_run(automation, subject_id=str(student.pk),
                                        run_key="manual:x", manual=True)  # fmt: skip
