"""E04-TW1: the trial lifecycle and subscription dunning on Temporal."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.subscriptions import services
from tutortrack.subscriptions.gateway import Item
from tutortrack.subscriptions.gateway.fake import FakeGateway
from tutortrack.subscriptions.models import Subscription
from tutortrack.subscriptions.processes import (
    SubscriptionDunningWorkflow,
    TrialLifecycleWorkflow,
    dunning_workflow_id,
    trial_workflow_id,
)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def server_now(temporal_env: Any) -> Any:
    return temporal_env.run(temporal_env.env.get_current_time())


def start_trial(org: Any, temporal_env: Any, monkeypatch: pytest.MonkeyPatch) -> Subscription:
    """A trial whose dates follow the shared test server's clock."""
    MembershipFactory(organisation=org, role="owner")
    moment = server_now(temporal_env)
    monkeypatch.setattr("tutortrack.subscriptions.services.now", lambda: moment)
    subscription = services.start_trial(org)
    dispatch_batch()  # subscription.started → TrialLifecycleWorkflow
    return subscription


def notices(org: Any) -> list[str]:
    from tutortrack.comms.models import Message

    with tenant_context(org):
        return list(
            Message.objects.filter(type_key="subscription_notice", channel="in_app")
            .order_by("created_at")
            .values_list("subject", flat=True)
        )


def test_trial_sends_its_emails_then_locks_without_a_card(org, temporal_env, monkeypatch):
    start_trial(org, temporal_env, monkeypatch)
    wid = trial_workflow_id(org.pk)
    assert temporal_env.result(wid) == "locked"
    state = temporal_env.run(temporal_env.handle(wid).query(TrialLifecycleWorkflow.state))
    assert state["sent"] == ["welcome", "checklist", "reminder", "last_chance"]
    assert notices(org) == [
        "Welcome to TutorTrack",
        "Getting the most from your trial",
        "Your trial ends in 7 days",
        "Your trial ends in 2 days",
        "Your trial has ended",
    ]
    org.refresh_from_db()
    assert org.status == "suspended"


def test_adding_a_card_stops_the_reminders_and_carries_on(org, temporal_env, monkeypatch):
    start_trial(org, temporal_env, monkeypatch)
    with tenant_context(org):
        url = services.checkout("team", "month")
        services.complete_checkout(parse_qs(urlparse(url).query)["checkout"][0])
    wid = trial_workflow_id(org.pk)
    assert temporal_env.result(wid) == "active"
    state = temporal_env.run(temporal_env.handle(wid).query(TrialLifecycleWorkflow.state))
    assert state["converted"]
    assert "reminder" not in state["sent"]
    org.refresh_from_db()
    assert org.status == "active"


def test_platform_admin_extends_the_trial(org, temporal_env, monkeypatch):
    subscription = start_trial(org, temporal_env, monkeypatch)
    with tenant_context(org):
        services.extend_trial(5, reason="Asked for more time")
        subscription.refresh_from_db()
    wid = trial_workflow_id(org.pk)
    assert temporal_env.result(wid) == "locked"
    state = temporal_env.run(temporal_env.handle(wid).query(TrialLifecycleWorkflow.state))
    assert state["extra_days"] == 5
    assert (subscription.trial_ends_at - subscription.trial_started_at).days == 35


def paying(org: Any) -> Subscription:
    """A paying subscriber, created directly (no trial workflow to tidy up)."""
    MembershipFactory(organisation=org, role="owner")
    remote = FakeGateway().create_subscription("cus_fake_x", [Item("tt:solo:GBP:month:base_fee")])
    with tenant_context(org):
        return Subscription.objects.create(
            organisation=org, plan=services.get_plan("solo"), currency="GBP", status="active",
            stripe_customer_id=remote.customer, stripe_subscription_id=remote.id,
        )  # fmt: skip


def test_dunning_reminds_then_suspends(org, temporal_env):
    paying(org)
    with transaction.atomic(), tenant_context(org):
        services.mark_past_due("in_1")
    dispatch_batch()  # subscription.past_due → SubscriptionDunningWorkflow
    wid = dunning_workflow_id(org.pk, "in_1")
    assert temporal_env.result(wid) == "suspended"
    state = temporal_env.run(temporal_env.handle(wid).query(SubscriptionDunningWorkflow.state))
    assert state["sent"] == [0, 3, 7, 14]
    org.refresh_from_db()
    assert org.status == "suspended"
    assert notices(org)[-1] == "Your account is read-only"


def test_paying_ends_dunning(org, temporal_env):
    paying(org)
    with transaction.atomic(), tenant_context(org):
        services.mark_past_due("in_2")
    dispatch_batch()
    with transaction.atomic(), tenant_context(org):
        services.payment_recovered("in_2")
    dispatch_batch()  # subscription.changed (payment_recovered) → signal "paid"
    assert temporal_env.result(dunning_workflow_id(org.pk, "in_2")) in {"paid", "recovered"}
    org.refresh_from_db()
    assert org.status == "active"


@pytest.mark.parametrize("prefix", ["TrialLifecycleWorkflow", "SubscriptionDunningWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[TrialLifecycleWorkflow, SubscriptionDunningWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_record_histories_if_requested(org, temporal_env, monkeypatch):
    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    start_trial(org, temporal_env, monkeypatch)
    wid = trial_workflow_id(org.pk)
    temporal_env.result(wid)
    (HISTORIES / "TrialLifecycleWorkflow-locked.json").write_text(temporal_env.history_json(wid))
    with tenant_context(org):
        Subscription.objects.update(
            status="active", stripe_subscription_id="sub_fake_hist", stripe_customer_id="cus_x"
        )
    with transaction.atomic(), tenant_context(org):
        services.mark_past_due("in_hist")
    dispatch_batch()
    did = dunning_workflow_id(org.pk, "in_hist")
    temporal_env.result(did)
    (HISTORIES / "SubscriptionDunningWorkflow-suspended.json").write_text(
        temporal_env.history_json(did)
    )
