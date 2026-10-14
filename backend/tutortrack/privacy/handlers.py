"""Privacy reactions to domain events (idempotent) and the Temporal bridge (E29-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    DataSubjectRequestWorkflow,
    LoneWorkingWorkflow,
    RequestInput,
    VisitInput,
    dsar_workflow_id,
    lone_working_workflow_id,
)
from .services import ensure_default_types


@subscribe("organisation.created")
def create_default_consent_types(event: EventEnvelope) -> None:
    ensure_default_types()


@subscribe("organisation.created")
def create_default_retention_policies(event: EventEnvelope) -> None:
    from .retention import ensure_policies

    ensure_policies()


@subscribe("organisation.settings_updated")
def follow_retention_schedule(event: EventEnvelope) -> None:
    keys = set(event.data.get("keys") or [])
    if event.data.get("area") == "privacy" and "privacy.retention_purge" in keys:
        from .schedules import sync_retention_schedule

        sync_retention_schedule()


@subscribe("lesson_report.commented")
def screen_report_comment(event: EventEnvelope) -> None:
    """Tutor-family conversation on lesson reports is screened and flagged (never blocked:
    it has already been shared)."""
    from tutortrack.delivery.models import LessonReportComment

    from .safeguards import screen_text

    comment = LessonReportComment.objects.filter(pk=event.data.get("comment_id")).first()
    if comment is None:
        return
    screen_text(
        text=comment.body,
        source_type="delivery.lessonreportcomment",
        source_id=str(comment.pk),
        sender_id=str(comment.author_id) if comment.author_id else None,
    )


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


# --- Temporal bridge ----------------------------------------------------------------------------

bridge.on(
    "data_request.received",
    start=DataSubjectRequestWorkflow,
    id=lambda e: dsar_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: RequestInput(
        organisation_id=str(e.organisation_id), request_id=e.subject["id"]
    ),
    subject=lambda e: ("data_request", e.subject["id"]),
)
bridge.on(
    "lone_working.checked_in",
    start=LoneWorkingWorkflow,
    id=lambda e: lone_working_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: VisitInput(organisation_id=str(e.organisation_id), visit_id=e.subject["id"]),
    subject=lambda e: ("lone_working_visit", e.subject["id"]),
)
bridge.on(
    "lone_working.checked_out",
    signal="checked_out",
    id=lambda e: lone_working_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(lone_working_workflow_id(e.organisation_id, e.subject["id"])),
)
