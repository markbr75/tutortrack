"""Gap G3: auto-pay N days before the due date (FR-11-3) in ``PaymentCollectionWorkflow``,
with a recorded replay history."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from tutortrack.core.context import tenant_context
from tutortrack.core.models import WorkflowLink
from tutortrack.payments import services
from tutortrack.payments.models import Payment
from tutortrack.payments.processes import (
    DisputeWorkflow,
    PaymentCollectionWorkflow,
    collect_workflow_id,
)
from tutortrack.payments.tests.test_workflows import autopay_invoice, fake  # noqa: F401
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def before_due(org, days=3):
    with tenant_context(org):
        settings_service.update_settings(
            "payments",
            {"payments.autopay_timing": "before_due", "payments.autopay_days_before_due": days},
        )


def test_autopay_waits_until_days_before_due(org, temporal_env):
    before_due(org)
    invoice = autopay_invoice(org, "pm_card_visa")  # due in the client's 14 days by default
    wid = collect_workflow_id(org.pk, invoice.pk)
    with tenant_context(org):
        assert not Payment.objects.exists()
    assert temporal_env.result(wid) == "succeeded"
    with tenant_context(org):
        payment = Payment.objects.get()
        invoice.refresh_from_db()
        link = WorkflowLink.objects.get(workflow_id=wid)
    assert invoice.status == "paid"
    assert payment.source == "auto_pay"
    assert link.status == "completed"
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "PaymentCollectionWorkflow-before-due.json").write_text(
            temporal_env.history_json(wid)
        )


def test_collect_now_skips_the_wait(org, temporal_env):
    before_due(org, days=1)
    invoice = autopay_invoice(org, "pm_card_visa")
    wid = collect_workflow_id(org.pk, invoice.pk)
    handle = temporal_env.handle(wid)
    for _ in range(80):  # until the workflow is waiting for its date
        if temporal_env.run(handle.query(PaymentCollectionWorkflow.state)).get("waiting"):
            break
    with tenant_context(org):
        services.start_collection(invoice)  # "Collect now": signals instead of refusing
    assert temporal_env.result(wid) == "succeeded"


def test_autopay_on_issue_is_unchanged(org, temporal_env):
    invoice = autopay_invoice(org, "pm_card_visa")
    assert temporal_env.result(collect_workflow_id(org.pk, invoice.pk)) == "succeeded"


def test_before_due_history_replays():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("PaymentCollectionWorkflow-*.json"))
    assert any("before-due" in f.name for f in files), "record with RECORD_WORKFLOW_HISTORIES=1"
    replayer = Replayer(
        workflows=[PaymentCollectionWorkflow, DisputeWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_due_dates_too_close_collect_at_once(org):
    before_due(org, days=30)
    with tenant_context(org):
        today = services.billing.org_today()
        assert services.autopay_date((today + timedelta(days=14)).isoformat()) == ""
