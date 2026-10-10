"""E27-TW1: WebhookDeliveryWorkflow (retries with backoff, retry-now signal, give up,
endpoint disabled) and replay of recorded histories."""

from __future__ import annotations

import itertools
import json
import os
import time as clock
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from django.core import mail
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events import EventEnvelope
from tutortrack.core.time import now
from tutortrack.developer import services, signing
from tutortrack.developer.models import WebhookAttempt, WebhookDelivery, WebhookEndpoint
from tutortrack.developer.processes import (
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    WebhookDeliveryWorkflow,
    delivery_workflow_id,
)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    deadline = clock.monotonic() + seconds
    while clock.monotonic() < deadline:
        with tenant_context(org):
            if check():
                return
        clock.sleep(0.1)
    raise AssertionError("timed out waiting for the workflow")


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def lesson_completed(org) -> EventEnvelope:
    return EventEnvelope(
        id=uuid.uuid4(),
        type="lesson.completed",
        version=1,
        occurred_at=now(),
        organisation_id=org.pk,
        branch_id=None,
        actor={"type": "user", "id": None},
        subject={"type": "lesson", "id": str(uuid.uuid4())},
        data={"outcome": "attended"},
        changes={},
    )


def deliver(org) -> tuple[WebhookDelivery, str]:
    """An endpoint for lesson.completed and one delivery (its workflow starts on commit)."""
    with tenant_context(org):
        with transaction.atomic():
            _endpoint, secret = services.create_endpoint(
                url="https://hooks.example.com/tt", events_=["lesson.completed"]
            )
        with transaction.atomic():
            delivery = services.enqueue_event(lesson_completed(org))[0]
    return delivery, secret


def attempts(org, delivery) -> list[WebhookAttempt]:
    with tenant_context(org):
        return list(WebhookAttempt.objects.filter(delivery=delivery).order_by("number"))


def test_delivery_succeeds_first_time(org, public_dns, receiver, temporal_env):
    fake = receiver()
    delivery, secret = deliver(org)
    wid = delivery_workflow_id(org.pk, delivery.pk)
    assert temporal_env.result(wid) == "succeeded"
    sent = fake.requests[0]
    assert signing.verify(secret, sent["headers"]["Webhook-Signature"], sent["body"])
    with tenant_context(org):
        assert WebhookDelivery.objects.get(pk=delivery.pk).status == "succeeded"
    record(temporal_env, wid, "WebhookDeliveryWorkflow-succeeded")


def test_a_500_is_retried_at_increasing_intervals(org, public_dns, receiver, temporal_env):
    """AC: a 500 is retried at increasing intervals and every attempt is in the log."""
    receiver([500, 500, 500])
    delivery, _secret = deliver(org)
    wid = delivery_workflow_id(org.pk, delivery.pk)
    assert temporal_env.result(wid) == "succeeded"
    log = attempts(org, delivery)
    assert [a.status_code for a in log] == [500, 500, 500, 200]
    gaps = [(b.attempted_at - a.attempted_at) for a, b in itertools.pairwise(log)]
    assert gaps == sorted(gaps)
    assert gaps[0] < gaps[-1]
    for gap, expected in zip(gaps, RETRY_DELAYS, strict=False):
        assert gap >= expected
    record(temporal_env, wid, "WebhookDeliveryWorkflow-retried")


def test_retry_now_signal_cuts_the_wait_short(org, public_dns, receiver, temporal_env):
    receiver([500])
    delivery, _secret = deliver(org)
    wait_for(org, lambda: WebhookAttempt.objects.filter(delivery=delivery).exists())
    with tenant_context(org):
        services.retry_now(WebhookDelivery.objects.get(pk=delivery.pk))
    # The 30-second backoff isn't skipped while we poll; only the signal can wake it.
    wait_for(org, lambda: WebhookDelivery.objects.get(pk=delivery.pk).status == "succeeded", 15)
    wid = delivery_workflow_id(org.pk, delivery.pk)
    assert temporal_env.result(wid) == "succeeded"
    record(temporal_env, wid, "WebhookDeliveryWorkflow-retry-now")


def test_always_failing_gives_up_after_72_hours_and_disables(
    org, user, member, public_dns, receiver, temporal_env
):
    receiver(default=500)
    delivery, _secret = deliver(org)
    wid = delivery_workflow_id(org.pk, delivery.pk)
    assert temporal_env.result(wid) == "failed"
    log = attempts(org, delivery)
    assert len(log) == MAX_ATTEMPTS == 15
    assert (log[-1].attempted_at - log[0].attempted_at).total_seconds() >= 72 * 3600
    with tenant_context(org):
        assert WebhookDelivery.objects.get(pk=delivery.pk).status == "failed"
        endpoint = WebhookEndpoint.objects.get(pk=delivery.endpoint_id)
        assert endpoint.status == "disabled"
    assert any("Webhook endpoint disabled" in m.subject for m in mail.outbox)
    record(temporal_env, wid, "WebhookDeliveryWorkflow-failed")


def test_paused_endpoint_cancels_the_delivery(org, public_dns, receiver, temporal_env):
    receiver(default=500)
    delivery, _secret = deliver(org)
    wait_for(org, lambda: WebhookAttempt.objects.filter(delivery=delivery).exists())
    with tenant_context(org), transaction.atomic():
        services.update_endpoint(
            WebhookEndpoint.objects.get(pk=delivery.endpoint_id), status="paused"
        )
    wid = delivery_workflow_id(org.pk, delivery.pk)
    assert temporal_env.result(wid) == "cancelled"
    record(temporal_env, wid, "WebhookDeliveryWorkflow-cancelled")


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("WebhookDeliveryWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[WebhookDeliveryWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
