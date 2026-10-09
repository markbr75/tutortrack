"""E02-TW1: organisation closure on Temporal (export, notice, grace, reopen or deletion)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent, WorkflowLink
from tutortrack.identity.tests.factories import TEST_PASSWORD, MembershipFactory
from tutortrack.tenancy import lifecycle, settings_service
from tutortrack.tenancy.closure import OrganisationClosureWorkflow, closure_workflow_id
from tutortrack.tenancy.models import Organisation

pytestmark = pytest.mark.django_db(transaction=True)


def close(org):
    owner = MembershipFactory(organisation=org, role="owner", user__email="owner@example.com").user
    lifecycle.close_organisation(
        org, user=owner, password=TEST_PASSWORD, confirm_slug=org.slug, reason="Retiring"
    )
    dispatch_batch()  # the outbox → Temporal bridge starts the workflow
    return closure_workflow_id(org.pk)


def events(org) -> list[str]:
    return list(
        OutboxEvent.objects.filter(organisation_id=org.pk)
        .order_by("occurred_at", "id")
        .values_list("event_type", flat=True)
    )


def test_closure_runs_through_the_grace_period_to_deletion(org, temporal_env):
    wid = close(org)
    with tenant_context(org):
        link = WorkflowLink.objects.get(workflow_id=wid)
    assert link.process == "org-closure"
    state = temporal_env.run(temporal_env.handle(wid).query(OrganisationClosureWorkflow.state))
    assert state["step"] in {"starting", "exporting", "grace_period"}

    started = temporal_env.run(temporal_env.env.get_current_time())
    assert temporal_env.result(wid) == "deletion_due"
    elapsed = temporal_env.run(temporal_env.env.get_current_time()) - started
    assert elapsed >= timedelta(days=30)

    assert {"organisation.export_requested", "organisation.deletion_due"} <= set(events(org))
    assert mail.outbox[0].to == ["owner@example.com"]
    assert "closed" in mail.outbox[0].subject
    with tenant_context(org):
        link.refresh_from_db()
    assert (link.status, link.current_step) == ("completed", "deletion_due")


def test_grace_period_comes_from_settings(org, temporal_env):
    with tenant_context(org):
        settings_service.update_settings("privacy", {"privacy.closure_grace_days": 7})
    wid = close(org)
    assert temporal_env.result(wid) == "deletion_due"
    state = temporal_env.run(temporal_env.handle(wid).query(OrganisationClosureWorkflow.state))
    assert state["grace_days"] == "7"  # snapshotted at start


def test_platform_can_reopen_during_the_grace_period(org, temporal_env):
    wid = close(org)
    temporal_env.skip(timedelta(days=3))
    assert lifecycle.request_reopen(Organisation.objects.get(pk=org.pk)) is True
    assert temporal_env.result(wid) == "reopened"
    org.refresh_from_db()
    assert org.status == Organisation.Status.ACTIVE
    assert org.closed_at is None
    assert "organisation.deletion_due" not in events(org)
    assert "organisation.reactivated" in events(org)


def test_bridge_starts_closure_once(org, temporal_env):
    wid = close(org)
    # Re-delivering the event (outbox retry) does not start a second process.
    OutboxEvent.objects.filter(event_type="organisation.closed").update(
        dispatched_at=None, attempts=0
    )
    from tutortrack.core.models import ProcessedEvent

    ProcessedEvent.objects.all().delete()
    dispatch_batch()
    with tenant_context(org):
        assert WorkflowLink.objects.filter(process="org-closure").count() == 1
    temporal_env.result(wid)


def test_closure_history_replays():
    import json
    from pathlib import Path

    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import data_converter
    from tutortrack.core.workflows.worker import sandbox_runner

    folder = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
    files = sorted(folder.glob("OrganisationClosureWorkflow*.json"))
    assert files, "record with RECORD_WORKFLOW_HISTORIES=1 (see the README there)"
    replayer = Replayer(
        workflows=[OrganisationClosureWorkflow],
        data_converter=data_converter(),
        workflow_runner=sandbox_runner(),
    )
    for path in files:
        runtime.run(
            replayer.replay_workflow(
                WorkflowHistory.from_json(path.stem, json.loads(path.read_text()))
            )
        )


def test_record_history_if_requested(org, temporal_env):
    import os
    from pathlib import Path

    if not os.environ.get("RECORD_WORKFLOW_HISTORIES"):
        pytest.skip("set RECORD_WORKFLOW_HISTORIES=1 to (re)record")
    wid = close(org)
    temporal_env.result(wid)
    folder = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
    (folder / "OrganisationClosureWorkflow-deletion.json").write_text(
        temporal_env.history_json(wid)
    )
