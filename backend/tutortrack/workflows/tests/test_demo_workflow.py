"""E32-T12 reference workflow: happy path, timers in tenant time, signal, query, retry,
replay (FR-32-11 test set)."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from unittest import mock

import pytest
from temporalio.client import WorkflowExecutionStatus

from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent, WorkflowLink
from tutortrack.core.workflows import start_now, workflow_id
from tutortrack.workflows.demo import DemoReminderInput, DemoReminderWorkflow

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def begin(org, **kwargs) -> str:
    wid = workflow_id("demo-reminder", org.pk, "subject-1")
    start_now(
        DemoReminderWorkflow,
        DemoReminderInput(organisation_id=str(org.pk), subject_id="subject-1", **kwargs),
        id=wid,
        subject=("demo", "subject-1"),
    )
    return wid


def test_waits_in_tenant_time_then_publishes(org, temporal_env):
    wid = begin(org, days=3, note="hello")
    with tenant_context(org):
        link = WorkflowLink.objects.get(workflow_id=wid)
        assert (link.process, link.subject_type, link.status) == (
            "demo-reminder",
            "demo",
            "running",
        )

    started = temporal_env.run(temporal_env.env.get_current_time())
    assert temporal_env.result(wid) == "reminded"  # 3 days skipped in milliseconds
    finished = temporal_env.run(temporal_env.env.get_current_time())
    assert finished - started >= timedelta(days=2)

    event = OutboxEvent.objects.get(event_type="demo.reminder_due")
    assert event.organisation_id == org.pk
    assert event.payload["actor"] == {"type": "workflow", "id": wid}
    assert event.payload["data"] == {"note": "hello"}
    with tenant_context(org):
        link.refresh_from_db()
    assert (link.status, link.current_step) == ("completed", "done")
    assert link.closed_at is not None
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "DemoReminderWorkflow-reminded.json").write_text(
            temporal_env.history_json(wid)
        )


def test_cancel_signal_and_state_query(org, temporal_env):
    wid = begin(org, days=10)
    handle = temporal_env.handle(wid)
    temporal_env.run(handle.signal(DemoReminderWorkflow.cancel))
    assert temporal_env.result(wid) == "cancelled"
    assert not OutboxEvent.objects.filter(event_type="demo.reminder_due").exists()
    assert temporal_env.run(handle.query(DemoReminderWorkflow.state)) == {"step": "cancelled"}


def test_duplicate_starts_are_idempotent(org, temporal_env):
    wid = begin(org, days=1)
    again = start_now(
        DemoReminderWorkflow,
        DemoReminderInput(organisation_id=str(org.pk), subject_id="subject-1"),
        id=wid,
    )
    assert again is None
    temporal_env.result(wid)


def test_activity_failures_are_retried_and_publish_once(org, temporal_env):
    from tutortrack.core.events import publisher

    real = publisher.publish
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database blip")
        return real(*args, **kwargs)

    with mock.patch("tutortrack.workflows.demo.publish", side_effect=flaky):
        wid = begin(org, days=1)
        assert temporal_env.result(wid) == "reminded"
    assert calls["n"] == 2
    assert OutboxEvent.objects.filter(event_type="demo.reminder_due").count() == 1


def test_payloads_are_encrypted_in_temporal(org, temporal_env):
    wid = begin(org, days=1, note="Personal detail")
    temporal_env.result(wid)
    raw = temporal_env.run(temporal_env.env.client.get_workflow_handle(wid).fetch_history())
    dumped = raw.to_json()
    assert "Personal detail" not in dumped
    assert str(org.pk) not in dumped
    status = temporal_env.run(temporal_env.handle(wid).describe()).status
    assert status == WorkflowExecutionStatus.COMPLETED


def test_replay_recorded_history():
    """CI replays stored histories against the current code (FR-32-8)."""
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("DemoReminderWorkflow*.json"))
    assert files, "record a history with tests/workflow_histories/README.md"
    replayer = Replayer(
        workflows=[DemoReminderWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        history = WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
        runtime.run(replayer.replay_workflow(history))
