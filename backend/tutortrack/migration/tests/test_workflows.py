"""E28-TW1: ImportWorkflow, MigrationProjectWorkflow and TenantExportWorkflow on Temporal."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.time import now
from tutortrack.migration import services
from tutortrack.migration.models import ExportJob, ImportBatch, MigrationProject
from tutortrack.migration.processes import (
    ImportWorkflow,
    MigrationProjectWorkflow,
    TenantExportWorkflow,
    export_workflow_id,
    import_workflow_id,
    project_workflow_id,
)
from tutortrack.people.models import TutorProfile

from .conftest import make_batch

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
ROWS = [
    {"Email": "a@example.com", "First name": "Ann"},
    {"Email": "b@example.com", "First name": "Bo"},
    {"Email": "broken", "First name": "Cy"},
]


def wait_for(org: Any, check: Callable[[], bool], seconds: float = 30) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def record(temporal_env: Any, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def status(batch_id: Any) -> str:
    return str(ImportBatch.objects.get(pk=batch_id).status)


def submitted(org: Any) -> ImportBatch:
    with tenant_context(org):
        batch = make_batch("tutors", ROWS)
        with transaction.atomic():
            services.submit(batch)
    dispatch_batch()  # import.submitted → ImportWorkflow
    return batch


def confirm(org: Any, batch: ImportBatch) -> None:
    wait_for(org, lambda: status(batch.pk) == "validated")
    with tenant_context(org), transaction.atomic():
        services.confirm(ImportBatch.objects.get(pk=batch.pk))


def test_confirmed_import_is_finalised_when_the_window_closes(org, temporal_env, s3):
    batch = submitted(org)
    confirm(org, batch)
    wid = import_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "finalised"  # the 7-day timer was skipped
    with tenant_context(org):
        batch.refresh_from_db()
        assert batch.status == "finalised"
        assert batch.stats["imported"] == 2
        assert batch.stats["invalid"] == 1
        assert batch.error_file is not None
        assert TutorProfile.objects.count() == 2
    record(temporal_env, wid, "ImportWorkflow-finalised")


def test_rollback_signal_reverts_the_batch(org, temporal_env, s3):
    batch = submitted(org)
    confirm(org, batch)
    wait_for(org, lambda: status(batch.pk) == "completed")
    with tenant_context(org), transaction.atomic():
        services.request_rollback(ImportBatch.objects.get(pk=batch.pk))
    wid = import_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "rolled_back"
    with tenant_context(org):
        assert not TutorProfile.objects.exists()
        assert ImportBatch.objects.get(pk=batch.pk).stats["reverted"] == 2
    record(temporal_env, wid, "ImportWorkflow-rolled-back")


def test_cancel_before_confirming(org, temporal_env, s3):
    batch = submitted(org)
    wait_for(org, lambda: status(batch.pk) == "validated")
    with tenant_context(org), transaction.atomic():
        services.cancel(ImportBatch.objects.get(pk=batch.pk))
    wid = import_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "cancelled"
    with tenant_context(org):
        assert status(batch.pk) == "cancelled"
        assert not TutorProfile.objects.exists()
    record(temporal_env, wid, "ImportWorkflow-cancelled")


def test_a_failing_chunk_is_retried(org, temporal_env, s3, monkeypatch):
    real = services.import_chunk
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database hiccup")
        return real(*args, **kwargs)

    monkeypatch.setattr(services, "import_chunk", flaky)
    batch = submitted(org)
    confirm(org, batch)
    assert temporal_env.result(import_workflow_id(org.pk, batch.pk)) == "finalised"
    assert len(calls) == 2
    with tenant_context(org):
        assert TutorProfile.objects.count() == 2  # no duplicates after the retry


def test_migration_project_steps_wait_for_confirmation(org, user, temporal_env, s3):
    from tutortrack.identity.tests.factories import MembershipFactory

    MembershipFactory(organisation=org, user=user)
    with tenant_context(org), transaction.atomic():
        project = services.create_project(
            user=user, name="From TutorBird", source="tutorbird", cutover_date=now().date()
        )
    dispatch_batch()  # migration_project.started → MigrationProjectWorkflow
    wait_for(
        org,
        lambda: (
            MigrationProject.objects.get(pk=project.pk).steps["people"]["status"] == "in_progress"
        ),
    )
    for step in services.STEP_KEYS:
        wait_for(
            org,
            lambda step=step: (
                MigrationProject.objects.get(pk=project.pk).steps[step]["status"]  # type: ignore[misc]
                == "in_progress"
            ),
        )
        with tenant_context(org), transaction.atomic():
            services.complete_step(
                MigrationProject.objects.get(pk=project.pk), step, skip=step == "payment_methods"
            )
    wid = project_workflow_id(org.pk, project.pk)
    assert temporal_env.result(wid) == "completed"
    with tenant_context(org):
        project.refresh_from_db()
        assert project.status == "completed"
        assert project.reconciliation["ok"]
    record(temporal_env, wid, "MigrationProjectWorkflow-completed")


def test_export_is_built_offered_and_expires(org, temporal_env, s3):
    with tenant_context(org), transaction.atomic():
        job = services.request_export(reason="closure")
    dispatch_batch()  # export.requested → TenantExportWorkflow
    wait_for(org, lambda: ExportJob.objects.get(pk=job.pk).status == "ready", seconds=60)
    wid = export_workflow_id(org.pk, job.pk)
    assert temporal_env.result(wid, timeout=120) == "expired"
    with tenant_context(org):
        job.refresh_from_db()
        assert job.status == "expired"
        assert job.file is not None
        assert job.file.status == "rejected"
    record(temporal_env, wid, "TenantExportWorkflow-expired")


@pytest.mark.parametrize(
    "prefix", ["ImportWorkflow", "MigrationProjectWorkflow", "TenantExportWorkflow"]
)
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    found = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert found, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ImportWorkflow, MigrationProjectWorkflow, TenantExportWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in found:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
