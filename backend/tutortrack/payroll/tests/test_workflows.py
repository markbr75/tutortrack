"""E12-TW1: pay run and expense approval workflows."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.payroll import services
from tutortrack.payroll.models import ExpenseCategory, PayRun
from tutortrack.payroll.processes import (
    ExpenseApprovalWorkflow,
    PayRunWorkflow,
    expense_workflow_id,
    pay_run_workflow_id,
)
from tutortrack.people.tests.factories import TutorProfileFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def setup(org):
    with tenant_context(org):
        finance = MembershipFactory(organisation=org, role="finance").user
        tutor = TutorProfileFactory(organisation=org, status="active")
        with transaction.atomic():
            services.create_manual_item(tutor=tutor, kind="bonus", description="Bonus",
                                        amount=Money("40.00", "GBP"),
                                        day=services.org_today())  # fmt: skip
    return finance, tutor


def start_run(org) -> PayRun:
    with tenant_context(org), transaction.atomic():
        today = services.org_today()
        run, _ = services.create_pay_run(period_start=today - timedelta(days=30), period_end=today)
    return run


def wait_for_review(org, temporal_env, run) -> None:
    handle = temporal_env.handle(pay_run_workflow_id(org.pk, run.pk))
    for _ in range(100):
        state = temporal_env.run(handle.query(PayRunWorkflow.state))
        if state["step"] == "review":
            return
    raise AssertionError("never reached review")


def test_pay_run_is_approved_paid_and_finished(org, temporal_env):
    finance, _tutor = setup(org)
    run = start_run(org)
    wait_for_review(org, temporal_env, run)
    with tenant_context(org):
        services.approve(PayRun.objects.get(pk=run.pk), user=finance)  # signal "approved"
    handle = temporal_env.handle(pay_run_workflow_id(org.pk, run.pk))
    for _ in range(100):  # until payouts were sent (manual method: waiting)
        if temporal_env.run(handle.query(PayRunWorkflow.state))["step"] == "paying":
            break
    with tenant_context(org):
        services.mark_paid(PayRun.objects.get(pk=run.pk), reference="Paid")  # signal "settled"
    assert temporal_env.result(pay_run_workflow_id(org.pk, run.pk)) == "paid"
    with tenant_context(org):
        run.refresh_from_db()
        assert run.status == "paid"
        assert run.payouts.get().statement is not None


def test_cancelling_ends_the_pay_run_workflow(org, temporal_env):
    setup(org)
    run = start_run(org)
    wait_for_review(org, temporal_env, run)
    with tenant_context(org):
        services.cancel_pay_run(PayRun.objects.get(pk=run.pk))
    assert temporal_env.result(pay_run_workflow_id(org.pk, run.pk)) == "cancelled"


def test_expense_approval_reminds_until_decided(org, temporal_env):
    _finance, tutor = setup(org)
    with tenant_context(org):
        category = ExpenseCategory.objects.create(name="Books")
        with transaction.atomic():
            expense = services.submit_expense(
                tutor=tutor, category=category, day=services.org_today(), description="Book",
                amount=Money("9.00", "GBP"),
            )  # fmt: skip
    dispatch_batch()  # expense.submitted → ExpenseApprovalWorkflow
    wid = expense_workflow_id(org.pk, expense.pk)
    assert temporal_env.result(wid) == "reminded:2"


def test_deciding_ends_the_reminders(org, temporal_env):
    finance, tutor = setup(org)
    with tenant_context(org):
        category = ExpenseCategory.objects.create(name="Books")
        with transaction.atomic():
            expense = services.submit_expense(
                tutor=tutor, category=category, day=services.org_today(), description="Book",
                amount=Money("9.00", "GBP"),
            )  # fmt: skip
    dispatch_batch()
    with tenant_context(org), transaction.atomic():
        services.approve_expense(expense, user=finance)
    dispatch_batch()  # expense.approved → signal "decided"
    assert temporal_env.result(expense_workflow_id(org.pk, expense.pk)) == "reminded:0"


@pytest.mark.parametrize("prefix", ["PayRunWorkflow", "ExpenseApprovalWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[PayRunWorkflow, ExpenseApprovalWorkflow],
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
    finance, tutor = setup(org)
    run = start_run(org)
    wait_for_review(org, temporal_env, run)
    with tenant_context(org):
        services.approve(PayRun.objects.get(pk=run.pk), user=finance)
    handle = temporal_env.handle(pay_run_workflow_id(org.pk, run.pk))
    for _ in range(100):
        if temporal_env.run(handle.query(PayRunWorkflow.state))["step"] == "paying":
            break
    with tenant_context(org):
        services.mark_paid(PayRun.objects.get(pk=run.pk), reference="Paid")
    wid = pay_run_workflow_id(org.pk, run.pk)
    temporal_env.result(wid)
    (HISTORIES / "PayRunWorkflow-paid.json").write_text(temporal_env.history_json(wid))
    with tenant_context(org):
        category = ExpenseCategory.objects.create(name="Books")
        with transaction.atomic():
            expense = services.submit_expense(
                tutor=tutor, category=category, day=services.org_today(), description="Book",
                amount=Money("9.00", "GBP"),
            )  # fmt: skip
    dispatch_batch()
    eid = expense_workflow_id(org.pk, expense.pk)
    temporal_env.result(eid)
    (HISTORIES / "ExpenseApprovalWorkflow-reminded.json").write_text(temporal_env.history_json(eid))
