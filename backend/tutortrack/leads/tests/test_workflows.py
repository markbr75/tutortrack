"""E17-TW1: enquiry follow-up (acknowledgement, SLA) and waitlist offers on Temporal."""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.leads import services
from tutortrack.leads.models import Enquiry, WaitlistEntry
from tutortrack.leads.processes import (
    EnquiryFollowUpWorkflow,
    WaitlistOfferWorkflow,
    enquiry_workflow_id,
    offer_workflow_id,
)
from tutortrack.people.tests.factories import ClientFactory, StudentFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def new_enquiry(org, temporal_env) -> Enquiry:
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    with tenant_context(org), transaction.atomic():
        enquiry = services.create_enquiry(
            contact={"first_name": "Priya", "email": "priya@example.com"},
            students=[{"first_name": "Arjun"}],
        )
        # The "New" stage has a 24h SLA: it has already run out on the test server's clock.
        Enquiry.objects.filter(pk=enquiry.pk).update(
            stage_entered_at=server_now - timedelta(hours=25)
        )
    return enquiry


def test_enquiry_is_acknowledged_breaches_its_sla_and_ends_when_lost(org, temporal_env):
    enquiry = new_enquiry(org, temporal_env)
    dispatch_batch()  # enquiry.received → EnquiryFollowUpWorkflow
    for _ in range(100):  # the breach happens straight away (the deadline has passed)
        with tenant_context(org):
            enquiry.refresh_from_db()
        if enquiry.sla_breached_at:
            break
        time.sleep(0.1)
    assert enquiry.sla_breached_at is not None
    with tenant_context(org):
        assert Message.objects.filter(type_key="enquiry_acknowledgement").exists()
        services.lose(enquiry, reason="no_response")  # signal "closed"
    assert temporal_env.result(enquiry_workflow_id(org.pk, enquiry.pk)) == "breaches:1"


def test_unanswered_offer_expires(org, temporal_env):
    with tenant_context(org):
        settings_service.update_settings("leads", {"leads.waitlist_auto_cascade": False})
        family = ClientFactory(organisation=org)
        entry = services.add_to_waitlist(
            student=StudentFactory(organisation=org, client=family), subject="Maths"
        )
        with transaction.atomic():
            services.offer_place(entry, details="Tuesdays", hours=1)
    dispatch_batch()  # waitlist.place_offered → WaitlistOfferWorkflow
    assert temporal_env.result(offer_workflow_id(org.pk, entry.pk)) == "expired:none"
    with tenant_context(org):
        assert WaitlistEntry.objects.get(pk=entry.pk).status == "expired"


@pytest.mark.parametrize("prefix", ["EnquiryFollowUpWorkflow", "WaitlistOfferWorkflow"])
def test_histories_replay(prefix):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob(f"{prefix}-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[EnquiryFollowUpWorkflow, WaitlistOfferWorkflow],
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
    test_enquiry_is_acknowledged_breaches_its_sla_and_ends_when_lost(org, temporal_env)
    with tenant_context(org):
        enquiry = Enquiry.objects.get()
    wid = enquiry_workflow_id(org.pk, enquiry.pk)
    (HISTORIES / "EnquiryFollowUpWorkflow-breached.json").write_text(temporal_env.history_json(wid))
    test_unanswered_offer_expires(org, temporal_env)
    with tenant_context(org):
        entry = WaitlistEntry.objects.get()
    oid = offer_workflow_id(org.pk, entry.pk)
    (HISTORIES / "WaitlistOfferWorkflow-expired.json").write_text(temporal_env.history_json(oid))
