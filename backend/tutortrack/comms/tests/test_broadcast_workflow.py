"""E13-TW1: BroadcastWorkflow (scheduled start, throttled batches, pause/resume, cancel,
quiet hours, retries) and replay of the recorded histories."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.comms import broadcasts
from tutortrack.comms.models import Broadcast, Message
from tutortrack.comms.processes import BroadcastWorkflow
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.time import now
from tutortrack.people.tests.factories import ClientFactory, ContactFactory
from tutortrack.tenancy import settings_service

from .test_comms import quiet_window

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def families(org, count: int, *, mobile: bool = False) -> None:
    for i in range(count):
        client = ClientFactory(organisation=org, display_name=f"Family {i}")
        ContactFactory(
            organisation=org,
            client=client,
            first_name=f"Parent{i}",
            email=f"parent{i}@example.com",
            mobile=f"07700 90{i:04d}" if mobile else "",
            is_primary=True,
        )


def scheduled(org, *, channel="email", days_ahead=0, batch=2, pause=60):
    with tenant_context(org), transaction.atomic():
        settings_service.update_settings(
            "comms",
            {"comms.broadcast_batch_size": batch, "comms.broadcast_batch_pause_seconds": pause},
        )
        draft = broadcasts.create_broadcast(
            name="Half term", channel=channel, subject="Half term", body="Hello, lessons pause."
        )
        when = now() + timedelta(days=days_ahead) if days_ahead else None
        broadcasts.schedule(draft, scheduled_for=when)
    dispatch_batch()  # broadcast.scheduled → BroadcastWorkflow
    return draft, broadcasts.broadcast_workflow_id(org.pk, draft.pk)


def status_of(draft) -> str:
    return str(Broadcast.objects.get(pk=draft.pk).status)


def test_a_scheduled_broadcast_waits_then_sends_in_batches(org, temporal_env):
    families(org, 5)
    draft, wid = scheduled(org, days_ahead=2)
    assert temporal_env.result(wid) == "sent"
    with tenant_context(org):
        row = Broadcast.objects.get(pk=draft.pk)
        assert row.status == "sent"
        assert row.stats["queued"] == 5
        assert set(row.recipients.values_list("batch", flat=True)) == {1, 2, 3}
    assert len(mail.outbox) == 5
    record(temporal_env, wid, "BroadcastWorkflow-sent")


def test_pause_and_resume(org, temporal_env):
    from tutortrack.core.workflows.ops import query_now

    families(org, 3)
    draft, wid = scheduled(org, batch=1, pause=3600)
    wait_for(org, lambda: Message.objects.filter(related_id=str(draft.pk)).count() == 1)
    with tenant_context(org), transaction.atomic():
        broadcasts.pause(Broadcast.objects.get(pk=draft.pk))
    deadline = clock.monotonic() + 20
    while not query_now(wid, "state")["paused"]:
        assert clock.monotonic() < deadline
        clock.sleep(0.1)
    with tenant_context(org):
        assert status_of(draft) == "paused"
    with tenant_context(org), transaction.atomic():
        broadcasts.resume(Broadcast.objects.get(pk=draft.pk))
    assert temporal_env.result(wid) == "sent"
    with tenant_context(org):
        assert Message.objects.filter(related_id=str(draft.pk)).count() == 3
    record(temporal_env, wid, "BroadcastWorkflow-paused")


def test_cancel_before_the_scheduled_time(org, temporal_env):
    families(org, 2)
    draft, wid = scheduled(org, days_ahead=1)
    wait_for(org, lambda: status_of(draft) == "scheduled")
    from tutortrack.core.models import WorkflowLink

    wait_for(
        org, lambda: WorkflowLink.objects.filter(workflow_id=wid, current_step="waiting").exists()
    )
    with tenant_context(org), transaction.atomic():
        broadcasts.cancel(Broadcast.objects.get(pk=draft.pk))
    assert temporal_env.result(wid) == "cancelled"
    with tenant_context(org):
        assert not Message.objects.filter(related_id=str(draft.pk)).exists()
    record(temporal_env, wid, "BroadcastWorkflow-cancelled")


def test_texts_wait_for_quiet_hours_to_end(org, temporal_env):
    families(org, 2, mobile=True)
    with tenant_context(org):
        settings_service.update_settings("comms", quiet_window(now_is_quiet=True))
    started = temporal_env.run(temporal_env.env.get_current_time())
    draft, wid = scheduled(org, channel="sms")
    assert temporal_env.result(wid) == "sent"
    assert temporal_env.run(temporal_env.env.get_current_time()) - started >= timedelta(hours=1)
    with tenant_context(org):
        assert Message.objects.filter(related_id=str(draft.pk), channel="sms").count() == 2
    record(temporal_env, wid, "BroadcastWorkflow-quiet")


def test_a_failed_batch_is_retried(org, temporal_env, monkeypatch):
    real = broadcasts.send_batch
    calls: list[int] = []

    def flaky(broadcast_id, batch):
        calls.append(batch)
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return real(broadcast_id, batch)

    monkeypatch.setattr(broadcasts, "send_batch", flaky)
    families(org, 2)
    _draft, wid = scheduled(org)
    assert temporal_env.result(wid) == "sent"
    assert calls[:2] == [1, 1]
    record(temporal_env, wid, "BroadcastWorkflow-retried")


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("BroadcastWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[BroadcastWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
