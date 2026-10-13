"""E08-TW1: booking hold, reschedule request and time-off approval workflows."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.billing import services as billing
from tutortrack.billing.models import PaymentRequest
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.money import Money
from tutortrack.scheduling import services
from tutortrack.scheduling.models import AvailabilityException, BookingHold, RescheduleRequest
from tutortrack.scheduling.processes import (
    BookingHoldWorkflow,
    RescheduleRequestWorkflow,
    TimeOffApprovalWorkflow,
    hold_workflow_id,
    reschedule_workflow_id,
    time_off_workflow_id,
)

from .test_phase2 import enable_booking, first_slot, local, make_lesson, world  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def record(temporal_env, workflow_id: str, name: str) -> None:
    if os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        (HISTORIES / f"{name}.json").write_text(temporal_env.history_json(workflow_id))


def _hold(org, world, **settings):  # noqa: F811
    enable_booking(org, **settings)
    slot = first_slot(org, world, days=3)
    with tenant_context(org), transaction.atomic():
        hold, _token = services.hold_slot(
            service=world["service"], start=slot.start, student=world["student"]
        )
    dispatch_batch()  # booking.held → BookingHoldWorkflow
    return hold


def test_an_unfinished_booking_releases_its_slot(org, world, temporal_env):  # noqa: F811
    hold = _hold(org, world)
    wid = hold_workflow_id(org.pk, hold.pk)
    assert temporal_env.result(wid) == "expired"
    with tenant_context(org):
        assert BookingHold.objects.get(pk=hold.pk).status == "expired"
    record(temporal_env, wid, "BookingHoldWorkflow-expired")


def test_a_paid_booking_is_confirmed(org, world, temporal_env):  # noqa: F811
    hold = _hold(org, world, payment="at_booking")
    with tenant_context(org), transaction.atomic():
        hold, _url = services.submit_hold(BookingHold.objects.get(pk=hold.pk))
    dispatch_batch()  # booking.submitted → signal "submitted"
    with tenant_context(org), transaction.atomic():
        request = PaymentRequest.objects.get(pk=hold.payment_request_id)
        billing.pay_payment_request(request, Money("40.00", "GBP"))
    dispatch_batch()  # payment_request.paid → signal "paid"
    wid = hold_workflow_id(org.pk, hold.pk)
    assert temporal_env.result(wid) == "confirmed"
    with tenant_context(org):
        hold = BookingHold.objects.get(pk=hold.pk)
        assert hold.status == "confirmed"
        assert hold.lesson is not None
    record(temporal_env, wid, "BookingHoldWorkflow-paid")


def test_an_unanswered_reschedule_request_is_declined(org, world, temporal_env):  # noqa: F811
    lesson = make_lesson(org, world, local(6))
    with tenant_context(org), transaction.atomic():
        item = services.request_reschedule(
            lesson, options=[(local(7), local(7, "17:00"))], requester="client"
        )
    dispatch_batch()  # reschedule.requested → RescheduleRequestWorkflow
    wid = reschedule_workflow_id(org.pk, item.pk)
    assert temporal_env.result(wid) == "expired"
    with tenant_context(org):
        assert RescheduleRequest.objects.get(pk=item.pk).status == "expired"
    record(temporal_env, wid, "RescheduleRequestWorkflow-expired")


def test_an_answered_reschedule_request_ends_the_workflow(org, world, temporal_env):  # noqa: F811
    lesson = make_lesson(org, world, local(6))
    with tenant_context(org), transaction.atomic():
        item = services.request_reschedule(
            lesson, options=[(local(7), local(7, "17:00"))], requester="client"
        )
    dispatch_batch()
    with tenant_context(org), transaction.atomic():
        services.decide_reschedule(RescheduleRequest.objects.get(pk=item.pk), approve=True)
    dispatch_batch()  # reschedule.approved → signal "answered"
    wid = reschedule_workflow_id(org.pk, item.pk)
    assert temporal_env.result(wid) == "approved"
    with tenant_context(org):
        lesson.refresh_from_db()
        assert lesson.start == local(7)
    record(temporal_env, wid, "RescheduleRequestWorkflow-approved")


def test_approved_time_off_flags_cover(org, world, temporal_env):  # noqa: F811
    clash = make_lesson(org, world, local(9))
    with tenant_context(org), transaction.atomic():
        exception, _ = services.add_exception(
            world["tutor"], type="off", start=local(9, "00:00"), end=local(10, "00:00"),
            needs_approval=True,
        )  # fmt: skip
    dispatch_batch()  # time_off.requested → TimeOffApprovalWorkflow
    with tenant_context(org), transaction.atomic():
        services.decide_time_off(AvailabilityException.objects.get(pk=exception.pk), approve=True)
    dispatch_batch()  # time_off.approved → signal "decided"
    wid = time_off_workflow_id(org.pk, exception.pk)
    assert temporal_env.result(wid) == "approved_cover"
    with tenant_context(org):
        clash.refresh_from_db()
        assert clash.cover_flagged_at is not None
        assert AvailabilityException.objects.get(pk=exception.pk).cover_request_id
    record(temporal_env, wid, "TimeOffApprovalWorkflow-approved")


def test_undecided_time_off_is_declined_when_it_starts(org, world, temporal_env):  # noqa: F811
    with tenant_context(org), transaction.atomic():
        exception, _ = services.add_exception(
            world["tutor"], type="off", start=local(2, "00:00"), end=local(3, "00:00"),
            needs_approval=True,
        )  # fmt: skip
    dispatch_batch()
    wid = time_off_workflow_id(org.pk, exception.pk)
    temporal_env.skip(timedelta(days=3))
    assert temporal_env.result(wid) == "declined"
    with tenant_context(org):
        assert AvailabilityException.objects.get(pk=exception.pk).status == "declined"
    record(temporal_env, wid, "TimeOffApprovalWorkflow-declined")


@pytest.mark.parametrize(
    "prefix", ["BookingHoldWorkflow", "RescheduleRequestWorkflow", "TimeOffApprovalWorkflow"]
)
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[BookingHoldWorkflow, RescheduleRequestWorkflow, TimeOffApprovalWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
