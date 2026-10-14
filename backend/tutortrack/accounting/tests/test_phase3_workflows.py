"""E23-T10: ``XeroPayrollSyncWorkflow`` starts on ``pay_run.approved`` when Xero Payroll is
connected, retries through outages, and replays."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.accounting.models import PayrollTimesheetSync
from tutortrack.accounting.payroll_processes import (
    XeroPayrollSyncWorkflow,
    payroll_sync_workflow_id,
)
from tutortrack.accounting.providers.xero_payroll import Employee, FakeXeroPayroll
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.payroll import services as payroll
from tutortrack.payroll.models import PayItem
from tutortrack.people.tests.factories import TutorProfileFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def test_approving_a_pay_run_sends_the_timesheets(org, temporal_env):
    FakeXeroPayroll.reset([Employee("emp-1", "sam@example.com", "Sam", "Lee", "cal-1")])
    with tenant_context(org):
        finance = MembershipFactory(organisation=org, role="finance").user
        IntegrationConnection.objects.create(
            provider="xero_payroll",
            level="organisation",
            status="active",
            access_token="t",
            external_account_id="tenant-1",
        )
        tutor = TutorProfileFactory(
            organisation=org, status="active", employment_type="employee", email="sam@example.com"
        )
        with transaction.atomic():
            payroll.update_profile(tutor, method="external_payroll")
            item = payroll.create_manual_item(
                tutor=tutor,
                kind="salary",
                description="Lessons",
                amount=Money("60.00", "GBP"),
                day=now().date() - timedelta(days=1),
            )
            PayItem.objects.filter(pk=item.pk).update(unit="hour", quantity=Decimal("3"))
            run, _ = payroll.create_pay_run(
                period_start=now().date() - timedelta(days=30),
                period_end=now().date(),
                start_workflow=False,
            )
            payroll.assemble(run.pk)
        with transaction.atomic():
            payroll.approve(run, user=finance)
    dispatch_batch()  # pay_run.approved → XeroPayrollSyncWorkflow
    wid = payroll_sync_workflow_id(org.pk, run.pk)
    assert temporal_env.result(wid) == "synced"
    with tenant_context(org):
        sync = PayrollTimesheetSync.objects.get()
    assert sync.results[0]["timesheet"] == "ts-1"
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "XeroPayrollSyncWorkflow-synced.json").write_text(
            temporal_env.history_json(wid)
        )


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("XeroPayrollSyncWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[XeroPayrollSyncWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
