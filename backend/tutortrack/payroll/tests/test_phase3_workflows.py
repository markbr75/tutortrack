"""E12-T12: a Wise payout settles through ``PayRunWorkflow``'s daily check (the polling
fallback when no webhook arrives). The recorded history is replayed by
``test_workflows.test_histories_replay`` (``PayRunWorkflow-*.json``)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.payroll import services
from tutortrack.payroll.models import Payout, PayRun
from tutortrack.payroll.payouts.wise_fake import FakeWise
from tutortrack.payroll.processes import PayRunWorkflow, pay_run_workflow_id
from tutortrack.people.tests.factories import TutorProfileFactory

from .test_workflows import start_run, wait_for_review

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
UK_BANK = {
    "country": "GB",
    "account_name": "Nia Jones",
    "sort_code": "200000",
    "account_number": "55779911",
}


def test_wise_payout_settles_on_the_daily_check(org, temporal_env):
    FakeWise.reset()
    with tenant_context(org):
        finance = MembershipFactory(organisation=org, role="finance").user
        tutor = TutorProfileFactory(organisation=org, status="active")
        IntegrationConnection.objects.create(
            provider="wise",
            level="organisation",
            status="active",
            secret="token",
            external_account_id="fake-profile",
        )
        with transaction.atomic():
            services.update_profile(tutor, method="wise", bank=UK_BANK)
            services.create_manual_item(
                tutor=tutor,
                kind="bonus",
                description="Bonus",
                amount=Money("40.00", "GBP"),
                day=services.org_today(),
            )
    run = start_run(org)
    wait_for_review(org, temporal_env, run)
    with tenant_context(org):
        services.approve(PayRun.objects.get(pk=run.pk), user=finance)
    wid = pay_run_workflow_id(org.pk, run.pk)
    handle = temporal_env.handle(wid)
    for _ in range(200):
        if temporal_env.run(handle.query(PayRunWorkflow.state))["step"] == "paying":
            break
    with tenant_context(org):
        for _ in range(200):
            payout = Payout.objects.filter(pay_run_id=run.pk).first()
            if payout is not None and payout.provider_ref:
                break
    assert payout is not None
    assert payout.status == "processing"
    FakeWise.settle(payout.provider_ref)  # no webhook: the daily check finds it
    assert temporal_env.result(wid) == "paid"
    with tenant_context(org):
        payout.refresh_from_db()
    assert payout.status == "paid"
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / "PayRunWorkflow-wise.json").write_text(temporal_env.history_json(wid))
    FakeWise.reset()
