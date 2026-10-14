"""E09-T09: ``LessonFeedbackWorkflow`` on Temporal (send after the delay, end when answered,
expire unanswered requests), plus replay of recorded histories."""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.time import now
from tutortrack.delivery import feedback, services
from tutortrack.delivery.models import LessonFeedback
from tutortrack.delivery.processes import LessonFeedbackWorkflow, feedback_workflow_id
from tutortrack.people.tests.factories import ContactFactory
from tutortrack.tenancy import settings_service

from .test_delivery import lesson_at, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def setup_surveys(org, people, delay_hours):  # noqa: F811
    contact = ContactFactory(organisation=org, client=people["client"], email="p@example.com")
    with tenant_context(org):
        settings_service.update_settings(
            "delivery",
            {
                "delivery.feedback_enabled": True,
                "delivery.feedback_delay_hours": delay_hours,
                "delivery.feedback_every_n_lessons": 1,
                "delivery.report_required": False,
            },
        )
    return contact


def complete(org, people):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
    dispatch_batch()  # lesson.completed → the bridge starts LessonFeedbackWorkflow
    return lesson


def wait_for_request(org, lesson) -> LessonFeedback:
    for _ in range(100):
        with tenant_context(org):
            found = LessonFeedback.objects.filter(lesson=lesson).first()
        if found is not None:
            return found
        time.sleep(0.1)
    raise AssertionError("no feedback request was sent")


def test_feedback_is_sent_and_the_answer_ends_the_workflow(org, people, temporal_env):  # noqa: F811
    setup_surveys(org, people, delay_hours=0)
    lesson = complete(org, people)
    item = wait_for_request(org, lesson)
    with tenant_context(org):
        feedback.answer(feedback.token_for(item), rating=5)
    dispatch_batch()  # lesson_feedback.received → signal "answered"
    assert temporal_env.result(feedback_workflow_id(org.pk, lesson.pk)) == "answered:1/1"
    with tenant_context(org):
        assert LessonFeedback.objects.get(pk=item.pk).status == "answered"


def test_unanswered_feedback_expires(org, people, temporal_env):  # noqa: F811
    setup_surveys(org, people, delay_hours=2)
    lesson = complete(org, people)
    # The time-skipping server jumps over the delay and the 7-day expiry.
    assert temporal_env.result(feedback_workflow_id(org.pk, lesson.pk)) == "answered:0/1"
    with tenant_context(org):
        assert LessonFeedback.objects.get(lesson=lesson).status == "expired"


def test_no_workflow_when_surveys_are_off(org, people, temporal_env):  # noqa: F811
    from tutortrack.core.models import WorkflowLink

    lesson = complete(org, people)
    with tenant_context(org):
        wid = feedback_workflow_id(org.pk, lesson.pk)
        assert not WorkflowLink.objects.filter(workflow_id=wid).exists()


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


def test_record_histories_if_requested(org, people, temporal_env):  # noqa: F811
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    test_unanswered_feedback_expires(org, people, temporal_env)
    with tenant_context(org):
        lesson_id = LessonFeedback.objects.get().lesson_id
    wid = feedback_workflow_id(org.pk, lesson_id)
    (HISTORIES / "LessonFeedbackWorkflow-expired.json").write_text(temporal_env.history_json(wid))
