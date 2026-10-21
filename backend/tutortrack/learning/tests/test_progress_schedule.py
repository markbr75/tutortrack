"""Gap G5c (FR-21-6): progress reports drafted on a monthly or termly schedule (Temporal
Schedule + ``ProgressReportRunWorkflow``, with a recorded replay history)."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import ScheduleLink
from tutortrack.courses.tests.factories import TermFactory
from tutortrack.learning import progress_schedule
from tutortrack.learning.models import ProgressReport
from tutortrack.learning.processes import ProgressReportRunWorkflow, ProgressRunInput

from .conftest import at, events_of, lesson_for, set_learning

HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def first_of_next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def taught_last_month(org, world) -> date:
    """Two lessons for Arjun (one with Nia, one with Sam: Nia taught most); returns the
    'today' on which they were last month."""
    lessons = [lesson_for(org, world, at(-3), [world["student"]])]
    lessons.append(lesson_for(org, world, at(-3, hour=12), [world["student"]]))
    lesson_for(org, world, at(-3, hour=14), [world["student"]], tutor=world["other_tutor"])
    return first_of_next_month(lessons[0].start.date())


@pytest.mark.django_db
def test_monthly_plan_drafts_missing_reports_for_the_main_tutor(org, world):
    set_learning(org, progress_schedule="monthly")
    today = taught_last_month(org, world)
    with tenant_context(org):
        (period,) = progress_schedule.plan(today)
        start, end = progress_schedule.last_month(today)
        assert (period["period"], period["start"], period["end"]) == (
            "monthly",
            start.isoformat(),
            end.isoformat(),
        )
        assert period["students"] == [str(world["student"].pk)]
        assert progress_schedule.draft("monthly", start, end, period["students"]) == 1
        report = ProgressReport.objects.get()
        assert (report.status, report.period, report.author_id) == (
            "draft",
            "monthly",
            world["tutor"].pk,
        )
        assert report.snapshot  # built from the period's lessons
        # Idempotent: a rerun finds nothing to draft and never touches the existing draft.
        assert progress_schedule.plan(today)[0]["students"] == []
        assert progress_schedule.draft("monthly", start, end, period["students"]) == 0


@pytest.mark.django_db
def test_announce_tells_the_author_and_staff_once(org, world):
    set_learning(org, progress_schedule="monthly")
    today = taught_last_month(org, world)
    with tenant_context(org):
        start, end = progress_schedule.last_month(today)
        progress_schedule.draft("monthly", start, end, [str(world["student"].pk)])
        assert progress_schedule.announce("monthly", start, end) == 1
        progress_schedule.announce("monthly", start, end)  # rerun: deduplicated
        tutor_notices = Message.objects.filter(type_key="progress_reports_drafted")
        assert tutor_notices.filter(channel="in_app").count() == 1
        assert Message.objects.filter(
            type_key="staff_progress_reports_drafted", channel="in_app"
        ).exists()
    batches = events_of(org, "progress_report.batch_drafted")
    assert len(batches) == 1
    assert batches[0]["data"]["created"] == 1


@pytest.mark.django_db
def test_termly_plan_uses_terms_that_just_ended(org, world):
    set_learning(org, progress_schedule="termly")
    lesson = lesson_for(org, world, at(-3), [world["student"]])
    day = lesson.start.date()
    with tenant_context(org):
        TermFactory(
            organisation=org,
            branch_id=world["student"].branch_id,
            start_date=day - timedelta(days=30),
            end_date=day + timedelta(days=1),
        )
        assert progress_schedule.plan(day) == []  # the term hasn't ended yet
        (period,) = progress_schedule.plan(day + timedelta(days=2))
        assert period["period"] == "termly"
        assert period["end"] == (day + timedelta(days=1)).isoformat()
        assert period["students"] == [str(world["student"].pk)]
        assert progress_schedule.plan(day + timedelta(days=10)) == []  # outside the look-back


@pytest.mark.django_db
def test_off_by_default_and_settings_follow_the_schedule(org, world, monkeypatch):
    with tenant_context(org):
        assert progress_schedule.plan(date(2026, 11, 1)) == []
    calls: list[str] = []
    monkeypatch.setattr(progress_schedule, "sync_schedule", lambda: calls.append("sync") or "")
    set_learning(org, progress_schedule="monthly")
    dispatch_batch()  # organisation.settings_updated → keep the Temporal Schedule in step
    assert calls == ["sync"]


@pytest.mark.django_db(transaction=True)
def test_run_workflow_drafts_and_announces(org, world, temporal_env):
    from tutortrack.core.workflows import start_now, workflow_id

    set_learning(org, progress_schedule="monthly")
    today = taught_last_month(org, world)
    wid = workflow_id("progress-reports", org.pk, "test")
    with tenant_context(org):
        start_now(
            ProgressReportRunWorkflow,
            ProgressRunInput(organisation_id=str(org.pk), on=today.isoformat()),
            id=wid,
        )
    assert temporal_env.result(wid) == "drafted:1"
    with tenant_context(org):
        assert ProgressReport.objects.get().author_id == world["tutor"].pk
        assert Message.objects.filter(type_key="progress_reports_drafted").exists()
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "ProgressReportRunWorkflow-drafted.json").write_text(
            temporal_env.history_json(wid)
        )


@pytest.mark.django_db(transaction=True)
def test_schedule_follows_the_setting(org, temporal_local_env):
    with tenant_context(org):
        set_learning(org, progress_schedule="termly")
        sid = progress_schedule.sync_schedule()
        assert ScheduleLink.objects.filter(schedule_id=sid).exists()
        set_learning(org, progress_schedule="none")
        assert progress_schedule.sync_schedule() == ""
        assert not ScheduleLink.objects.filter(schedule_id=sid).exists()


def test_progress_run_history_replays():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("ProgressReportRunWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ProgressReportRunWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
