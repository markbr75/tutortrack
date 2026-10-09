"""E09-TW1: report SLA and unconfirmed-lesson workflows on Temporal."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent, WorkflowLink
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.delivery import services
from tutortrack.delivery.models import LessonReport
from tutortrack.delivery.processes import (
    LessonReportSlaWorkflow,
    UnconfirmedLessonWorkflow,
    sla_workflow_id,
    unconfirmed_workflow_id,
)
from tutortrack.delivery.tasks import start_unconfirmed_checks
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

from .test_delivery import lesson_at, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def event_types(org) -> list[str]:
    with tenant_context(org):
        return list(OutboxEvent.objects.values_list("event_type", flat=True))


def complete_recent(org, people):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
        report = LessonReport.objects.get(lesson=lesson)
    dispatch_batch()  # lesson_report.requested → the bridge starts the SLA workflow
    return lesson, report


def test_sla_reminds_marks_overdue_and_escalates(org, people, temporal_env):  # noqa: F811
    with tenant_context(org):
        settings_service.update_settings("delivery", {"delivery.hold_pay_overdue_reports": True})
    _lesson, report = complete_recent(org, people)
    wid = sla_workflow_id(org.pk, report.pk)
    assert temporal_env.result(wid) == "escalated"
    kinds = event_types(org)
    for kind in ("lesson_report.due", "lesson_report.overdue", "lesson_report.escalated"):
        assert kinds.count(kind) == 1, kind
    with tenant_context(org):
        report.refresh_from_db()
        assert report.pay_held is True
        assert report.overdue_at is not None
        assert Task.objects.filter(target_id=str(report.pk)).exists()
        link = WorkflowLink.objects.get(workflow_id=wid)
    assert (link.status, link.current_step) == ("completed", "escalated")


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


def test_unconfirmed_lesson_is_flagged_once(org, people, temporal_env):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    assert start_unconfirmed_checks(organisation_id=str(org.pk)) == 1
    assert start_unconfirmed_checks(organisation_id=str(org.pk)) == 0  # already running
    assert temporal_env.result(unconfirmed_workflow_id(org.pk, lesson.pk)) == "flagged"
    with tenant_context(org):
        lesson.refresh_from_db()
    assert lesson.unconfirmed_at is not None
    assert event_types(org).count("lesson.unconfirmed") == 1


def test_unconfirmed_lesson_auto_completes(org, people, temporal_env):  # noqa: F811
    with tenant_context(org):
        settings_service.update_settings(
            "delivery",
            # Without a report process: workflows a test starts must all finish.
            {"delivery.unconfirmed_action": "auto_complete", "delivery.report_required": False},
        )
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    start_unconfirmed_checks(organisation_id=str(org.pk))
    assert temporal_env.result(unconfirmed_workflow_id(org.pk, lesson.pk)) == "auto_completed"
    with tenant_context(org):
        lesson.refresh_from_db()
    assert (lesson.status, lesson.auto_completed) == (Lesson.Status.COMPLETED, True)


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


def test_record_histories_if_requested(org, people, temporal_env):  # noqa: F811
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    _lesson, report = complete_recent(org, people)
    wid = sla_workflow_id(org.pk, report.pk)
    temporal_env.result(wid)
    (HISTORIES / "LessonReportSlaWorkflow-escalated.json").write_text(
        temporal_env.history_json(wid)
    )
    lesson = lesson_at(org, people, now() - timedelta(hours=3))
    start_unconfirmed_checks(organisation_id=str(org.pk))
    uid = unconfirmed_workflow_id(org.pk, lesson.pk)
    temporal_env.result(uid)
    (HISTORIES / "UnconfirmedLessonWorkflow-flagged.json").write_text(
        temporal_env.history_json(uid)
    )
