"""Recruitment and compliance reactions to events, and the Temporal bridge (E18-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    COMPLIANCE_PROCESS,
    ApplicationInput,
    ComplianceInput,
    ComplianceRecordWorkflow,
    OnboardingInput,
    ReferenceInput,
    ReferenceRequestWorkflow,
    TutorApplicationWorkflow,
    TutorOnboardingWorkflow,
    application_workflow_id,
    compliance_workflow_id,
    onboarding_workflow_id,
    reference_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("compliance.record_verified")
def follow_expiry(event: EventEnvelope) -> None:
    """A (re)verified record with an expiry: end the previous run, start one for this date."""
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now, start_now
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.settings_service import get_setting

    expiry = event.data.get("expiry_date")
    record_id = event.subject["id"]
    new_id = compliance_workflow_id(event.organisation_id, record_id, expiry or "none")
    for link in WorkflowLink.objects.filter(
        process=COMPLIANCE_PROCESS, status="running", subject_id=record_id
    ).exclude(workflow_id=new_id):
        signal_now(link.workflow_id, "renewed")
    if not expiry or event.organisation_id is None:
        return
    org = Organisation.objects.get(pk=event.organisation_id)
    start_now(
        ComplianceRecordWorkflow,
        ComplianceInput(
            organisation_id=str(event.organisation_id),
            record_id=record_id,
            expiry=expiry,
            timezone=org.timezone,
            reminder_days=[int(d) for d in get_setting("compliance.reminder_days") or []],
        ),
        id=new_id,
        subject=("compliance_record", record_id),
    )


@subscribe(
    "compliance.record_verified",
    "compliance.record_rejected",
    "compliance.expired",
    "availability.updated",
)
def refresh_onboarding(event: EventEnvelope) -> None:
    """Document and availability items may have just been completed."""
    from tutortrack.core.workflows import signal_now

    tutor_id = event.data.get("tutor_id") or (
        event.subject["id"] if event.subject.get("type") == "tutor" else None
    )
    if tutor_id is None and event.type == "availability.updated":
        tutor_id = event.data.get("tutor")
    if not tutor_id:
        return
    wid = onboarding_workflow_id(event.organisation_id, tutor_id)
    if _running(wid):
        signal_now(wid, "item_done")


bridge.on(
    "application.submitted",
    start=TutorApplicationWorkflow,
    id=lambda e: application_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ApplicationInput(
        organisation_id=str(e.organisation_id), application_id=e.subject["id"]
    ),
)
bridge.on(
    "application.stage_changed",
    signal="stage_changed",
    id=lambda e: application_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(application_workflow_id(e.organisation_id, e.subject["id"])),
)
for _closed in ("application.approved", "application.rejected"):
    bridge.on(
        _closed,
        signal="closed",
        id=lambda e: application_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(application_workflow_id(e.organisation_id, e.subject["id"])),
    )
bridge.on(
    "reference.requested",
    start=ReferenceRequestWorkflow,
    id=lambda e: reference_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ReferenceInput(
        organisation_id=str(e.organisation_id), reference_id=e.subject["id"]
    ),
)
bridge.on(
    "reference.received",
    signal="received",
    id=lambda e: reference_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(reference_workflow_id(e.organisation_id, e.subject["id"])),
)
bridge.on(
    "onboarding.started",
    start=TutorOnboardingWorkflow,
    id=lambda e: onboarding_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: OnboardingInput(
        organisation_id=str(e.organisation_id), tutor_id=e.subject["id"]
    ),
)
bridge.on(
    "onboarding.item_done",
    signal="item_done",
    id=lambda e: onboarding_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(onboarding_workflow_id(e.organisation_id, e.subject["id"])),
)
