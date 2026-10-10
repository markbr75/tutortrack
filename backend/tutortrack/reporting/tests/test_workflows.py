"""E26-T07 (TW): scheduled report delivery on Temporal."""

from __future__ import annotations

import json
import os
from datetime import time
from pathlib import Path
from typing import Any

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.models import ScheduleLink
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.reporting import services
from tutortrack.reporting.models import ReportRun
from tutortrack.reporting.processes import ScheduledReportInput, ScheduledReportWorkflow

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env: Any, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def schedule(org: Any, **fields: Any) -> tuple[Any, Any]:
    owner = MembershipFactory(organisation=org, role="finance").user
    recipient = MembershipFactory(organisation=org, role="admin").user
    with tenant_context(org), transaction.atomic():
        saved = services.create_saved_report(
            owner, name="Weekly revenue", report_key="revenue", params={"period": "this_month"}
        )
        scheduled = services.create_scheduled_report(
            owner,
            saved,
            recipients=[recipient.pk],
            frequency="weekly",
            weekday=0,
            time=time(7),
            format="csv",
            **fields,
        )
    return scheduled, recipient


def start(org: Any, scheduled: Any, suffix: str) -> str:
    from tutortrack.core.workflows import start_now

    wid = f"scheduled-report:{org.pk}:{scheduled.pk}-{suffix}"
    start_now(
        ScheduledReportWorkflow,
        ScheduledReportInput(organisation_id=str(org.pk), scheduled_id=str(scheduled.pk)),
        id=wid,
    )
    return wid


def test_scheduled_report_is_generated_and_emailed(org, temporal_env, s3):
    scheduled, recipient = schedule(org)
    wid = start(org, scheduled, "happy")
    assert temporal_env.result(wid) == "delivered:1"
    with tenant_context(org):
        run = ReportRun.objects.get(run_key=wid)
        assert run.status == "delivered"
        assert run.file is not None
    assert [m.to for m in mail.outbox if m.attachments] == [[recipient.email]]
    record(temporal_env, wid, "ScheduledReportWorkflow-delivered")


def test_generation_is_retried(org, temporal_env, s3, monkeypatch):
    scheduled, _recipient = schedule(org)
    real = services.generate_scheduled_run
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("storage hiccup")
        return real(*args, **kwargs)

    monkeypatch.setattr(services, "generate_scheduled_run", flaky)
    wid = start(org, scheduled, "retry")
    assert temporal_env.result(wid) == "delivered:1"
    assert len(calls) == 2


def test_a_run_that_keeps_failing_is_marked_failed(org, temporal_env, monkeypatch):
    scheduled, _recipient = schedule(org)

    def broken(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("report exploded")

    monkeypatch.setattr(services, "generate_scheduled_run", broken)
    wid = start(org, scheduled, "failing")
    assert temporal_env.result(wid) == "failed"
    with tenant_context(org):
        run = ReportRun.objects.get(run_key=wid)
        assert run.status == "failed"
        assert "report exploded" in run.error
    record(temporal_env, wid, "ScheduledReportWorkflow-failed")


def test_paused_schedule_is_skipped(org, temporal_env):
    scheduled, _recipient = schedule(org, enabled=False)
    wid = start(org, scheduled, "paused")
    assert temporal_env.result(wid) == "skipped"


def test_schedule_follows_the_scheduled_report(org, temporal_local_env):
    scheduled, _recipient = schedule(org)
    with tenant_context(org):
        sid = services.sync_schedule(scheduled.pk)
        assert sid
        assert ScheduleLink.objects.filter(schedule_id=sid).exists()
        scheduled.enabled = False
        scheduled.save()
        assert services.sync_schedule(scheduled.pk) is None
        assert not ScheduleLink.objects.filter(schedule_id=sid).exists()


@pytest.mark.parametrize("prefix", ["ScheduledReportWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ScheduledReportWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
