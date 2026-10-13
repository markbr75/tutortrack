"""E20-TW1: the enrolment payment and term rollover workflows."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.billing import services as billing
from tutortrack.billing.models import PaymentRequest
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.courses import services
from tutortrack.courses.models import Enrolment, RolloverOffer, TermRollover
from tutortrack.courses.processes import (
    EnrolmentPaymentWorkflow,
    TermRolloverWorkflow,
    payment_workflow_id,
    rollover_workflow_id,
)

from .test_courses import enrol, future_class, make_class, make_term, settings, world  # noqa: F401

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


def _held_place(org, world):  # noqa: F811
    settings(org, online_payment="full")
    group_class = future_class(org, world)
    with tenant_context(org), transaction.atomic():
        enrolment = services.enrol(group_class, world["student"], source="portal", payment="full")
    assert enrolment.status == "pending_payment"
    dispatch_batch()  # enrolment.created → EnrolmentPaymentWorkflow
    return enrolment


def _pay(org, enrolment):
    with tenant_context(org), transaction.atomic():
        request = PaymentRequest.objects.get(pk=enrolment.payment_request_id)
        billing.pay_payment_request(request, request.amount)
    dispatch_batch()  # payment_request.paid → signal "payment_received"


def test_a_paid_place_becomes_an_enrolment(org, world, temporal_env):  # noqa: F811
    enrolment = _held_place(org, world)
    _pay(org, enrolment)
    wid = payment_workflow_id(org.pk, enrolment.pk)
    assert temporal_env.result(wid) == "enrolled"
    with tenant_context(org):
        enrolment.refresh_from_db()
        assert enrolment.status == "enrolled"
        assert enrolment.billed_at is not None
    record(temporal_env, wid, "EnrolmentPaymentWorkflow-paid")


def test_an_unpaid_place_is_released_when_the_hold_runs_out(org, world, temporal_env):  # noqa: F811
    enrolment = _held_place(org, world)
    wid = payment_workflow_id(org.pk, enrolment.pk)
    assert temporal_env.result(wid) == "withdrawn"
    with tenant_context(org):
        enrolment.refresh_from_db()
        assert (enrolment.status, enrolment.withdrawal_reason) == ("withdrawn", "unpaid")
        request = PaymentRequest.objects.get(pk=enrolment.payment_request_id)
        assert request.status == "cancelled"
    record(temporal_env, wid, "EnrolmentPaymentWorkflow-released")


def test_cancelling_a_held_place_ends_the_workflow(org, world, temporal_env):  # noqa: F811
    enrolment = _held_place(org, world)
    wid = payment_workflow_id(org.pk, enrolment.pk)
    wait_for(org, lambda: bool(Enrolment.objects.get(pk=enrolment.pk).workflow_id))
    with tenant_context(org), transaction.atomic():
        services.cancel_pending(Enrolment.objects.get(pk=enrolment.pk))
    dispatch_batch()  # enrolment.released → signal "cancelled"
    assert temporal_env.result(wid) == "cancelled"


def test_confirming_is_retried_after_a_failure(org, world, temporal_env, monkeypatch):  # noqa: F811
    real = services.confirm_enrolment
    calls: list[str] = []

    def flaky(enrolment_id, **kwargs):
        calls.append(str(enrolment_id))
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return real(enrolment_id, **kwargs)

    monkeypatch.setattr(services, "confirm_enrolment", flaky)
    enrolment = _held_place(org, world)
    _pay(org, enrolment)
    wid = payment_workflow_id(org.pk, enrolment.pk)
    assert temporal_env.result(wid) == "enrolled"
    assert len(calls) == 2
    with tenant_context(org):
        assert Enrolment.objects.get(pk=enrolment.pk).status == "enrolled"
    record(temporal_env, wid, "EnrolmentPaymentWorkflow-retried")


def _rollover(org, world, temporal_env, days=4):  # noqa: F811
    current = future_class(org, world, weeks=4)
    start = current.term.end_date + timedelta(days=14)
    spring = make_term(org, world, start, 4, name="Spring")
    offset = (current.start_date.weekday() - start.weekday()) % 7
    nxt = make_class(org, world, spring, first=start + timedelta(days=offset))
    enrol(org, current, world["student"])
    enrol(org, current, world["sibling"])
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    with tenant_context(org), transaction.atomic():
        rollover = services.start_rollover(
            current.term, spring, deadline=server_now + timedelta(days=days)
        )
    return rollover, nxt


def test_rollover_reminds_and_finishes_at_the_deadline(org, world, temporal_env):  # noqa: F811
    rollover, nxt = _rollover(org, world, temporal_env)
    with tenant_context(org), transaction.atomic():
        services.respond_rollover(rollover.offers.get(student=world["student"]), confirm=True)
    dispatch_batch()  # term.rollover_started → TermRolloverWorkflow (the answer is checked)
    wid = rollover_workflow_id(org.pk, rollover.pk)
    assert temporal_env.result(wid) == "finalised:1"
    with tenant_context(org):
        pending = rollover.offers.get(student=world["sibling"])
        assert pending.status == "released"
        assert pending.reminded_at is not None  # reminded half way to the deadline
        assert list(
            Enrolment.objects.filter(group_class=nxt).values_list("student_id", flat=True)
        ) == [world["student"].pk]
        assert TermRollover.objects.get(pk=rollover.pk).status == "finalised"
        from tutortrack.comms.models import Message

        assert Message.objects.filter(type_key="term_rollover_invite").exists()
    record(temporal_env, wid, "TermRolloverWorkflow-deadline")


def test_rollover_finishes_once_every_family_has_answered(org, world, temporal_env):  # noqa: F811
    rollover, nxt = _rollover(org, world, temporal_env, days=10)
    dispatch_batch()
    wid = rollover_workflow_id(org.pk, rollover.pk)
    wait_for(org, lambda: rollover.offers.filter(status="pending").count() == 2)
    with tenant_context(org), transaction.atomic():
        services.respond_rollover(rollover.offers.get(student=world["student"]), confirm=True)
        services.respond_rollover(rollover.offers.get(student=world["sibling"]), confirm=False)
    dispatch_batch()  # term.rollover_responded → signal "responded"
    assert temporal_env.result(wid) == "finalised:1"
    with tenant_context(org):
        assert not RolloverOffer.objects.filter(reminded_at__isnull=False).exists()
        assert Enrolment.objects.filter(group_class=nxt).count() == 1
    record(temporal_env, wid, "TermRolloverWorkflow-answered")


def test_staff_can_finish_a_rollover_early(org, world, temporal_env):  # noqa: F811
    rollover, _nxt = _rollover(org, world, temporal_env, days=10)
    dispatch_batch()
    wid = rollover_workflow_id(org.pk, rollover.pk)
    wait_for(org, lambda: bool(TermRollover.objects.get(pk=rollover.pk).workflow_id))
    with tenant_context(org), transaction.atomic():
        services.finish_rollover_now(TermRollover.objects.get(pk=rollover.pk))
    assert temporal_env.result(wid) == "finalised:0"  # nobody confirmed
    with tenant_context(org):
        assert set(rollover.offers.values_list("status", flat=True)) == {"released"}


@pytest.mark.parametrize("prefix", ["EnrolmentPaymentWorkflow", "TermRolloverWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[EnrolmentPaymentWorkflow, TermRolloverWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
