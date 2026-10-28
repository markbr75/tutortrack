"""E25-TW1: the referral reward and affiliate statement workflows."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.billing import ledger
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.core.workflows import start_now
from tutortrack.growth import services
from tutortrack.growth.models import CommissionItem, Referral
from tutortrack.growth.processes import (
    AffiliateStatementRunWorkflow,
    ReferralRewardWorkflow,
    StatementRunInput,
    referral_workflow_id,
)
from tutortrack.payments import services as payments
from tutortrack.people.tests.factories import ClientFactory, ContactFactory

from .factories import AffiliateFactory, ReferralProgramFactory

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def running(org, workflow_id: str) -> Callable[[], bool]:
    from tutortrack.core.models import WorkflowLink

    return lambda: WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


def gbp(value: str) -> Money:
    return Money(Decimal(value), "GBP")


def family(org, name: str, email: str):
    client = ClientFactory(organisation=org, display_name=name)
    ContactFactory(organisation=org, client=client, email=email, first_name="Pat", mobile="")
    return client


# --- ReferralRewardWorkflow ---------------------------------------------------------------------


def _referral(org, *, referee_email="smith@example.com", deadline_days=30):
    ReferralProgramFactory(organisation=org, deadline_days=deadline_days)
    referrer = family(org, "The Patels", "priya@example.com")
    referee = family(org, "The Smiths", referee_email)
    with tenant_context(org), transaction.atomic():
        referral = services.create_referral(referrer=referrer, referee=referee)
    dispatch_batch()  # referral.created → ReferralRewardWorkflow
    return referral, referrer, referee


def _pay(org, client):
    with tenant_context(org), transaction.atomic():
        payments.record_manual_payment(client=client, amount=gbp("40"), method="bank_transfer")
    dispatch_batch()  # payment.succeeded → signal "milestone"


def test_the_referees_first_payment_rewards_the_referrer(org, temporal_env):
    referral, referrer, referee = _referral(org)
    wid = referral_workflow_id(org.pk, referral.pk)
    wait_for(org, running(org, wid))
    _pay(org, referee)
    assert temporal_env.result(wid) == "rewarded"
    with tenant_context(org):
        assert Referral.objects.get(pk=referral.pk).status == "rewarded"
        assert ledger.ledger_balance(referrer, "GBP") == gbp("-20.00")
    record(temporal_env, wid, "ReferralRewardWorkflow-rewarded")


def test_a_referral_expires_at_the_programme_deadline(org, temporal_env):
    referral, _referrer, _referee = _referral(org, deadline_days=3)
    wid = referral_workflow_id(org.pk, referral.pk)
    assert temporal_env.result(wid) == "expired"
    with tenant_context(org):
        assert Referral.objects.get(pk=referral.pk).status == "expired"
    record(temporal_env, wid, "ReferralRewardWorkflow-expired")


def test_fraud_checks_hold_the_reward(org, temporal_env):
    referral, _referrer, referee = _referral(org, referee_email="priya@example.com")
    wid = referral_workflow_id(org.pk, referral.pk)
    wait_for(org, running(org, wid))
    _pay(org, referee)
    assert temporal_env.result(wid) == "blocked"
    with tenant_context(org):
        assert Referral.objects.get(pk=referral.pk).fraud_flags == ["same_email"]
    record(temporal_env, wid, "ReferralRewardWorkflow-blocked")


def test_cancelling_a_referral_ends_the_workflow(org, temporal_env):
    referral, _referrer, _referee = _referral(org)
    wid = referral_workflow_id(org.pk, referral.pk)
    wait_for(org, running(org, wid))
    with tenant_context(org), transaction.atomic():
        services.cancel_referral(Referral.objects.get(pk=referral.pk), reason="duplicate")
    assert temporal_env.result(wid) == "cancelled"


def test_rewarding_is_retried_after_a_failure(org, temporal_env, monkeypatch):
    real = services.reward_referral
    calls: list[str] = []

    def flaky(referral_id, **kwargs):
        calls.append(str(referral_id))
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return real(referral_id, **kwargs)

    monkeypatch.setattr(services, "reward_referral", flaky)
    referral, _referrer, referee = _referral(org)
    wid = referral_workflow_id(org.pk, referral.pk)
    wait_for(org, running(org, wid))
    _pay(org, referee)
    assert temporal_env.result(wid) == "rewarded"
    assert len(calls) == 2
    record(temporal_env, wid, "ReferralRewardWorkflow-retried")


# --- AffiliateStatementRunWorkflow --------------------------------------------------------------


def test_the_monthly_run_issues_last_months_statements(org, temporal_env):
    affiliate = AffiliateFactory(organisation=org)
    with tenant_context(org), transaction.atomic():
        item = services.adjust_commission(affiliate, amount=gbp("12.50"), description="Bonus")
        last_month = services.org_today().replace(day=1) - timedelta(days=3)
        CommissionItem.objects.filter(pk=item.pk).update(
            earned_at=item.earned_at.replace(year=last_month.year, month=last_month.month, day=1)
        )
    wid = f"schedule-test:{org.pk}:affiliate-statements"
    start_now(AffiliateStatementRunWorkflow, StatementRunInput(organisation_id=str(org.pk)), id=wid)
    assert temporal_env.result(wid) == "issued:1"
    with tenant_context(org):
        assert CommissionItem.objects.get(pk=item.pk).statement is not None
    record(temporal_env, wid, "AffiliateStatementRunWorkflow-issued")


@pytest.mark.parametrize("prefix", ["ReferralRewardWorkflow", "AffiliateStatementRunWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ReferralRewardWorkflow, AffiliateStatementRunWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
