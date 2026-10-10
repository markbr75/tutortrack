"""E14-TW1: automation runs on Temporal (waits, branches, retries, loop stop, schedules)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.automations import services
from tutortrack.automations.models import AutomationRun
from tutortrack.automations.processes import (
    AutomationRunWorkflow,
    AutomationScheduleWorkflow,
    ScheduleInput,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.crm.services import tags_for
from tutortrack.people import services as people
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
MESSAGE = {"type": "action", "action": "send_message", "config": {
    "to": ["client"], "channels": ["email"], "subject": "Hi", "body": "{{ student.first_name }}",
}}  # fmt: skip


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def student_in(org, **fields):
    with tenant_context(org):
        client = ClientFactory(organisation=org)
        contact = ContactFactory(organisation=org, client=client, email="p@example.com")
        client.primary_contact = contact
        client.save()
        return StudentFactory(organisation=org, client=client, status="active", **fields)


def automation(org, steps, **fields):
    with tenant_context(org), transaction.atomic():
        return services.create_automation(
            name="Test", trigger_type=fields.pop("trigger_type", "event"),
            trigger_config=fields.pop("trigger_config", {"event": "student.status_changed"}),
            steps=steps, enabled=True, **fields,
        )  # fmt: skip


def change_status(org, student, status):
    with tenant_context(org), transaction.atomic():
        people.change_student_status(type(student).objects.get(pk=student.pk), status)


def runs(org):
    with tenant_context(org):
        return list(AutomationRun.objects.order_by("started_at"))


def test_event_run_waits_branches_and_completes(org, temporal_env):
    student = student_in(org)
    automation(org, [
        MESSAGE,
        {"type": "wait", "days": 2},
        {"type": "branch", "if": {"field": "student.status", "op": "equals", "value": "paused"},
         "then": [{"type": "action", "action": "add_tag", "config": {"tag": "Paused"}}],
         "else": [{"type": "action", "action": "create_task", "config": {"title": "Check"}}]},
    ])  # fmt: skip
    change_status(org, student, "paused")
    dispatch_batch()  # student.status_changed → AutomationRunWorkflow
    [run] = runs(org)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        assert run.status == "completed"
        steps = {s.step_key: s.status for s in run.steps.all()}
        assert steps == {"0": "completed", "1": "completed", "2": "completed",
                         "2.then.0": "completed"}  # fmt: skip
        assert run.steps.get(step_key="1").resume_at is not None
        tags = tags_for("people.student", [str(student.pk)])[str(student.pk)]
        assert [t.name for t in tags] == ["Paused"]
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-completed")


def test_a_failed_step_can_be_retried(org, temporal_env, monkeypatch):
    student = student_in(org)
    calls = []

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def flaky(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("connection refused")
        return Reply()

    monkeypatch.setattr("tutortrack.core.net.safe_urlopen", flaky)
    automation(org, [
        MESSAGE,
        {"type": "action", "action": "webhook", "config": {"url": "https://hooks.example.com/a"}},
    ])  # fmt: skip
    change_status(org, student, "paused")
    dispatch_batch()
    [run] = runs(org)
    assert temporal_env.result(run.workflow_id) == "failed"
    with tenant_context(org):
        run.refresh_from_db()
        assert "connection refused" in run.error
        with transaction.atomic():
            run = services.retry(run)
    assert run.workflow_id.endswith("-retry2")
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        assert (run.status, run.attempts) == ("completed", 2)
        assert run.steps.filter(status="completed").count() == 2
        from tutortrack.comms.models import Message

        assert Message.objects.filter(type_key="automation_message").count() == 1  # not resent
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-retried")


def test_automations_triggering_each_other_are_stopped(org, temporal_env):
    student = student_in(org)
    automation(org, [
        {"type": "branch", "if": {"field": "student.status", "op": "equals", "value": "paused"},
         "then": [{"type": "action", "action": "update_field",
                   "config": {"field": "status", "value": "active"}}],
         "else": [{"type": "action", "action": "update_field",
                   "config": {"field": "status", "value": "paused"}}]},
    ], max_runs_per_record=20)  # fmt: skip
    change_status(org, student, "paused")
    seen: set[object] = set()
    for _round in range(10):
        dispatch_batch()
        fresh = [r for r in runs(org) if r.pk not in seen]
        if not fresh:
            break
        for run in fresh:
            seen.add(run.pk)
            if run.status != "skipped":
                temporal_env.result(run.workflow_id)
    final = runs(org)
    assert [r.causation_depth for r in final] == [0, 1, 2, 3, 4]
    assert [r.status for r in final][-1] == "skipped"
    assert all(r.status == "completed" for r in final[:-1])


def test_schedule_fans_out_to_due_records(org, temporal_env):
    from tutortrack.core.workflows import start_now

    with tenant_context(org):
        today = services.org_today()
    student = student_in(org, date_of_birth=today.replace(year=2012))
    student_in(org)  # no birthday
    birthday = automation(org, [MESSAGE], trigger_type="date", trigger_config={
        "subject": "student", "field": "date_of_birth", "offset_days": 0, "anniversary": True,
        "time": "08:00",
    })  # fmt: skip
    wid = f"automation-schedule:{org.pk}:{birthday.pk}:test"
    start_now(
        AutomationScheduleWorkflow,
        ScheduleInput(organisation_id=str(org.pk), automation_id=str(birthday.pk)),
        id=wid,
    )
    assert temporal_env.result(wid) == 1
    [run] = runs(org)
    assert run.subject_id == str(student.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    assert run.run_key == f"schedule:{today.isoformat()}"
    record(temporal_env, wid, "AutomationScheduleWorkflow-fanout")


@pytest.mark.parametrize("prefix", ["AutomationRunWorkflow", "AutomationScheduleWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[AutomationRunWorkflow, AutomationScheduleWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
