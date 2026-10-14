"""E29-TW1: privacy workflows on Temporal (DSAR, erasure, retention purge, lone working)."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.workflows import start_now
from tutortrack.people.models import Student
from tutortrack.people.tests.factories import StudentFactory
from tutortrack.privacy import dsar, holds, lone_working, retention
from tutortrack.privacy.models import DataSubjectRequest, ErasureRecord, LoneWorkingVisit
from tutortrack.privacy.processes import (
    DataSubjectRequestWorkflow,
    ErasureWorkflow,
    LoneWorkingWorkflow,
    RequestInput,
    RetentionInput,
    RetentionPurgeWorkflow,
    dsar_workflow_id,
    erasure_workflow_id,
    lone_working_workflow_id,
)
from tutortrack.privacy.tests.test_lone_working_children import lesson_for, lone_working_on

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def wait_for(org, check: Callable[[], bool], seconds: float = 30) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def running(workflow_id: str) -> Callable[[], bool]:
    from tutortrack.core.models import WorkflowLink

    return lambda: WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


def status_is(request_id, status: str) -> Callable[[], bool]:
    return lambda: DataSubjectRequest.objects.get(pk=request_id).status == status


def _requested(org, family, **kwargs):
    defaults = {
        "kind": "access",
        "subject_type": "people.student",
        "subject_id": str(family.student.pk),
        "requester_name": "Priya Patel",
        "requester_email": "priya@example.com",
        "relationship": "parent",
    }
    with tenant_context(org), transaction.atomic():
        request = dsar.log_request(**{**defaults, **kwargs})
    dispatch_batch()  # data_request.received → DataSubjectRequestWorkflow
    wid = dsar_workflow_id(org.pk, request.pk)
    wait_for(org, running(wid))
    return request, wid


def _verify(org, request):
    with tenant_context(org), transaction.atomic():
        dsar.update_checks(
            DataSubjectRequest.objects.get(pk=request.pk),
            {"identity": True, "matches_records": True, "authority": True},
        )


def test_an_access_request_is_compiled_reviewed_delivered_and_expires(
    org, family, owner, s3, temporal_env
):
    request, wid = _requested(org, family)
    _verify(org, request)
    wait_for(org, status_is(request.pk, "in_review"))
    with tenant_context(org), transaction.atomic():
        dsar.approve_redactions(DataSubjectRequest.objects.get(pk=request.pk), user=owner)
    assert temporal_env.result(wid) == "completed"
    with tenant_context(org):
        done = DataSubjectRequest.objects.get(pk=request.pk)
        assert done.delivered_at is not None
        assert done.status == "completed"
        assert done.token_hash == ""
    record(temporal_env, wid, "DataSubjectRequestWorkflow-delivered")


def test_unverified_requests_get_escalating_reminders_until_closed(
    org, family, owner, temporal_env
):
    request, wid = _requested(org, family)
    temporal_env.skip(timedelta(days=31))
    wait_for(org, lambda: len(DataSubjectRequest.objects.get(pk=request.pk).reminders_sent) == 3)
    with tenant_context(org), transaction.atomic():
        dsar.close(
            DataSubjectRequest.objects.get(pk=request.pk),
            status="cancelled",
            reason="Withdrawn by the requester",
        )
    assert temporal_env.result(wid) == "cancelled"
    with tenant_context(org):
        sent = DataSubjectRequest.objects.get(pk=request.pk).reminders_sent
    assert [s.split(":")[1] for s in sent] == ["7", "2", "0"]
    record(temporal_env, wid, "DataSubjectRequestWorkflow-reminded")


def test_an_approved_erasure_request_erases_across_the_apps(org, family, owner, temporal_env):
    request, wid = _requested(org, family, kind="erasure")
    _verify(org, request)
    wait_for(org, status_is(request.pk, "in_review"))
    with tenant_context(org), transaction.atomic():
        dsar.approve_erasure(DataSubjectRequest.objects.get(pk=request.pk), user=owner)
    assert temporal_env.result(wid) == "completed"
    with tenant_context(org):
        assert Student.objects.get(pk=family.student.pk).first_name.startswith("Erased Student")
        erased = ErasureRecord.objects.get(request_id=request.pk)
        assert erased.status == "completed"
        assert "people" in erased.steps_done
        assert "logins" in erased.steps_done
    record(temporal_env, wid, "DataSubjectRequestWorkflow-erased")
    record(temporal_env, erasure_workflow_id(org.pk, request.pk), "ErasureWorkflow-completed")


def test_a_legal_hold_blocks_the_erasure_workflow(org, family, owner, temporal_env):
    with tenant_context(org), transaction.atomic():
        request = dsar.log_request(
            kind="erasure",
            subject_type="people.student",
            subject_id=str(family.student.pk),
            requester_name="Priya Patel",
        )
        holds.place(
            subject_type="people.client",
            subject_id=str(family.client.pk),
            reason="Fee dispute",
            user=owner,
        )
    wid = f"erasure-test:{org.pk}:{request.pk}"
    start_now(
        ErasureWorkflow,
        RequestInput(organisation_id=str(org.pk), request_id=str(request.pk)),
        id=wid,
    )
    assert temporal_env.result(wid) == "blocked"
    with tenant_context(org):
        assert ErasureRecord.objects.get(request_id=request.pk).status == "blocked"
        assert Student.objects.get(pk=family.student.pk).first_name == "Arjun"
    record(temporal_env, wid, "ErasureWorkflow-blocked")


def test_the_retention_purge_reports_then_purges(org, owner, temporal_env):
    from tutortrack.core.time import now

    old = StudentFactory(organisation=org, first_name="Old")
    with tenant_context(org), transaction.atomic():
        Student.objects.filter(pk=old.pk).update(archived_at=now() - timedelta(days=365 * 7))
        run = retention.start_run(dry_run=False, trigger="manual", user=owner)
    wid = f"retention-purge:{org.pk}:manual-test"
    start_now(
        RetentionPurgeWorkflow,
        RetentionInput(organisation_id=str(org.pk), run_id=str(run.pk)),
        id=wid,
    )
    assert temporal_env.result(wid) == "purged:1"
    with tenant_context(org):
        assert Student.objects.get(pk=old.pk).first_name.startswith("Erased Student")
        run.refresh_from_db()
        assert run.status == "completed"
        assert run.report["archived_students"]["done"] == 1
    record(temporal_env, wid, "RetentionPurgeWorkflow-purged")


def test_the_scheduled_purge_does_nothing_while_switched_off(org, temporal_env):
    wid = f"retention-purge:{org.pk}:scheduled-test"
    start_now(RetentionPurgeWorkflow, RetentionInput(organisation_id=str(org.pk)), id=wid)
    assert temporal_env.result(wid) == "off"
    record(temporal_env, wid, "RetentionPurgeWorkflow-off")


def test_a_missed_check_out_alerts_then_escalates_until_resolved(
    org, family, tutor, owner, temporal_env
):
    lone_working_on(org)
    lesson = lesson_for(org, tutor, family.student, starts_in=timedelta(hours=-3))
    with tenant_context(org), transaction.atomic():
        visit = lone_working.check_in(user=tutor.membership.user, lesson_id=lesson.pk)
    dispatch_batch()  # lone_working.checked_in → LoneWorkingWorkflow
    wid = lone_working_workflow_id(org.pk, visit.pk)
    wait_for(org, running(wid))
    temporal_env.skip(timedelta(hours=1))
    wait_for(org, lambda: LoneWorkingVisit.objects.get(pk=visit.pk).escalated_at is not None)
    with tenant_context(org), transaction.atomic():
        lone_working.resolve(LoneWorkingVisit.objects.get(pk=visit.pk), user=owner, note="Safe")
    assert temporal_env.result(wid) == "resolved"
    record(temporal_env, wid, "LoneWorkingWorkflow-escalated")


def test_checking_out_ends_the_lone_working_timer(org, family, tutor, temporal_env):
    lone_working_on(org)
    lesson = lesson_for(org, tutor, family.student, starts_in=timedelta(minutes=10))
    with tenant_context(org), transaction.atomic():
        visit = lone_working.check_in(user=tutor.membership.user, lesson_id=lesson.pk)
    dispatch_batch()
    wid = lone_working_workflow_id(org.pk, visit.pk)
    wait_for(org, running(wid))
    with tenant_context(org), transaction.atomic():
        lone_working.check_out(user=tutor.membership.user, lesson_id=lesson.pk)
    dispatch_batch()  # lone_working.checked_out → signal "checked_out"
    assert temporal_env.result(wid) == "checked_out"
    with tenant_context(org):
        assert LoneWorkingVisit.objects.get(pk=visit.pk).alerted_at is None
    record(temporal_env, wid, "LoneWorkingWorkflow-checked-out")


@pytest.mark.parametrize(
    "prefix",
    [
        "DataSubjectRequestWorkflow",
        "ErasureWorkflow",
        "RetentionPurgeWorkflow",
        "LoneWorkingWorkflow",
    ],
)
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[
            DataSubjectRequestWorkflow,
            ErasureWorkflow,
            RetentionPurgeWorkflow,
            LoneWorkingWorkflow,
        ],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
