"""E33-T09: moving to Workflows. Automations from before E33 are custom workflows, and runs
of the per-record workflows the built-ins replaced are ended once their code is gone."""

from __future__ import annotations

import pytest

from tutortrack.automations import services
from tutortrack.automations.models import Automation
from tutortrack.core.context import tenant_context
from tutortrack.core.models import WorkflowLink
from tutortrack.core.time import now
from tutortrack.core.workflows import ops

pytestmark = pytest.mark.django_db


def link(process: str, ref: str, status: str = WorkflowLink.Status.RUNNING) -> WorkflowLink:
    return WorkflowLink.objects.create(
        workflow_id=f"{process}:{ref}", workflow_type="Old", process=process,
        status=status, started_at=now(),
    )  # fmt: skip


def test_installing_the_built_ins_ends_open_runs_of_the_workflows_they_replaced(
    org, other_org, monkeypatch, django_capture_on_commit_callbacks
):
    ended = []
    monkeypatch.setattr(ops, "terminate_now", lambda wid, reason: ended.append(wid))
    with tenant_context(org):
        dunning = link("invoice-dunning", "i1")
        review = link("review-request", "r1")
        finished = link("report-sla", "s1", WorkflowLink.Status.COMPLETED)
        kept = link("invoice-run", "run1")  # still a live workflow
    with tenant_context(other_org):
        elsewhere = link("lesson-feedback", "l1")
    with django_capture_on_commit_callbacks(execute=True), tenant_context(org):
        services.install_builtins()
    assert sorted(ended) == sorted([dunning.workflow_id, review.workflow_id])
    with tenant_context(org):
        statuses = dict(WorkflowLink.objects.values_list("workflow_id", "status"))
    assert statuses[dunning.workflow_id] == statuses[review.workflow_id] == "terminated"
    assert statuses[finished.workflow_id] == "completed"
    assert statuses[kept.workflow_id] == "running"
    with tenant_context(other_org):
        assert WorkflowLink.objects.get(pk=elsewhere.pk).status == "running"


def test_a_run_temporal_cant_reach_is_tried_again_and_a_gone_one_is_closed(org, monkeypatch):
    def unreachable(wid, reason):
        raise RuntimeError("connection refused")

    with tenant_context(org):
        stuck = link("enquiry", "e1")
    monkeypatch.setattr(ops, "terminate_now", unreachable)
    assert services._end_replaced_runs(org.pk) == 0
    with tenant_context(org):
        assert WorkflowLink.objects.get(pk=stuck.pk).status == "running"

    def gone(wid, reason):
        raise RuntimeError("workflow execution not found")

    monkeypatch.setattr(ops, "terminate_now", gone)
    assert services._end_replaced_runs(org.pk) == 1
    with tenant_context(org):
        assert WorkflowLink.objects.get(pk=stuck.pk).status == "terminated"


def test_automations_from_before_e33_are_custom_workflows(org, api):
    with tenant_context(org):
        old = Automation.objects.create(
            name="Chase unpaid invoices", trigger_type="event",
            trigger_config={"event": "invoice.issued"}, steps=[], enabled=True,
        )  # fmt: skip
    assert old.kind == Automation.Kind.CUSTOM
    listed = api.get("/api/v1/workflows").json()
    rows = listed["results"] if isinstance(listed, dict) else listed
    assert [w["kind"] for w in rows if w["id"] == str(old.pk)] == ["custom"]
