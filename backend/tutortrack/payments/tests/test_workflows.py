"""E11-TW1: payment collection (auto-pay) and dispute workflows."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.billing import services as billing
from tutortrack.billing.models import Invoice
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.money import Money
from tutortrack.payments import services
from tutortrack.payments.models import AccountRoute, Payment, PaymentAttempt, ProviderAccount
from tutortrack.payments.processes import (
    DisputeWorkflow,
    PaymentCollectionWorkflow,
    collect_workflow_id,
)
from tutortrack.payments.providers import get_provider
from tutortrack.payments.providers.base import MethodDetails
from tutortrack.people.tests.factories import ClientFactory, StudentFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture(autouse=True)
def fake():
    get_provider.cache_clear()
    yield get_provider("stripe")
    get_provider.cache_clear()


def autopay_invoice(org, method_ref: str) -> Invoice:
    """An auto-pay client whose invoice is issued; the bridge starts collection."""
    kind = "bacs_debit" if "debit" in method_ref else "card"
    with tenant_context(org):
        settings_service.update_settings(
            "billing", {"billing.auto_send": False, "billing.reminders_enabled": False}
        )
        account, _ = ProviderAccount.objects.get_or_create(
            provider="stripe", account_ref="acct_wf", defaults={"status": "active"}
        )
        AccountRoute.objects.get_or_create(
            provider="stripe", account_ref="acct_wf", defaults={"organisation_id": org.pk}
        )
        client = ClientFactory(organisation=org)
        student = StudentFactory(organisation=org, client=client)
        with transaction.atomic():
            method = services.save_method(client, account, MethodDetails(method_ref, kind))
            services.give_consent(client, method, ip_address=None, user_agent="")
            billing.create_ad_hoc_charge(
                client=client, student=student, description="Tuition",
                unit_price=Money(Decimal("40.00"), "GBP"),
            )  # fmt: skip
            invoice = billing.issue_invoice(billing.create_draft(client), send=False)
    dispatch_batch()  # invoice.issued → PaymentCollectionWorkflow
    return invoice


def events(org, kind):
    with tenant_context(org):
        return [e.payload["data"] for e in OutboxEvent.objects.filter(event_type=kind)]


def test_card_collected_on_issue(org, temporal_env):
    invoice = autopay_invoice(org, "pm_card_visa")
    assert temporal_env.result(collect_workflow_id(org.pk, invoice.pk)) == "succeeded"
    with tenant_context(org):
        invoice.refresh_from_db()
        payment = Payment.objects.get()
    assert (invoice.status, payment.source) == ("paid", "auto_pay")


def test_declined_card_retries_then_tells_staff(org, temporal_env):
    invoice = autopay_invoice(org, "pm_fail_card")
    assert temporal_env.result(collect_workflow_id(org.pk, invoice.pk)) == "failed"
    with tenant_context(org):
        assert PaymentAttempt.objects.filter(invoice=invoice).count() == 3  # now, +3d, +5d
    failures = events(org, "payment.failed")
    assert [f["attempt"] for f in failures] == [1, 2, 3]
    assert [f["final"] for f in failures] == [False, False, True]


def test_direct_debit_waits_for_confirmation(org, temporal_env, client):
    invoice = autopay_invoice(org, "pm_debit_bacs")
    wid = collect_workflow_id(org.pk, invoice.pk)
    handle = temporal_env.handle(wid)
    for _ in range(100):  # until the debit has been submitted
        with tenant_context(org):
            payment = Payment.objects.filter(status="pending").first()
        if payment is not None:
            break
        temporal_env.run(handle.query(PaymentCollectionWorkflow.state))
    assert payment is not None
    with tenant_context(org):
        services.confirm_pending(payment)  # as the webhook does
    dispatch_batch()  # invoice.paid → the workflow hears it and finishes
    assert temporal_env.result(wid) == "succeeded"
    with tenant_context(org):
        invoice.refresh_from_db()
    assert invoice.status == "paid"


@pytest.mark.parametrize("prefix", ["PaymentCollectionWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
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


def test_record_histories_if_requested(org, temporal_env):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    invoice = autopay_invoice(org, "pm_fail_card")
    wid = collect_workflow_id(org.pk, invoice.pk)
    temporal_env.result(wid)
    (HISTORIES / "PaymentCollectionWorkflow-retried.json").write_text(
        temporal_env.history_json(wid)
    )
