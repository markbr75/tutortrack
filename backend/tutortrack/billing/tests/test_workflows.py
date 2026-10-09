"""E10-TW1: invoice runs, dunning, payment request reminders and invoicing schedules."""

from __future__ import annotations

import json
import os
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection, transaction

from tutortrack.billing import services
from tutortrack.billing.models import Charge, Invoice, InvoiceRun
from tutortrack.billing.processes import (
    InvoiceDunningWorkflow,
    InvoiceRunWorkflow,
    dunning_workflow_id,
    run_workflow_id,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent, ScheduleLink
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory
from tutortrack.tenancy import settings_service

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


def settings_for(org, values):
    with tenant_context(org):
        settings_service.update_settings("billing", {"billing.auto_send": False, **values})


def start_run(org):
    today = now().date()
    with transaction.atomic(), tenant_context(org):
        run, _ = services.create_run(period_start=today - timedelta(days=7), period_end=today)
    return run


def event_types(org) -> list[str]:
    with tenant_context(org):
        return list(OutboxEvent.objects.values_list("event_type", flat=True))


def test_run_reviews_then_issues(org, temporal_env):
    settings_for(org, {"billing.review_days": 2, "billing.reminders_enabled": False})
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
        {"billing.auto_issue": False, "billing.review_days": 0, "billing.reminders_enabled": False},
    )
    charged_client(org)
    run = start_run(org)
    handle = temporal_env.handle(run_workflow_id(org.pk, run.pk))
    for _ in range(50):  # until the drafts exist
        with tenant_context(org):
            run.refresh_from_db()
        if run.status == InvoiceRun.Status.REVIEW:
            break
        temporal_env.run(handle.query(InvoiceRunWorkflow.state))
    with tenant_context(org):
        assert Invoice.objects.get().status == "draft"
        services.approve_run(run)  # signal "approve" after commit
    assert temporal_env.result(run_workflow_id(org.pk, run.pk)) == "completed"
    with tenant_context(org):
        assert Invoice.objects.get().status == "issued"


def test_dunning_sends_each_reminder_once_and_stops_when_paid(org, temporal_env):
    settings_for(org, {"billing.reminder_offsets": [-3, 0, 7]})
    client = charged_client(org)
    with transaction.atomic(), tenant_context(org):
        invoice = services.issue_invoice(services.create_draft(client))
    dispatch_batch()  # invoice.issued → start dunning
    wid = dunning_workflow_id(org.pk, invoice.pk)
    assert temporal_env.result(wid) == "sent:3"
    kinds = event_types(org)
    assert kinds.count("invoice.reminder") == 3
    assert kinds.count("invoice.overdue") == 1


def test_paying_closes_dunning(org, temporal_env):
    settings_for(org, {"billing.reminder_offsets": [7, 14]})
    client = charged_client(org)
    # Due dates are absolute: anchor this one to the shared test server's clock.
    server_today = temporal_env.run(temporal_env.env.get_current_time()).date()
    with transaction.atomic(), tenant_context(org):
        draft = services.update_draft(
            services.create_draft(client), due_date=server_today + timedelta(days=30)
        )
        invoice = services.issue_invoice(draft)
    dispatch_batch()
    with transaction.atomic(), tenant_context(org):
        services.allocate_payment(invoice, Money("40.00", "GBP"))
    dispatch_batch()  # invoice.paid → signal "closed"
    assert temporal_env.result(dunning_workflow_id(org.pk, invoice.pk)) == "sent:0"
    assert "invoice.reminder" not in event_types(org)


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


def test_invoice_schedule_follows_settings(org, temporal_local_env):
    from tutortrack.billing.schedules import cron_for, sync_invoice_schedules

    assert cron_for("monthly", 25) == "0 6 25 * *"
    assert cron_for("weekly", 7) == "0 6 * * 0"
    with tenant_context(org):
        settings_service.update_settings(
            "billing", {"billing.invoice_schedule": "monthly", "billing.invoice_day": 25}
        )
        ids = sync_invoice_schedules()
        assert ScheduleLink.objects.filter(schedule_id__in=ids).count() == 1
        settings_service.update_settings("billing", {"billing.invoice_schedule": "manual"})
        sync_invoice_schedules()
        assert not ScheduleLink.objects.exists()


@pytest.mark.parametrize("prefix", ["InvoiceRunWorkflow", "InvoiceDunningWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[InvoiceRunWorkflow, InvoiceDunningWorkflow],
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
    settings_for(org, {"billing.review_days": 1, "billing.reminder_offsets": [0, 7]})
    client = charged_client(org)
    run = start_run(org)
    rid = run_workflow_id(org.pk, run.pk)
    temporal_env.result(rid)
    (HISTORIES / "InvoiceRunWorkflow-issued.json").write_text(temporal_env.history_json(rid))
    dispatch_batch()
    with tenant_context(org):
        invoice = Invoice.objects.get(client=client)
    did = dunning_workflow_id(org.pk, invoice.pk)
    temporal_env.result(did)
    (HISTORIES / "InvoiceDunningWorkflow-reminded.json").write_text(temporal_env.history_json(did))
