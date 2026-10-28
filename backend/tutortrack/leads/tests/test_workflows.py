"""E17-TW1: waitlist offers on Temporal."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.leads import services
from tutortrack.leads.models import WaitlistEntry
from tutortrack.leads.processes import WaitlistOfferWorkflow, offer_workflow_id
from tutortrack.people.tests.factories import ClientFactory, StudentFactory
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


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


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("WaitlistOfferWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[WaitlistOfferWorkflow],
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
    test_unanswered_offer_expires(org, temporal_env)
    with tenant_context(org):
        entry = WaitlistEntry.objects.get()
    oid = offer_workflow_id(org.pk, entry.pk)
    (HISTORIES / "WaitlistOfferWorkflow-expired.json").write_text(temporal_env.history_json(oid))
