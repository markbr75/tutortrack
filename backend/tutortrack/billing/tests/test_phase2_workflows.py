"""E10 Phase 2 workflows: PackageExpiryWorkflow (TW1), BillingPlanWorkflow (T13) and the
late-fee/collections steps of InvoiceDunningWorkflow (T14), with replayed histories."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.billing import packages, plans, services
from tutortrack.billing.models import BillingPlan, Charge, Invoice, PackagePurchase
from tutortrack.billing.processes import (
    BillingPlanWorkflow,
    InvoiceDunningWorkflow,
    PackageExpiryWorkflow,
)
from tutortrack.billing.tests.test_billing import events_of, gbp, set_settings
from tutortrack.catalogue.models import PackageTemplate
from tutortrack.core.context import tenant_context
from tutortrack.people.tests.factories import ClientFactory, ContactFactory, StudentFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


@pytest.fixture
def client_(org):
    with tenant_context(org):
        client = ClientFactory(organisation=org, display_name="The Okafors")
        contact = ContactFactory(organisation=org, client=client, email="ada@example.com")
        client.billing_contact = contact
        client.save()
        StudentFactory(organisation=org, client=client)
    set_settings(org, "billing", {"billing.auto_send": False})
    return client


def server_today(temporal_env):
    return temporal_env.run(temporal_env.env.get_current_time()).date()


def active_package(org, client, *, validity_days=5, quantity="4"):
    with tenant_context(org):
        tpl = PackageTemplate.objects.create(
            name="Lessons", quantity_type="lessons", quantity=Decimal(quantity),
            currency="GBP", price_amount=Decimal("100"), validity_days=validity_days,
        )  # fmt: skip
    with tenant_context(org), transaction.atomic():
        purchase = packages.sell_package(client=client, template=tpl)
        invoice = Invoice.objects.get(charges__pk=purchase.charge_id)
        services.allocate_payment(invoice, invoice.balance_due)
        packages.activate_for_invoice(invoice.pk)  # starts the expiry workflow on commit
    with tenant_context(org):
        purchase.refresh_from_db()
    return purchase


def test_package_is_reminded_then_expires(org, client_, temporal_env):
    set_settings(org, "billing", {"billing.package_expiry_reminder_days": 2})
    purchase = active_package(org, client_)
    assert temporal_env.result(purchase.workflow_id) == "expired"
    with tenant_context(org):
        purchase.refresh_from_db()
    assert (purchase.status, purchase.units_expired) == ("expired", 4)
    assert len(events_of(org, "package.expiring")) == 1
    assert len(events_of(org, "package.expired")) == 1


def test_using_up_a_package_stops_its_expiry(org, client_, temporal_env):
    purchase = active_package(org, client_, validity_days=30, quantity="1")
    with tenant_context(org), transaction.atomic():
        from tutortrack.billing.models import PackageConsumption

        packages._move(
            PackagePurchase.objects.select_for_update().get(pk=purchase.pk),
            Decimal(1),
            kind=PackageConsumption.Kind.LESSON,
        )  # signals "depleted" on commit
    assert temporal_env.result(purchase.workflow_id) == "depleted"
    with tenant_context(org):
        purchase.refresh_from_db()
    assert purchase.status == "depleted"


def test_extending_moves_the_deadline(org, client_, temporal_env):
    purchase = active_package(org, client_, validity_days=5)
    until = purchase.expires_at + timedelta(days=20)
    with tenant_context(org):
        packages.extend_package(purchase, until=until)  # signal "extended" on commit
    assert temporal_env.result(purchase.workflow_id) == "expired"
    assert temporal_env.run(temporal_env.env.get_current_time()) >= until


def make_plan(org, client, start, end=None, **kwargs):
    with tenant_context(org), transaction.atomic():
        return plans.create_plan(
            client=client,
            description="Monthly tuition",
            amount=gbp("120.00"),
            interval="monthly",
            start_date=start,
            end_date=end,
            **kwargs,
        )


def test_plan_charges_each_period_until_it_ends(org, client_, temporal_env):
    today = server_today(temporal_env)
    start = today - timedelta(days=35)
    plan = make_plan(org, client_, start, start + timedelta(days=65))
    assert temporal_env.result(plan.workflow_id) == "charged:3"
    with tenant_context(org):
        charges = list(Charge.objects.filter(kind="plan").order_by("date"))
        issued = Invoice.objects.filter(charges__kind="plan", status="issued").count()
    assert [c.gross for c in charges][:2] == [gbp("120.00"), gbp("120.00")]
    assert charges[2].gross < gbp("120.00")  # the last period is prorated
    assert issued == 3


def test_pausing_then_ending_a_plan_charges_nothing(org, client_, temporal_env):
    plan = make_plan(org, client_, server_today(temporal_env) + timedelta(days=10))
    with tenant_context(org):
        plans.set_plan_status(plan, BillingPlan.Status.PAUSED)
    with tenant_context(org):
        plans.set_plan_status(plan, BillingPlan.Status.ENDED)
    assert temporal_env.result(plan.workflow_id) == "charged:0"


REPLAYED = (PackageExpiryWorkflow, BillingPlanWorkflow, InvoiceDunningWorkflow)


@pytest.mark.parametrize(
    "prefix", ["PackageExpiryWorkflow", "BillingPlanWorkflow", "InvoiceDunningWorkflow"]
)
def test_phase2_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=list(REPLAYED), data_converter=data_converter(), workflow_runner=sandbox_runner()
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_record_phase2_histories_if_requested(org, client_, temporal_env):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    set_settings(org, "billing", {"billing.package_expiry_reminder_days": 2})
    purchase = active_package(org, client_)
    temporal_env.result(purchase.workflow_id)
    (HISTORIES / "PackageExpiryWorkflow-expired.json").write_text(
        temporal_env.history_json(purchase.workflow_id)
    )
    start = server_today(temporal_env) - timedelta(days=35)
    plan = make_plan(org, client_, start, start + timedelta(days=65))
    temporal_env.result(plan.workflow_id)
    (HISTORIES / "BillingPlanWorkflow-ended.json").write_text(
        temporal_env.history_json(plan.workflow_id)
    )
    # InvoiceDunningWorkflow-late-fees.json stays as recorded: the Payment chasing built-in
    # workflow replaced it (E33 T04), so nothing starts it any more.
