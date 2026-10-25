"""E09-TW1: the report SLA and unconfirmed-lesson workflows, replaced by built-in workflows
in E33 T05 (``test_workflows_builtin_runs.py``): kept while runs under way finish, so their
signals and recorded histories are still tested."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now
from tutortrack.delivery import services
from tutortrack.delivery.models import LessonReport
from tutortrack.delivery.processes import (
    LessonReportSlaWorkflow,
    UnconfirmedLessonWorkflow,
    sla_workflow_id,
    unconfirmed_workflow_id,
)
from tutortrack.tenancy import settings_service

from .test_delivery import lesson_at, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def event_types(org) -> list[str]:
    with tenant_context(org):
        return list(OutboxEvent.objects.values_list("event_type", flat=True))


def test_submitting_ends_the_sla_workflow(org, people, temporal_env):  # noqa: F811
    from tutortrack.core.workflows import start_now
    from tutortrack.delivery.processes import ReportSlaInput

    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
        report = LessonReport.objects.get(lesson=lesson)
    wid = sla_workflow_id(org.pk, report.pk)
    # Anchor the deadline to the session-wide test server's clock (it has moved on).
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    due = (server_now + timedelta(hours=23)).isoformat()
    start_now(
        LessonReportSlaWorkflow,
        ReportSlaInput(organisation_id=str(org.pk), report_id=str(report.pk), due_at=due),
        id=wid,
        subject=("lesson_report", str(report.pk)),
    )
    with tenant_context(org):
        services.submit_report(report, answers={"covered": "Fractions"})
    dispatch_batch()  # lesson_report.submitted → signal
    assert temporal_env.result(wid) == "submitted"
    assert "lesson_report.overdue" not in event_types(org)


def test_completing_resolves_the_unconfirmed_workflow(org, people, temporal_env):  # noqa: F811
    from tutortrack.core.workflows import start_now
    from tutortrack.delivery.processes import UnconfirmedInput

    with tenant_context(org):  # no report process: every workflow a test starts must finish
        settings_service.update_settings("delivery", {"delivery.report_required": False})
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    # The session-wide test server's clock has moved on: anchor the wait to it.
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    start_now(
        UnconfirmedLessonWorkflow,
        UnconfirmedInput(
            organisation_id=str(org.pk), lesson_id=str(lesson.pk), end=server_now.isoformat()
        ),
        id=unconfirmed_workflow_id(org.pk, lesson.pk),
        subject=("lesson", str(lesson.pk)),
    )
    with tenant_context(org):
        services.complete_lesson(lesson)
    dispatch_batch()  # lesson.completed → signal "resolved"
    assert temporal_env.result(unconfirmed_workflow_id(org.pk, lesson.pk)) == "resolved"


@pytest.mark.parametrize(
    ("workflow", "prefix"),
    [
        (LessonReportSlaWorkflow, "LessonReportSlaWorkflow"),
        (UnconfirmedLessonWorkflow, "UnconfirmedLessonWorkflow"),
    ],
)
def test_histories_replay(workflow, prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[workflow], data_converter=data_converter(), workflow_runner=sandbox_runner()
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
