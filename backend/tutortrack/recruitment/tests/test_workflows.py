"""E18-TW1: compliance expiry, references, onboarding and application workflows."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads.models import Form
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.recruitment import compliance, services
from tutortrack.recruitment.models import (
    ComplianceRecord,
    JobOpening,
    ReferenceRequest,
    TutorApplication,
)
from tutortrack.recruitment.processes import (
    ComplianceRecordWorkflow,
    ReferenceRequestWorkflow,
    TutorApplicationWorkflow,
    TutorOnboardingWorkflow,
    application_workflow_id,
    compliance_workflow_id,
    onboarding_workflow_id,
    reference_workflow_id,
)

pytestmark = pytest.mark.django_db(transaction=True)
HISTORIES = Path(__file__).resolve().parents[3] / "tests" / "workflow_histories"
SCHEMA = {"steps": [{"title": "You", "fields": [
    {"key": "first_name", "label": "First", "type": "text", "maps_to": "applicant.first_name"},
    {"key": "email", "label": "Email", "type": "email", "maps_to": "applicant.email"},
]}]}  # fmt: skip


def test_verified_check_reminds_then_expires_and_restricts(org, temporal_env):
    server_today = temporal_env.run(temporal_env.env.get_current_time()).date()
    with tenant_context(org):
        membership = MembershipFactory(organisation=org, role="tutor")
        tutor = TutorProfileFactory(organisation=org, status="active", membership=membership)
        verifier = MembershipFactory(organisation=org, role="admin").user
        compliance.ensure_requirement_types()
        expiry = max(server_today, compliance.today()) + timedelta(days=10)
        for requirement in compliance.applicable(tutor):
            if requirement.mandatory and requirement.blocking:
                with transaction.atomic():
                    record = compliance.submit(
                        tutor,
                        requirement,
                        number="123",
                        expiry_date=expiry if requirement.has_expiry else None,
                    )
                    compliance.verify(record, user=verifier)
        dbs = ComplianceRecord.objects.get(requirement__key="dbs_enhanced")
    dispatch_batch()  # compliance.record_verified → ComplianceRecordWorkflow (per expiring record)
    wid = compliance_workflow_id(org.pk, dbs.pk, expiry.isoformat())
    assert temporal_env.result(wid) == "expired"
    with tenant_context(org):
        tutor.refresh_from_db()
        assert tutor.status == "restricted"
        expiring = [
            r.pk
            for r in ComplianceRecord.objects.exclude(pk=dbs.pk).filter(expiry_date__isnull=False)
        ]
    for pk in expiring:  # the other records with an expiry run to the same end
        temporal_env.result(compliance_workflow_id(org.pk, pk, expiry.isoformat()))


def application(org) -> TutorApplication:
    with tenant_context(org):
        form = Form.objects.create(
            name="Apply", slug="apply", type="application", schema=SCHEMA, published=True
        )
        opening = JobOpening.objects.create(
            title="Tutors", slug="tutors", form=form, published=True
        )
        with transaction.atomic():
            return services.apply(opening, {"first_name": "Nia", "email": "nia@example.com"})


def test_reference_without_reply_expires_and_application_closes(org, temporal_env):
    made = application(org)
    with tenant_context(org), transaction.atomic():
        reference, _token = services.request_reference(made, name="Jo", email="jo@example.com")
    dispatch_batch()
    assert temporal_env.result(reference_workflow_id(org.pk, reference.pk)) == "expired"
    with tenant_context(org):
        assert ReferenceRequest.objects.get(pk=reference.pk).status == "expired"
        with transaction.atomic():
            services.reject(made, reason="Not now", notify=False)
    dispatch_batch()  # application.rejected → signal "closed"
    assert temporal_env.result(application_workflow_id(org.pk, made.pk)).startswith("reminders:")


def test_onboarding_finishes_when_the_checklist_is_done(org, temporal_env):
    made = application(org)
    with tenant_context(org):
        recruiter = MembershipFactory(organisation=org, role="admin").user
        with transaction.atomic():
            tutor = services.approve(made, user=recruiter)
            template_items = [
                {"key": "agreement", "label": "Agree", "kind": "agreement", "mandatory": True}
            ]
            from tutortrack.recruitment.models import ChecklistInstance

            ChecklistInstance.objects.filter(tutor=tutor).update(items=template_items)
    dispatch_batch()  # onboarding.started → TutorOnboardingWorkflow; application closes
    with tenant_context(org), transaction.atomic():
        services.complete_item(tutor, "agreement", user=recruiter)
    dispatch_batch()  # onboarding.item_done → signal
    assert temporal_env.result(onboarding_workflow_id(org.pk, tutor.pk)) == "complete"
    with tenant_context(org):
        tutor.refresh_from_db()
    assert tutor.status == "active"
    temporal_env.result(application_workflow_id(org.pk, made.pk))


@pytest.mark.parametrize(
    "prefix",
    [
        "ComplianceRecordWorkflow",
        "ReferenceRequestWorkflow",
        "TutorOnboardingWorkflow",
        "TutorApplicationWorkflow",
    ],
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
        workflows=[
            ComplianceRecordWorkflow,
            ReferenceRequestWorkflow,
            TutorOnboardingWorkflow,
            TutorApplicationWorkflow,
        ],
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
    made = application(org)
    with tenant_context(org), transaction.atomic():
        reference, _token = services.request_reference(made, name="Jo", email="jo@example.com")
    dispatch_batch()
    rid = reference_workflow_id(org.pk, reference.pk)
    temporal_env.result(rid)
    (HISTORIES / "ReferenceRequestWorkflow-expired.json").write_text(temporal_env.history_json(rid))
    with tenant_context(org):
        recruiter = MembershipFactory(organisation=org, role="admin").user
        with transaction.atomic():
            tutor = services.approve(made, user=recruiter)
            from tutortrack.recruitment.models import ChecklistInstance

            ChecklistInstance.objects.filter(tutor=tutor).update(
                items=[{"key": "agreement", "label": "A", "kind": "agreement", "mandatory": True}]
            )
    dispatch_batch()
    with tenant_context(org), transaction.atomic():
        services.complete_item(tutor, "agreement", user=recruiter)
    dispatch_batch()
    oid = onboarding_workflow_id(org.pk, tutor.pk)
    temporal_env.result(oid)
    (HISTORIES / "TutorOnboardingWorkflow-complete.json").write_text(temporal_env.history_json(oid))
    aid = application_workflow_id(org.pk, made.pk)
    temporal_env.result(aid)
    (HISTORIES / "TutorApplicationWorkflow-hired.json").write_text(temporal_env.history_json(aid))
    test_verified_check_reminds_then_expires_and_restricts(org, temporal_env)
    with tenant_context(org):
        dbs = ComplianceRecord.objects.get(requirement__key="dbs_enhanced")
    cid = compliance_workflow_id(org.pk, dbs.pk, dbs.expiry_date.isoformat())
    (HISTORIES / "ComplianceRecordWorkflow-expired.json").write_text(temporal_env.history_json(cid))
