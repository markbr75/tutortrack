"""Delivery reactions to domain events (idempotent) and the Temporal bridge (E09-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    FeedbackInput,
    LessonFeedbackWorkflow,
    LessonReportSlaWorkflow,
    ReportSlaInput,
    feedback_workflow_id,
    sla_workflow_id,
    unconfirmed_workflow_id,
)


def _running(workflow_id: str) -> bool:
    """Only signal processes that exist (most lessons are completed before one starts)."""
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("organisation.created")
def create_default_report_template(event: EventEnvelope) -> None:
    from . import services

    services.ensure_default_template()


bridge.on(
    "lesson_report.requested",
    start=LessonReportSlaWorkflow,
    id=lambda e: sla_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ReportSlaInput(
        organisation_id=str(e.organisation_id),
        report_id=e.subject["id"],
        due_at=e.data["due_at"],
    ),
)
bridge.on(
    "lesson_report.submitted",
    signal="submitted",
    id=lambda e: sla_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(sla_workflow_id(e.organisation_id, e.subject["id"])),
)


for _event_type in ("lesson.completed", "lesson.cancelled"):
    bridge.on(
        _event_type,
        signal="resolved",
        id=lambda e: unconfirmed_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(unconfirmed_workflow_id(e.organisation_id, e.subject["id"])),
    )


# --- client feedback micro-surveys (E09-T09) ------------------------------------------------


def _feedback_wanted(event: EventEnvelope) -> bool:
    """Surveys on, and someone attended (the workflow decides who is asked)."""
    from tutortrack.tenancy.settings_service import get_setting

    if not get_setting("delivery.feedback_enabled"):
        return False
    return any(a.get("outcome") in ("present", "late", "") for a in event.data["attendees"])


bridge.on(
    "lesson.completed",
    start=LessonFeedbackWorkflow,
    when=_feedback_wanted,
    id=lambda e: feedback_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: FeedbackInput(
        organisation_id=str(e.organisation_id),
        lesson_id=e.subject["id"],
        completed_at=e.occurred_at.isoformat(),
    ),
)
bridge.on(
    "lesson_feedback.received",
    signal="answered",
    id=lambda e: feedback_workflow_id(e.organisation_id, e.data["lesson_id"]),
    when=lambda e: _running(feedback_workflow_id(e.organisation_id, e.data["lesson_id"])),
)
