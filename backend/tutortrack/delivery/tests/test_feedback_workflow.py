"""E09-T09: ``LessonFeedbackWorkflow``, replaced by the "Lesson feedback request" built-in
workflow in E33 T05 (``test_workflows_builtin_runs.py``): its recorded histories still
replay while runs under way finish."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tutortrack.delivery.processes import LessonFeedbackWorkflow

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("LessonFeedbackWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[LessonFeedbackWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
