"""E34-T01: ``PathwayRunWorkflow`` on Temporal: finishing steps ends it, timers send the
reminder and the overdue notice, cancelling ends it; plus replay of recorded histories."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.pathways import services
from tutortrack.pathways.models import PathwayStep
from tutortrack.pathways.processes import PathwayRunWorkflow, run_workflow_id

from .factories import acknowledge, make_job, make_template, make_tutor, review, sign

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def _start(org, template, tutor):
    job = make_job(org)
    with tenant_context(org), transaction.atomic():
        return services.start_run(template, record_id=job.pk, tutor=tutor)


def _step(run, key):
    return PathwayStep.objects.get(run=run, key=key)


def test_finishing_every_step_ends_the_workflow(org, temporal_env, s3):
    template = make_template(org, [
        {"key": "paperwork", "name": "Paperwork", "steps": [acknowledge(due_days=7)]},
        {"key": "ready", "name": "Ready", "gate": "ready", "steps": [review()]},
    ])  # fmt: skip
    tutor = make_tutor(org)
    staff = MembershipFactory(organisation=org, role="coordinator").user
    run = _start(org, template, tutor)
    wid = run_workflow_id(org.pk, run.pk)
    with tenant_context(org), transaction.atomic():
        services.complete_step(_step(run, "safeguarding"), user=tutor.membership.user)
    with tenant_context(org), transaction.atomic():
        services.complete_step(_step(run, "check"), user=staff)
    assert temporal_env.result(wid) == "completed"
    record(temporal_env, wid, "PathwayRunWorkflow-completed")


def test_timers_remind_then_say_overdue_and_cancelling_ends_it(org, temporal_env, monkeypatch):
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    monkeypatch.setattr(services, "now", lambda: server_now)  # the run's dates on test time
    template = make_template(org, [{"key": "a", "name": "A", "steps": [sign(due_days=2)]}])
    tutor = make_tutor(org)
    run = _start(org, template, tutor)
    wid = run_workflow_id(org.pk, run.pk)
    temporal_env.skip(timedelta(days=3))
    wait_for(org, lambda: _step(run, "agreement").overdue_at is not None)
    with tenant_context(org):
        step = _step(run, "agreement")
        assert step.reminded_at is not None
        keys = set(
            Message.objects.filter(type_key="pathway_task_reminder").values_list(
                "dedupe_key", flat=True
            )
        )
        assert any(":due_soon:" in k for k in keys)
        assert any(":overdue:" in k for k in keys)
    admin = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org), transaction.atomic():
        services.cancel_run(run, user=admin, reason="No longer needed")
    assert temporal_env.result(wid) == "cancelled"
    record(temporal_env, wid, "PathwayRunWorkflow-reminded-cancelled")


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("PathwayRunWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[PathwayRunWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
