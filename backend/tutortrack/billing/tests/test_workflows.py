"""E10-TW1: invoice runs."""

from __future__ import annotations

import json
import os
import threading
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection, transaction

from tutortrack.billing import services
from tutortrack.billing.models import Charge, Invoice, InvoiceRun
from tutortrack.billing.processes import (
    InvoiceRunWorkflow,
    run_workflow_id,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory
from tutortrack.tenancy import settings_service


def local_today(org):
    with tenant_context(org):
        return services.org_today()


pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def charged_client(org, amount="40.00"):
    with tenant_context(org):
        client = ClientFactory(organisation=org, display_name="The Patels")
        contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
        client.billing_contact = contact
        client.save()
        student = StudentFactory(organisation=org, client=client)
        services.create_ad_hoc_charge(
            client=client, student=student, description="Tuition", unit_price=Money(amount, "GBP")
        )
    return client


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    """Poll the database while the worker runs activities (time doesn't skip meanwhile)."""
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def settings_for(org, values):
    with tenant_context(org):
        settings_service.update_settings("billing", {"billing.auto_send": False, **values})


def start_run(org):
    today = local_today(org)
    with transaction.atomic(), tenant_context(org):
        run, _ = services.create_run(period_start=today - timedelta(days=7), period_end=today)
    return run


def event_types(org) -> list[str]:
    with tenant_context(org):
        return list(OutboxEvent.objects.values_list("event_type", flat=True))


def test_run_reviews_then_issues(org, temporal_env):
    settings_for(org, {"billing.review_days": 2})
    charged_client(org)
    run = start_run(org)
    assert temporal_env.result(run_workflow_id(org.pk, run.pk)) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        invoice = Invoice.objects.get()
    assert (run.status, run.stats["drafts"], run.stats["issued"]) == ("completed", 1, 1)
    assert (invoice.number, invoice.status) == ("INV-000001", "issued")


def test_run_waits_for_approval_when_auto_issue_is_off(org, temporal_env):
    settings_for(
        org,
        {"billing.auto_issue": False, "billing.review_days": 0},
    )
    charged_client(org)
    run = start_run(org)
    wait_for(  # until the drafts exist
        org, lambda: InvoiceRun.objects.filter(pk=run.pk, status=InvoiceRun.Status.REVIEW).exists()
    )
    with tenant_context(org):
        assert Invoice.objects.get().status == "draft"
        services.approve_run(run)  # signal "approve" after commit
    assert temporal_env.result(run_workflow_id(org.pk, run.pk)) == "completed"
    with tenant_context(org):
        assert Invoice.objects.get().status == "issued"


def test_concurrent_runs_never_invoice_a_charge_twice(org):
    """Two runs racing over the same charges (row locks with SKIP LOCKED)."""
    settings_for(org, {})
    for _ in range(3):
        charged_client(org)
    barrier = threading.Barrier(2)
    results: list[int] = []

    def build() -> None:
        try:
            with tenant_context(org), transaction.atomic():
                barrier.wait(timeout=10)
                results.append(len(services.build_drafts(Charge.objects.all())))
        finally:
            connection.close()

    threads = [threading.Thread(target=build) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with tenant_context(org):
        on_invoices = Charge.objects.filter(invoice__isnull=False).count()
        lines = sum(i.lines.count() for i in Invoice.objects.all())
    assert sum(results) == 3
    assert on_invoices == lines == 3


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("InvoiceRunWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[InvoiceRunWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_record_histories_if_requested(org, temporal_env):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    settings_for(org, {"billing.review_days": 1})
    charged_client(org)
    run = start_run(org)
    rid = run_workflow_id(org.pk, run.pk)
    temporal_env.result(rid)
    (HISTORIES / "InvoiceRunWorkflow-issued.json").write_text(temporal_env.history_json(rid))
