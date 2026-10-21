"""Gap batch G5a workflows: ``InterviewWorkflow`` (video link, confirmation, reminder, retry)
and ``ProbationReviewWorkflow`` (reminders, chasing, the ``closed`` signal), with replays of
the recorded histories."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import performance, services
from tutortrack.recruitment.models import Interview, ProbationReview
from tutortrack.recruitment.review_processes import (
    InterviewWorkflow,
    ProbationReviewWorkflow,
    interview_workflow_id,
    probation_workflow_id,
)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
APPLICANT = {
    "first_name": "Nia",
    "last_name": "Okafor",
    "email": "nia@example.com",
    "subjects": "Maths",
    "referees": [{"name": "Dr Ade", "email": "ade@example.com"}],
    "privacy": True,
}


def record(temporal_env: Any, wid: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(wid))


def booked_interview(
    org: Any, temporal_env: Any, suffix: str = "", meeting_url: str = ""
) -> Interview:
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    start = (server_now + timedelta(days=3)).replace(microsecond=0)
    with tenant_context(org):
        admin = MembershipFactory(organisation=org, role="admin").user
        with transaction.atomic():
            opening = services.save_opening(None, title=f"Tutors {suffix}", published=True)
            application = services.apply(opening, {**APPLICANT, "email": f"n{suffix}@x.com"})
            interview, token = services.propose_interview(
                application, interviewer=admin, options=[start], meeting_url=meeting_url
            )
        with transaction.atomic():
            services.book_interview(token, interview.options[0])
    return interview


def test_booked_interview_gets_a_video_link_confirmation_and_reminder(org, temporal_env):
    interview = booked_interview(org, temporal_env)
    dispatch_batch()  # application.interview_booked → InterviewWorkflow
    wid = interview_workflow_id(org.pk, interview.pk)
    assert temporal_env.result(wid) == "video:created,reminded:true"
    with tenant_context(org):
        interview.refresh_from_db()
        assert interview.meeting_url.startswith("http")
        assert interview.video_provider == "builtin"
        kinds = set(Message.objects.values_list("type_key", flat=True))
        email = Message.objects.get(type_key="interview_confirmed")
    assert {"interview_confirmed", "interview_reminder", "staff_interview_booked"} <= kinds
    assert interview.meeting_url in email.body
    record(temporal_env, wid, "InterviewWorkflow-reminded")


def test_meeting_creation_is_retried(org, temporal_env, monkeypatch):
    from tutortrack.calendar_sync import meetings
    from tutortrack.integrations.providers import ProviderError

    real = meetings.create_standalone_meeting
    calls: list[int] = []

    def flaky(**kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise ProviderError("video provider down")
        return real(**kwargs)

    monkeypatch.setattr(meetings, "create_standalone_meeting", flaky)
    interview = booked_interview(org, temporal_env, "retry")
    dispatch_batch()
    assert temporal_env.result(interview_workflow_id(org.pk, interview.pk)).startswith(
        "video:created"
    )
    assert len(calls) == 2


def test_a_link_typed_in_by_hand_is_kept(org, temporal_env, settings):
    interview = booked_interview(
        org, temporal_env, "manual", meeting_url="https://meet.example/abc"
    )
    dispatch_batch()
    assert temporal_env.result(interview_workflow_id(org.pk, interview.pk)).startswith("video:none")
    with tenant_context(org):
        interview.refresh_from_db()
    assert interview.meeting_url == "https://meet.example/abc"


def scheduled_review(org: Any, temporal_env: Any, days: int = 10) -> ProbationReview:
    server_today = temporal_env.run(temporal_env.env.get_current_time()).date()
    with tenant_context(org):
        MembershipFactory(organisation=org, role="admin")
        tutor = TutorProfileFactory(organisation=org, status="active")
        from tutortrack.recruitment import compliance

        due = max(server_today, compliance.today()) + timedelta(days=days)
        with transaction.atomic():
            return performance.schedule_probation(tutor, due_on=due)


def test_probation_review_reminds_then_chases_until_recorded(org, temporal_env):
    review = scheduled_review(org, temporal_env)
    dispatch_batch()  # probation.scheduled → ProbationReviewWorkflow
    wid = probation_workflow_id(org.pk, review.pk)
    assert temporal_env.result(wid) == "unreviewed"
    with tenant_context(org):
        alerts = Message.objects.filter(type_key="staff_probation_review", channel="in_app")
        subjects = " ".join(alerts.values_list("subject", flat=True))
    assert "coming up" in subjects
    assert "due today" in subjects
    assert "overdue" in subjects
    record(temporal_env, wid, "ProbationReviewWorkflow-unreviewed")


def test_recording_the_outcome_ends_the_review_workflow(org, temporal_env):
    review = scheduled_review(org, temporal_env, days=20)
    dispatch_batch()
    with tenant_context(org), transaction.atomic():
        performance.complete_probation(review, outcome="passed", notes="Great")
    dispatch_batch()  # probation.completed → signal "closed"
    wid = probation_workflow_id(org.pk, review.pk)
    assert temporal_env.result(wid) == "reviewed"
    with tenant_context(org):
        assert not Message.objects.filter(type_key="staff_probation_review").exists()
    record(temporal_env, wid, "ProbationReviewWorkflow-reviewed")


@pytest.mark.parametrize("prefix", ["InterviewWorkflow", "ProbationReviewWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[InterviewWorkflow, ProbationReviewWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
