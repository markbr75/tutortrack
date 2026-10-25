"""Gap G3 workflows: the invoice run's tutor review step (FR-10-3) and the monthly
statement run (FR-10-9), with recorded replay histories."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.billing import services, tutor_review
from tutortrack.billing.models import Invoice, InvoiceRun, TutorInvoiceReview
from tutortrack.billing.processes import (
    InvoiceRunWorkflow,
    StatementRunInput,
    StatementRunWorkflow,
    run_workflow_id,
)
from tutortrack.billing.tests.test_workflows import local_today, settings_for, wait_for
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.people.tests.factories import (
    ClientFactory,
    ContactFactory,
    StudentFactory,
    TutorProfileFactory,
)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def tutored_charge(org):
    """An ad hoc charge with a tutor (so the tutor is asked to check it)."""
    with tenant_context(org):
        client = ClientFactory(organisation=org, display_name="The Patels")
        contact = ContactFactory(organisation=org, client=client, email="priya@example.com")
        client.billing_contact = contact
        client.save()
        student = StudentFactory(organisation=org, client=client)
        tutor = TutorProfileFactory(organisation=org, status="active")
        charge = services.create_ad_hoc_charge(
            client=client, student=student, description="Tuition", unit_price=Money("40.00", "GBP")
        )
        charge.kind = "lesson"
        charge.tutor = tutor
        charge.save(update_fields=["kind", "tutor"])
    return client, tutor


def start_run(org):
    today = local_today(org)
    with transaction.atomic(), tenant_context(org):
        run, _ = services.create_run(period_start=today - timedelta(days=7), period_end=today)
    return run


def wait_for_review(org, run):
    wait_for(org, lambda: TutorInvoiceReview.objects.filter(invoice_run=run).exists())


def test_issuing_waits_for_tutors_then_ends_early(org, temporal_env):
    settings_for(
        org,
        {"billing.review_days": 0, "billing.tutor_review": True, "billing.tutor_review_days": 5},
    )
    tutored_charge(org)
    run = start_run(org)
    wait_for_review(org, run)
    with tenant_context(org):
        assert Invoice.objects.get().status == "draft"
        review = TutorInvoiceReview.objects.get()
        tutor_review.confirm(review)  # last answer: signal "tutors_done" after commit
    assert temporal_env.result(run_workflow_id(org.pk, run.pk)) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        assert Invoice.objects.get().status == "issued"
    assert run.stats["issued"] == 1


def test_flagged_drafts_are_held_when_the_window_ends(org, temporal_env):
    settings_for(
        org,
        {"billing.review_days": 0, "billing.tutor_review": True, "billing.tutor_review_days": 2},
    )
    tutored_charge(org)
    run = start_run(org)
    wait_for_review(org, run)
    with tenant_context(org):
        tutor_review.flag(TutorInvoiceReview.objects.get(), comment="Wrong date")
    assert temporal_env.result(run_workflow_id(org.pk, run.pk)) == "completed"
    with tenant_context(org):
        run.refresh_from_db()
        assert Invoice.objects.get().status == "draft"
    assert run.stats["held"] == 1
    assert run.stats["issued"] == 0
    assert run.status == InvoiceRun.Status.COMPLETED


def test_statement_run_emails_last_months_statements(org, temporal_env):
    settings_for(org, {})
    client, _tutor = tutored_charge(org)
    with transaction.atomic(), tenant_context(org):
        invoice = services.issue_invoice(services.create_draft(client), send=False)
        # Back-date the ledger entry into last month (the statement period).
        from tutortrack.billing.models import ClientLedgerEntry

        entry = ClientLedgerEntry.objects.get(ref_id=str(invoice.pk))
        last_month = services.org_today().replace(day=1) - timedelta(days=3)
        from datetime import datetime, time
        from zoneinfo import ZoneInfo

        moment = datetime.combine(last_month, time(12, 0), tzinfo=ZoneInfo(org.timezone))
        ClientLedgerEntry.objects.filter(pk=entry.pk).update(occurred_at=moment)
    mail.outbox.clear()
    from tutortrack.core.workflows import start_now, workflow_id

    wid = workflow_id("client-statements", org.pk, "test")
    with tenant_context(org):
        start_now(StatementRunWorkflow, StatementRunInput(organisation_id=str(org.pk)), id=wid)
    assert temporal_env.result(wid) == "sent:1"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].attachments
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "StatementRunWorkflow-sent.json").write_text(temporal_env.history_json(wid))


def test_record_tutor_review_history_if_requested(org, temporal_env):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    settings_for(
        org,
        {"billing.review_days": 0, "billing.tutor_review": True, "billing.tutor_review_days": 3},
    )
    tutored_charge(org)
    run = start_run(org)
    wait_for_review(org, run)
    with tenant_context(org):
        tutor_review.confirm(TutorInvoiceReview.objects.get())
    rid = run_workflow_id(org.pk, run.pk)
    temporal_env.result(rid)
    (HISTORIES / "InvoiceRunWorkflow-tutor-review.json").write_text(temporal_env.history_json(rid))
    dispatch_batch()


@pytest.mark.parametrize(
    ("prefix", "workflows"),
    [
        ("InvoiceRunWorkflow-tutor-review", "run"),
        ("StatementRunWorkflow", "statement"),
    ],
)
def test_g3_histories_replay(prefix, workflows):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[InvoiceRunWorkflow, StatementRunWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
