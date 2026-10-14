"""E17-T09: ``ProposalWorkflow`` on Temporal: reminder then expiry, and the family's answer
ending it early; plus replay of recorded histories."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.workflows import start_now
from tutortrack.leads import proposals, services
from tutortrack.leads.models import Proposal
from tutortrack.leads.processes import ProposalInput, ProposalWorkflow, proposal_workflow_id

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"


def make_proposal(org) -> Proposal:
    with tenant_context(org):
        enquiry = services.create_enquiry(
            contact={"first_name": "Priya", "email": "priya@example.com"},
            students=[{"first_name": "Arjun"}],
        )
        service = ServiceFactory(organisation=org)
        return proposals.save_proposal(
            enquiry, lines=[{"service": str(service.pk), "quantity": "4", "unit_price": "40"}]
        )


def send_at_server_time(org, temporal_env, proposal) -> None:
    """Send, then start the workflow with a deadline on the test server's clock."""
    server_now = temporal_env.run(temporal_env.env.get_current_time())
    with tenant_context(org), transaction.atomic():
        proposal = proposals.send(proposal)
    expires = server_now + timedelta(days=14)
    start_now(
        ProposalWorkflow,
        ProposalInput(
            organisation_id=str(org.pk),
            proposal_id=str(proposal.pk),
            expires_at=expires.isoformat(),
        ),
        id=proposal_workflow_id(org.pk, proposal.pk),
        subject=("proposal", str(proposal.pk)),
    )


def test_unanswered_proposal_is_reminded_then_expires(org, temporal_env):
    proposal = make_proposal(org)
    send_at_server_time(org, temporal_env, proposal)
    assert temporal_env.result(proposal_workflow_id(org.pk, proposal.pk)) == "expired"
    with tenant_context(org):
        assert Proposal.objects.get(pk=proposal.pk).status == "expired"
        keys = list(
            Message.objects.filter(type_key="proposal_sent").values_list("dedupe_key", flat=True)
        )
        assert any("proposal-reminder" in key for key in keys)


def test_accepting_ends_the_workflow(org, temporal_env):
    proposal = make_proposal(org)
    send_at_server_time(org, temporal_env, proposal)
    with tenant_context(org):
        proposals.accept(proposals.token_for(proposal), name="Priya Patel")
    dispatch_batch()  # proposal.accepted → signal "responded"
    assert temporal_env.result(proposal_workflow_id(org.pk, proposal.pk)) == "responded"
    with tenant_context(org):
        assert Proposal.objects.get(pk=proposal.pk).status == "accepted"


def test_histories_replay():
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    files = sorted(HISTORIES.glob("ProposalWorkflow-*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[ProposalWorkflow],
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
    test_unanswered_proposal_is_reminded_then_expires(org, temporal_env)
    with tenant_context(org):
        proposal = Proposal.objects.get()
    wid = proposal_workflow_id(org.pk, proposal.pk)
    (HISTORIES / "ProposalWorkflow-expired.json").write_text(temporal_env.history_json(wid))
