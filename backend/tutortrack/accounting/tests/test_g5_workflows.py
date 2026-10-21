"""Gap batch G5 (E23) through ``AccountingSyncWorkflow``: a branch's own ledger gets its
records and their prerequisites (the ledger is carried to child workflows), and a payment
reallocated after it synced is moved in the ledger by the ``payment.reallocated`` event.
The branch-ledger run is recorded as a replay history."""

from __future__ import annotations

import os

import pytest

from tutortrack.accounting import processes
from tutortrack.accounting.models import ExternalRecordLink
from tutortrack.billing import services as billing
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.workflows import workflow_id
from tutortrack.payments import services as payments

from .conftest import enabled, gbp, issue
from .test_g5_accounting import connect_branch, ledger, map_set, north  # noqa: F401
from .test_workflows import HISTORIES

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_schedule(monkeypatch):
    monkeypatch.setattr(processes, "ensure_daily_schedule", lambda *args: "")


def sync_id(org, event_type: str, object_type: str, object_id) -> str:
    with tenant_context(org):
        event = OutboxEvent.objects.filter(
            event_type=event_type, payload__subject__id=str(object_id)
        ).latest("occurred_at")
    return workflow_id("acct-sync", org.pk, object_type, object_id, event.pk)


def test_a_branch_ledger_syncs_through_the_workflow(org, world, north, temporal_env):  # noqa: F811
    main = enabled(org, world)
    branch_conn = connect_branch(org, world, north["branch"])
    map_set(world, branch_conn.mapping_set)
    response = world["api"].post(f"/api/v1/accounting/connections/{branch_conn.pk}/enable", {})
    assert response.status_code == 200
    dispatch_batch()
    with tenant_context(org):
        billing.create_ad_hoc_charge(
            client=north["client"],
            student=north["student"],
            description="Tuition",
            unit_price=gbp("80.00"),
            tax_rate=None,
        )
        invoice = billing.issue_invoice(billing.create_draft(north["client"]), send=False)
    dispatch_batch()  # invoice.issued → the branch ledger (contact as a child first)
    wid = sync_id(org, "invoice.issued", "invoice", invoice.pk)
    assert temporal_env.result(wid) == "synced"
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "AccountingSyncWorkflow-branch-ledger.json").write_text(
            temporal_env.history_json(wid)
        )
    with tenant_context(org):
        links = ExternalRecordLink.objects.filter(status="synced")
        assert {(x.object_type, x.connection_id) for x in links} == {
            ("contact", branch_conn.pk),
            ("invoice", branch_conn.pk),
        }
    assert len(ledger(branch_conn).records("invoices")) == 1
    assert ledger(main).records("invoices") == []


def test_a_reallocation_event_moves_the_payment_in_the_ledger(org, world, temporal_env):
    conn = enabled(org, world)
    dispatch_batch()
    first, second = issue(org, world, "50.00", vat=False, n=2)
    dispatch_batch()
    for invoice in (first, second):
        assert temporal_env.result(sync_id(org, "invoice.issued", "invoice", invoice.pk)) == (
            "synced"
        )
    with tenant_context(org):
        payment = payments.record_manual_payment(
            client=world["client"],
            amount=gbp("50.00"),
            method="bank_transfer",
            allocations=[(first, gbp("50.00"))],
        )
    dispatch_batch()
    assert temporal_env.result(sync_id(org, "payment.succeeded", "payment", payment.pk)) == (
        "synced"
    )
    with tenant_context(org):
        payments.reallocate(payment, [(second, gbp("50.00"))])
    dispatch_batch()  # the subscriber marks it pending; the bridge starts the sync
    wid = sync_id(org, "payment.reallocated", "reallocation", payment.pk)
    assert temporal_env.result(wid) == "synced"
    with tenant_context(org):
        first.refresh_from_db()
        second.refresh_from_db()
        externals = {
            x.object_id: x.external_id
            for x in ExternalRecordLink.objects.filter(object_type="invoice")
        }
    books = ledger(conn)
    assert books.amount_due("invoices", externals[str(first.pk)]) == first.balance_due.amount
    assert books.amount_due("invoices", externals[str(second.pk)]) == second.balance_due.amount
    assert second.balance_due.amount == 0
