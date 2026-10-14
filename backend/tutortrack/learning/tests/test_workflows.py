"""E21-TW1: the homework reminder and library loan workflows (timers, signals, retries
and replay of recorded histories)."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.learning import services
from tutortrack.learning.models import HomeworkAssignment, Loan
from tutortrack.learning.processes import (
    HomeworkReminderWorkflow,
    LoanReminderWorkflow,
    homework_workflow_id,
    loan_workflow_id,
)

from .conftest import events_of, set_learning
from .factories import LibraryItemFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def _assign(org, world, temporal_env, *, days=2):
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    with tenant_context(org), transaction.atomic():
        homework = services.assign_homework(
            title="Fractions worksheet",
            due_at=server_now + timedelta(days=days),
            students=[world["student"]],
            set_by=world["tutor"],
        )
        assignment = HomeworkAssignment.objects.get(homework=homework)
    dispatch_batch()  # homework.assigned → HomeworkReminderWorkflow
    return assignment


def test_homework_is_reminded_then_marked_overdue(org, world, temporal_env):
    set_learning(org, homework_reminder_hours=24)
    assignment = _assign(org, world, temporal_env)
    wid = homework_workflow_id(org.pk, assignment.pk, 1)
    assert temporal_env.result(wid) == "overdue"
    with tenant_context(org):
        assignment.refresh_from_db()
        assert assignment.reminded_at is not None
        assert assignment.overdue_at is not None
        assert Message.objects.filter(type_key="homework_reminder").exists()
        assert Message.objects.filter(type_key="homework_overdue").exists()
    assert len(events_of(org, "homework.overdue")) == 1
    record(temporal_env, wid, "HomeworkReminderWorkflow-overdue")


def test_handing_in_ends_the_reminders(org, world, temporal_env):
    assignment = _assign(org, world, temporal_env, days=5)
    with tenant_context(org), transaction.atomic():
        services.submit_homework(HomeworkAssignment.objects.get(pk=assignment.pk), body="done")
    dispatch_batch()  # homework.submitted → signal "changed"
    wid = homework_workflow_id(org.pk, assignment.pk, 1)
    assert temporal_env.result(wid) == "submitted"
    with tenant_context(org):
        assert HomeworkAssignment.objects.get(pk=assignment.pk).overdue_at is None
    record(temporal_env, wid, "HomeworkReminderWorkflow-submitted")


def test_overdue_marking_is_retried(org, world, temporal_env, monkeypatch):
    real = services.mark_homework_overdue
    calls: list[str] = []

    def flaky(assignment_id, **kwargs):
        calls.append(str(assignment_id))
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return real(assignment_id, **kwargs)

    monkeypatch.setattr(services, "mark_homework_overdue", flaky)
    set_learning(org, homework_reminder_hours=0)
    assignment = _assign(org, world, temporal_env, days=1)
    wid = homework_workflow_id(org.pk, assignment.pk, 1)
    assert temporal_env.result(wid) == "overdue"
    assert len(calls) == 2
    assert len(events_of(org, "homework.overdue")) == 1


def _lend(org, world, temporal_env, *, days=5):
    set_learning(org, loan_overdue_notices=1, loan_overdue_notice_days=3)
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    item = LibraryItemFactory(organisation=org)
    with tenant_context(org), transaction.atomic():
        today = server_now.astimezone(services.org_zone()).date()
        loan = services.lend(item, world["student"], due_date=today + timedelta(days=days))
    dispatch_batch()  # loan.created → LoanReminderWorkflow
    return loan


def test_loans_are_reminded_then_chased_when_overdue(org, world, temporal_env):
    loan = _lend(org, world, temporal_env)
    wid = loan_workflow_id(org.pk, loan.pk)
    assert temporal_env.result(wid) == "overdue"
    with tenant_context(org):
        loan = Loan.objects.get(pk=loan.pk)
        assert loan.reminded_at is not None
        assert loan.overdue_at is not None
        assert loan.overdue_notices == 1
        assert Message.objects.filter(type_key="loan_due").exists()
        assert Message.objects.filter(type_key="loan_overdue").count() >= 2
    assert len(events_of(org, "loan.overdue")) == 1
    record(temporal_env, wid, "LoanReminderWorkflow-overdue")


def test_returning_the_item_ends_the_loan_workflow(org, world, temporal_env):
    loan = _lend(org, world, temporal_env, days=10)
    wid = loan_workflow_id(org.pk, loan.pk)
    with tenant_context(org), transaction.atomic():
        services.return_loan(Loan.objects.get(pk=loan.pk))
    dispatch_batch()  # loan.returned → signal "changed"
    assert temporal_env.result(wid) == "returned"
    record(temporal_env, wid, "LoanReminderWorkflow-returned")


@pytest.mark.django_db(transaction=False)
@pytest.mark.parametrize("prefix", ["HomeworkReminderWorkflow", "LoanReminderWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[HomeworkReminderWorkflow, LoanReminderWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
