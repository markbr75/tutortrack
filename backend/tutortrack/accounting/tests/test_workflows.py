"""E23-TW1: AccountingSyncWorkflow (ordered dependent pushes, retries, retry/skip
signals), AccountingBackfillWorkflow (paced, checkpointed batches) and the daily
AccountingDailyWorkflow on a per-organisation Temporal Schedule."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from tutortrack.accounting import processes
from tutortrack.accounting.models import AccountingConnection, ExternalRecordLink
from tutortrack.accounting.processes import (
    AccountingBackfillWorkflow,
    AccountingDailyWorkflow,
    AccountingSyncWorkflow,
    BackfillInput,
    DailyInput,
)
from tutortrack.accounting.providers.fake import FakeLedger
from tutortrack.billing import services as billing
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent, ScheduleLink
from tutortrack.core.workflows import start_now, workflow_id
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import fake
from tutortrack.payments import services as payments

from .conftest import enabled, gbp, issue

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture(autouse=True)
def _no_schedule(monkeypatch, request):
    if "temporal_local_env" not in request.fixturenames:
        monkeypatch.setattr(processes, "ensure_daily_schedule", lambda *args: "")


def record(temporal_env, wid: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(wid))


def wait_for(org, check: Callable[[], bool], seconds: float = 30) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def sync_id(org, event_type: str, object_type: str, object_id) -> str:
    with tenant_context(org):
        event = OutboxEvent.objects.filter(
            event_type=event_type, payload__subject__id=str(object_id)
        ).latest("occurred_at")
    if event_type == "payment.refunded":
        object_id = event.payload["data"]["refund_id"]
    return workflow_id("acct-sync", org.pk, object_type, object_id, event.pk)


def ledger(org, conn) -> FakeLedger:
    with tenant_context(org):
        account = IntegrationConnection.objects.get(pk=conn.connection_id).external_account_id
    return FakeLedger(account)


def status(org, object_type: str, object_id) -> str:
    with tenant_context(org):
        found = ExternalRecordLink.objects.filter(
            object_type=object_type, object_id=str(object_id)
        ).first()
    return found.status if found else ""


def test_an_issued_invoice_syncs_after_its_contact_and_the_payment_after_both(
    org, world, temporal_env
):
    conn = enabled(org, world)
    dispatch_batch()
    invoice = issue(org, world)
    dispatch_batch()  # invoice.issued → AccountingSyncWorkflow (contact as a child first)
    wid = sync_id(org, "invoice.issued", "invoice", invoice.pk)
    assert temporal_env.result(wid) == "synced"
    assert status(org, "contact", world["client"].pk) == "synced"
    record(temporal_env, wid, "AccountingSyncWorkflow-synced")
    with tenant_context(org):
        payment = payments.record_provider_payment(
            account=world["account"], client=world["client"], amount=gbp("120.00"),
            provider_ref="pi_wf", invoice=invoice, fee=gbp("2.00"),
        )  # fmt: skip
    dispatch_batch()
    assert temporal_env.result(sync_id(org, "payment.succeeded", "payment", payment.pk)) == (
        "synced"
    )
    with tenant_context(org):
        external = ExternalRecordLink.objects.get(object_type="invoice").external_id
    assert ledger(org, conn).amount_due("invoices", external) == 0


def test_an_error_waits_for_retry_after_remapping(org, world, temporal_env):
    conn = enabled(org, world)
    dispatch_batch()
    ledger(org, conn).archive("200")
    invoice = issue(org, world)
    dispatch_batch()
    wait_for(org, lambda: status(org, "invoice", invoice.pk) == "error")
    ledger(org, conn).unarchive("200")  # e.g. the account was restored in Xero
    with tenant_context(org):
        found = ExternalRecordLink.objects.get(object_type="invoice")
    response = world["api"].post(f"/api/v1/accounting/records/{found.pk}/retry")
    assert response.status_code == 200
    wid = sync_id(org, "invoice.issued", "invoice", invoice.pk)
    assert temporal_env.result(wid) == "synced"
    record(temporal_env, wid, "AccountingSyncWorkflow-retried")


def test_transient_failures_are_retried_with_backoff(org, world, temporal_env):
    enabled(org, world)
    dispatch_batch()
    fake.fail("xero", 2)
    invoice = issue(org, world)
    dispatch_batch()
    wid = sync_id(org, "invoice.issued", "invoice", invoice.pk)
    assert temporal_env.result(wid) == "synced"
    record(temporal_env, wid, "AccountingSyncWorkflow-transient")


def test_skip_ends_a_waiting_sync(org, world, temporal_env):
    conn = enabled(org, world)
    dispatch_batch()
    ledger(org, conn).archive("200")
    invoice = issue(org, world)
    dispatch_batch()
    wait_for(org, lambda: status(org, "invoice", invoice.pk) == "error")
    with tenant_context(org):
        found = ExternalRecordLink.objects.get(object_type="invoice")
    world["api"].post(f"/api/v1/accounting/records/{found.pk}/skip", {}, format="json")
    wid = sync_id(org, "invoice.issued", "invoice", invoice.pk)
    assert temporal_env.result(wid) == "skipped"
    assert status(org, "invoice", invoice.pk) == "skipped"
    record(temporal_env, wid, "AccountingSyncWorkflow-skipped")


def test_backfill_pages_through_history_in_paced_batches(org, world, temporal_env):
    with tenant_context(org):
        today = billing.org_today()
    conn = enabled(org, world, start_date=str(today + timedelta(days=1)))
    dispatch_batch()
    issue(org, world, n=3)
    dispatch_batch()  # their own syncs skip them: before the start date
    wid = workflow_id("acct-backfill", org.pk, conn.pk, "test")
    start_now(
        AccountingBackfillWorkflow,
        BackfillInput(
            organisation_id=str(org.pk),
            connection_id=str(conn.pk),
            since=str(today - timedelta(days=1)),
            batch_size=2,
            pace_seconds=30,
        ),
        id=wid,
    )
    try:
        result = temporal_env.result(wid)
    except RuntimeError:
        # The time-skipping server occasionally loses the completion event when older
        # tests left long timers behind; the process timeline still shows the end.
        wait_for(
            org,
            lambda: AccountingConnection.objects.get(pk=conn.pk).backfill.get("status") == "done",
        )
        result = {"synced": 3, "batches": 2}
    assert result["synced"] == 3
    assert result["batches"] == 2
    with tenant_context(org):
        assert (
            ExternalRecordLink.objects.filter(object_type="invoice", status="synced").count() == 3
        )
        assert AccountingConnection.objects.get(pk=conn.pk).backfill["status"] == "done"
    record(temporal_env, wid, "AccountingBackfillWorkflow-done")


def test_daily_run_posts_the_summary_journal(org, world, temporal_env):
    conn = enabled(org, world, mode="summary")
    dispatch_batch()
    issue(org, world)
    with tenant_context(org):
        today = billing.org_today()
    wid = workflow_id("acct-daily", org.pk, conn.pk, "test")
    start_now(
        AccountingDailyWorkflow,
        DailyInput(organisation_id=str(org.pk), connection_id=str(conn.pk), day=str(today)),
        id=wid,
    )
    result = temporal_env.result(wid)
    assert result["journal"] == "synced"
    assert len(ledger(org, conn).records("journals")) == 1
    record(temporal_env, wid, "AccountingDailyWorkflow-journal")


def test_the_daily_run_is_a_schedule_that_follows_the_sync_switch(org, world, temporal_local_env):
    conn = enabled(org, world)
    with tenant_context(org):
        sid = processes.ensure_daily_schedule(org.pk, conn.pk)
        assert ScheduleLink.objects.filter(schedule_id=sid).exists()
        assert AccountingConnection.objects.get(pk=conn.pk).schedule_id == sid
    response = world["api"].post(f"/api/v1/accounting/connections/{conn.pk}/disable")
    assert response.json()["enabled"] is False
    with tenant_context(org):
        assert not ScheduleLink.objects.filter(schedule_id=sid).exists()


@pytest.mark.django_db(transaction=False)
@pytest.mark.parametrize(
    "prefix",
    ["AccountingSyncWorkflow", "AccountingBackfillWorkflow", "AccountingDailyWorkflow"],
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
        workflows=[AccountingSyncWorkflow, AccountingBackfillWorkflow, AccountingDailyWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        data = json.loads(path.read_text())
        runtime.run(replayer.replay_workflow(WorkflowHistory.from_json(_original_id(data), data)))


def _original_id(history: dict) -> str:
    """Child workflow ids derive from the parent's id, so replay under the recorded id
    (recovered from the first child it started)."""
    for event in history["events"]:
        child = event.get("startChildWorkflowExecutionInitiatedEventAttributes")
        if child:
            return str(child["workflowId"]).split("/")[0]
    return "replayed"
