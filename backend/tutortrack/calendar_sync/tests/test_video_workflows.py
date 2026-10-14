"""E22-T10: ``RecordingFetchWorkflow`` asks the provider for recordings after the lesson
(15 minutes, 1 hour, 6 hours, 24 hours), stops when one arrives, and replays."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.calendar_sync import meetings
from tutortrack.calendar_sync.models import LessonRecording, OnlineMeeting
from tutortrack.calendar_sync.video_processes import (
    RecordingFetchWorkflow,
    recordings_workflow_id,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.delivery import services as delivery
from tutortrack.integrations.providers import fake
from tutortrack.tenancy.settings_service import update_settings

from .conftest import connect, make_lesson, settle, slot

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
RECORD = bool(os.environ.get("RECORD_WORKFLOW_HISTORIES"))


def finished_zoom_lesson(org, people):
    with tenant_context(org), transaction.atomic():
        update_settings(
            "integrations",
            {"integrations.video_provider": "zoom", "integrations.zoom_recording": "cloud"},
        )
    connect(org, people["user"], provider="zoom")
    settle(org)
    lesson = make_lesson(org, people, start=slot(days=-1), online=True)
    with tenant_context(org):
        meetings.reconcile(lesson.pk)
    settle(org)
    with tenant_context(org), transaction.atomic():
        delivery.complete_lesson(lesson)
    return lesson


def test_recordings_are_fetched_after_the_lesson(org, people, temporal_env):
    lesson = finished_zoom_lesson(org, people)
    with tenant_context(org):
        external = OnlineMeeting.objects.get(lesson=lesson).external_id
    fake.add_recording("zoom", external, "rec-1", started_at=lesson.start)
    dispatch_batch()  # lesson.completed → RecordingFetchWorkflow
    wid = recordings_workflow_id(org.pk, lesson.pk)
    assert temporal_env.result(wid) == "found:1"
    with tenant_context(org):
        assert LessonRecording.objects.filter(lesson=lesson).count() == 1
    if RECORD:
        (HISTORIES / "RecordingFetchWorkflow-found.json").write_text(temporal_env.history_json(wid))


def test_gives_up_after_a_day_without_recordings(org, people, temporal_env):
    lesson = finished_zoom_lesson(org, people)
    dispatch_batch()
    wid = recordings_workflow_id(org.pk, lesson.pk)
    assert temporal_env.result(wid) == "found:0"
    if RECORD:
        (HISTORIES / "RecordingFetchWorkflow-none.json").write_text(temporal_env.history_json(wid))


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("RecordingFetchWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[RecordingFetchWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
