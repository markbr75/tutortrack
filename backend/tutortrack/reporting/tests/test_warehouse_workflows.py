"""E26-T09: ``WarehouseExportWorkflow``: an export started from "Export now", a warehouse
that keeps failing (the run is marked failed after retries), a skipped run, and replay."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.db import transaction

from tutortrack.core import entitlements
from tutortrack.core.context import tenant_context
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.reporting.warehouse import services
from tutortrack.reporting.warehouse.destinations import FakeDestination
from tutortrack.reporting.warehouse.models import WarehouseDestination, WarehouseExport
from tutortrack.reporting.warehouse.processes import WarehouseExportWorkflow

from .test_warehouse import Entitlements

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
RECORD = bool(os.environ.get("RECORD_WORKFLOW_HISTORIES"))


@pytest.fixture(autouse=True)
def enterprise(monkeypatch):
    monkeypatch.setattr(entitlements, "_resolver", Entitlements())
    FakeDestination.reset()
    yield
    FakeDestination.reset()


def destination(org) -> tuple[WarehouseDestination, Any]:
    with tenant_context(org):
        user = MembershipFactory(organisation=org, role="finance").user
        TutorProfileFactory(organisation=org, status="active")
        with transaction.atomic():
            found = services.save_destination(
                None,
                name="BigQuery",
                kind="bigquery",
                config={"project": "bright-minds-1", "dataset": "tt"},
                credentials={"client_email": "x@y.iam.gserviceaccount.com", "private_key": "k"},
                datasets=["dim_tutor"],
            )
    return found, user


def run(org, found, user) -> str:
    with tenant_context(org), transaction.atomic():
        return services.run_now(found, user=user)


def test_export_now_runs_the_workflow(org, temporal_env):
    found, user = destination(org)
    wid = run(org, found, user)
    assert temporal_env.result(wid) == "exported:1"
    with tenant_context(org):
        export = WarehouseExport.objects.get()
    assert (export.status, export.row_count, export.requested_by_id) == ("succeeded", 1, user.pk)
    assert len(FakeDestination.written[str(found.pk)]["dim_tutor"]) == 1
    if RECORD:
        (HISTORIES / "WarehouseExportWorkflow-exported.json").write_text(
            temporal_env.history_json(wid)
        )


def test_a_failing_warehouse_marks_the_run_failed(org, temporal_env):
    found, user = destination(org)
    FakeDestination.fail_next = 100
    wid = run(org, found, user)
    temporal_env.skip(timedelta(hours=3))  # the retry backoff
    assert temporal_env.result(wid, timeout=120) == "failed"
    with tenant_context(org):
        export = WarehouseExport.objects.get()
        found.refresh_from_db()
    assert export.status == "failed"
    assert "unavailable" in export.error
    assert found.last_status == "failed"
    if RECORD:
        (HISTORIES / "WarehouseExportWorkflow-failed.json").write_text(
            temporal_env.history_json(wid)
        )


def test_without_the_feature_the_run_is_skipped(org, temporal_env, monkeypatch):
    found, user = destination(org)
    wid = run(org, found, user)
    monkeypatch.setattr(entitlements, "_resolver", Entitlements("warehouse_export"))
    assert temporal_env.result(wid) == "skipped:not_entitled"


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("WarehouseExportWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[WarehouseExportWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
