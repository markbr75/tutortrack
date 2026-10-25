"""E33 T01: sequences on the automation engine: "only if" on a step, "stop when" an event
arrives for the record, and waits at a time of day on a business day."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from tutortrack.automations import services
from tutortrack.automations.tests.test_workflows import (
    MESSAGE,
    automation,
    change_status,
    record,
    runs,
    student_in,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.crm.services import tags_for

pytestmark = pytest.mark.django_db(transaction=True)

TAG = {"type": "action", "action": "add_tag", "config": {"tag": "Active"}}
TASK = {"type": "action", "action": "create_task", "config": {"title": "Call the family"}}


def problems(org, steps, **fields) -> dict:
    with pytest.raises(BusinessRuleViolation) as caught:
        automation(org, steps, **fields)
    return caught.value.extra["errors"]


def test_new_step_options_are_checked_when_saved(org):
    assert "steps" in problems(org, [{"type": "wait", "days": 1, "at": "9am"}])
    assert "steps" in problems(org, [{"type": "wait", "until": "student.nope"}])
    assert "steps" in problems(
        org, [{**TAG, "only_if": {"field": "student.nope", "op": "equals", "value": 1}}]
    )
    # Stop-when events must be about the same kind of record, and at most three.
    assert "stop_when" in problems(org, [TAG], stop_when=["invoice.paid"])
    assert "stop_when" in problems(org, [TAG], stop_when=["student.created"] * 4)
    ok = automation(org, [{"type": "wait", "days": 0, "at": "18:00"}, TAG],
                    stop_when=["student.created"])  # fmt: skip
    assert ok.stop_when == ["student.created"]
    with tenant_context(org):
        assert ok.versions.get().stop_when == ["student.created"]
        # Changing stop-when is a new version.
        with transaction.atomic():
            services.update_automation(ok, stop_when=[])
        assert ok.versions.count() == 2


def test_a_step_whose_only_if_no_longer_holds_is_skipped(org, temporal_env):
    student = student_in(org)
    automation(org, [
        {**TAG, "only_if": {"field": "student.status", "op": "equals", "value": "active"}},
        TASK,
    ])  # fmt: skip
    change_status(org, student, "paused")
    dispatch_batch()
    [run] = runs(org)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        statuses = {s.step_key: s.status for s in run.steps.all()}
        assert statuses == {"0": "skipped", "1": "completed"}
        assert not tags_for("people.student", [str(student.pk)]).get(str(student.pk))
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-only-if")


def test_a_stop_when_event_ends_a_waiting_run_before_its_next_step(org, temporal_env):
    student = student_in(org)
    automation(org, [{"type": "wait", "days": 3}, MESSAGE],
               stop_when=["student.status_changed"])  # fmt: skip
    change_status(org, student, "paused")
    dispatch_batch()  # starts the run, which waits 3 days
    [run] = runs(org)
    change_status(org, student, "active")
    dispatch_batch()  # the stop-when event for the same student
    assert temporal_env.result(run.workflow_id) == "stopped"
    with tenant_context(org):
        run.refresh_from_db()
        assert (run.status, run.stop_reason) == ("stopped", "student.status_changed")
        assert not run.steps.filter(step_key="1").exists()  # the message was never sent
        from tutortrack.comms.models import Message

        assert not Message.objects.filter(type_key="automation_message").exists()
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-stopped")


def test_a_wait_ends_at_a_time_of_day_on_a_business_day(org, temporal_env):
    student = student_in(org)
    automation(org, [{"type": "wait", "days": 1, "at": "09:00", "business_day": True}, TASK])
    change_status(org, student, "paused")
    dispatch_batch()
    [run] = runs(org)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        wait = run.steps.get(step_key="0")
        wall = wait.resume_at.astimezone(ZoneInfo(org.timezone))
        assert (wall.hour, wall.minute) == (9, 0)
        assert wall.weekday() != 6  # Sunday has no business hours by default
        assert run.steps.get(step_key="1").status == "completed"
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-timed")


def test_the_dry_run_describes_the_new_waits_and_skips(org):
    student = student_in(org)
    rule = automation(org, [
        {"type": "wait", "until": "student.date_of_birth", "offset_days": -3, "at": "09:00",
         "business_day": True},
        {**TAG, "only_if": {"field": "student.status", "op": "equals", "value": "paused"}},
    ])  # fmt: skip
    with tenant_context(org):
        steps = services.dry_run(rule, str(student.pk))["steps"]
    assert steps[0]["description"] == (
        "Wait until 3 days before student.date_of_birth, at 09:00, on a business day"
    )
    assert steps[1]["skipped"] is True


# --- E33 T02: pause and resume, start another workflow, skipped with a reason ------------------


def wait_for(org, run, status, seconds=20):
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with tenant_context(org):
            run.refresh_from_db()
        if run.status == status:
            return
        time.sleep(0.1)
    raise AssertionError(f"run is {run.status}, not {status}")


def test_a_paused_workflow_holds_its_runs_until_resumed(org, temporal_env):
    from datetime import timedelta

    student = student_in(org)
    rule = automation(org, [{"type": "wait", "days": 1}, TAG])
    change_status(org, student, "paused")
    dispatch_batch()
    [run] = runs(org)
    with tenant_context(org):
        services.pause(rule)
    # New events start nothing while paused.
    change_status(org, student, "active")
    dispatch_batch()
    assert len(runs(org)) == 1
    temporal_env.skip(timedelta(days=2))  # the wait ends; the next action holds
    wait_for(org, run, "paused")
    with tenant_context(org):
        assert not run.steps.filter(step_key="1").exists()
        services.resume(rule)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        assert run.status == "completed"
        assert [t.name for t in tags_for("people.student", [str(student.pk)])[str(student.pk)]] == [
            "Active"
        ]
    record(temporal_env, run.workflow_id, "AutomationRunWorkflow-paused")


def test_start_another_workflow_runs_it_one_level_deeper(org, temporal_env):
    student = student_in(org)
    target = automation(org, [TAG], trigger_type="manual", trigger_config={"subject": "student"})
    automation(org, [{"type": "action", "action": "start_workflow",
                      "config": {"workflow": str(target.pk)}}])  # fmt: skip
    change_status(org, student, "paused")
    dispatch_batch()
    [parent] = runs(org)
    assert temporal_env.result(parent.workflow_id) == "completed"
    child = runs(org)[1]
    assert temporal_env.result(child.workflow_id) == "completed"
    assert (child.automation_id, child.causation_depth) == (target.pk, 1)


def test_a_step_the_record_has_moved_past_is_skipped_with_its_reason(org):
    student = student_in(org)
    target = automation(org, [TAG], trigger_type="manual", trigger_config={"subject": "student"})
    step = {"type": "action", "action": "start_workflow", "config": {"workflow": str(target.pk)}}
    rule = automation(org, [step])
    with tenant_context(org), transaction.atomic():
        services.set_enabled(target, False)
        run = services.prepare_run(rule, subject_id=str(student.pk), run_key="test")
    with tenant_context(org):
        assert services.execute_step(str(run.pk), "0", step)["status"] == "skipped"
        logged = run.steps.get(step_key="0")
    assert (logged.status, logged.result) == ("skipped", {"skipped": "the other workflow is off"})
