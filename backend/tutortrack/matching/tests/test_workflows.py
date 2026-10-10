"""E19-TW1: the job offer cascade and cover request workflows."""

from __future__ import annotations

import json
import os
import time as clock
from collections.abc import Callable
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.jobs import services as jobs
from tutortrack.jobs.models import JobTutor
from tutortrack.matching import services
from tutortrack.matching.models import CoverRequest, JobOffer, OfferBatch
from tutortrack.matching.processes import (
    CoverRequestWorkflow,
    JobOfferCascadeWorkflow,
    cover_workflow_id,
    offer_workflow_id,
)

from .test_matching import _lesson_for, available, make_job, make_tutor, maths  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def wait_for(org, check: Callable[[], bool], seconds: float = 20) -> None:
    """Poll the database while the worker runs activities (time doesn't skip meanwhile)."""
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


def offer_status(offer: JobOffer) -> str:
    return JobOffer.objects.get(pk=offer.pk).status


def test_sequential_cascade_moves_on_after_a_decline_and_fills(org, maths, temporal_env):  # noqa: F811
    subject, level, _service = maths
    first = make_tutor(org, subject, level=level)
    second = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    with tenant_context(org), transaction.atomic():
        batch = services.start_offers(job, [first, second], mode="sequential")
        offers = list(batch.offers.order_by("cascade_order"))
    dispatch_batch()  # job_offer.batch_started → JobOfferCascadeWorkflow
    wait_for(org, lambda: offer_status(offers[0]) == "sent")
    with tenant_context(org):
        assert offer_status(offers[1]) == "queued"  # one at a time
        with transaction.atomic():
            services.respond(offers[0], accept=False, reason="Busy")
    dispatch_batch()  # job_offer.declined → signal "responded"
    wait_for(org, lambda: offer_status(offers[1]) == "sent")
    with tenant_context(org), transaction.atomic():
        services.respond(offers[1], accept=True)
    dispatch_batch()
    wid = offer_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "filled"
    with tenant_context(org):
        assert JobTutor.objects.get(job=job, status="active").tutor == second
        assert OfferBatch.objects.get(pk=batch.pk).status == "filled"
    record(temporal_env, wid, "JobOfferCascadeWorkflow-filled")


def test_unanswered_offers_expire_and_the_batch_is_exhausted(org, maths, temporal_env):  # noqa: F811
    subject, level, _service = maths
    tutors = [make_tutor(org, subject, level=level) for _ in range(2)]
    job = make_job(org, maths)
    with tenant_context(org), transaction.atomic():
        batch = services.start_offers(job, tutors, mode="simultaneous", expiry_hours=12)
    dispatch_batch()
    wid = offer_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "exhausted"
    with tenant_context(org):
        assert set(batch.offers.values_list("status", flat=True)) == {"expired"}
        assert OfferBatch.objects.get(pk=batch.pk).status == "exhausted"
    record(temporal_env, wid, "JobOfferCascadeWorkflow-exhausted")


def test_an_accepted_offer_waits_for_the_coordinator(org, maths, temporal_env):  # noqa: F811
    subject, level, _service = maths
    tutor = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    with tenant_context(org), transaction.atomic():
        batch = services.start_offers(job, [tutor], admin_confirms=True)
        offer = batch.offers.get()
    dispatch_batch()
    wait_for(org, lambda: offer_status(offer) == "sent")
    with tenant_context(org), transaction.atomic():
        services.respond(offer, accept=True)
    dispatch_batch()
    wait_for(org, lambda: OfferBatch.objects.get(pk=batch.pk).status == "awaiting_confirmation")
    with tenant_context(org):
        assert not JobTutor.objects.filter(job=job, status="active").exists()
        with transaction.atomic():
            services.decide(OfferBatch.objects.get(pk=batch.pk), approve=True)
    dispatch_batch()  # job_offer.decided → signal "decided"
    wid = offer_workflow_id(org.pk, batch.pk)
    assert temporal_env.result(wid) == "filled"
    with tenant_context(org):
        assert JobTutor.objects.get(job=job, status="active").tutor == tutor
    record(temporal_env, wid, "JobOfferCascadeWorkflow-confirmed")


def _cover_setup(org, maths, temporal_env, *, free: bool):  # noqa: F811
    """The lesson is a few days after the later of real and Temporal test-server time
    (the server's clock can run ahead under load)."""
    from tutortrack.core.time import now

    server_now = temporal_env.run(temporal_env.env.get_current_time())
    days = 5 + max((server_now - now()).days, 0)
    subject, level, _service = maths
    away = make_tutor(org, subject, level=level)
    helper = make_tutor(org, subject, level=level)
    job = make_job(org, maths)
    with tenant_context(org):
        jobs.add_tutor(job, tutor=away)
    lesson = _lesson_for(org, job, away, days=days)
    if free:
        with tenant_context(org):
            weekday = lesson.start.astimezone(ZoneInfo(org.timezone)).weekday()
        available(org, helper, weekday=weekday, start=time(0), end=time(23, 59))
    with tenant_context(org), transaction.atomic():
        request = services.create_cover([lesson], reason="Ill")
    return request, helper, lesson


def test_cover_nobody_takes_is_escalated_at_the_deadline(org, maths, temporal_env):  # noqa: F811
    request, _helper, _lesson = _cover_setup(org, maths, temporal_env, free=True)
    dispatch_batch()  # cover_request.created → CoverRequestWorkflow
    wid = cover_workflow_id(org.pk, request.pk)
    assert temporal_env.result(wid) == "unfilled"
    with tenant_context(org):
        request.refresh_from_db()
        assert request.status == "unfilled"
        assert len(request.notified) == 1
    record(temporal_env, wid, "CoverRequestWorkflow-unfilled")


def test_accepted_cover_ends_the_workflow(org, maths, temporal_env):  # noqa: F811
    request, helper, lesson = _cover_setup(org, maths, temporal_env, free=True)
    dispatch_batch()
    wait_for(org, lambda: bool(CoverRequest.objects.get(pk=request.pk).notified))
    with tenant_context(org), transaction.atomic():
        services.accept_cover(CoverRequest.objects.get(pk=request.pk), helper)
    dispatch_batch()  # cover_request.accepted → signal "accepted"
    wid = cover_workflow_id(org.pk, request.pk)
    assert temporal_env.result(wid) == "closed"
    with tenant_context(org):
        assert [t.tutor_id for t in lesson.tutors.all()] == [helper.pk]
    record(temporal_env, wid, "CoverRequestWorkflow-closed")


@pytest.mark.parametrize("prefix", ["JobOfferCascadeWorkflow", "CoverRequestWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[JobOfferCascadeWorkflow, CoverRequestWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )
