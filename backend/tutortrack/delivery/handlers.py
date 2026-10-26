"""Delivery reactions to domain events (idempotent) and the Temporal bridge (E09-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import feedback_workflow_id, sla_workflow_id, unconfirmed_workflow_id


def _running(workflow_id: str) -> bool:
    """Only signal processes that exist (most lessons are completed before one starts)."""
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("organisation.created")
def create_default_report_template(event: EventEnvelope) -> None:
    from . import services

    services.ensure_default_template()


# Report chasing, the feedback request and the unconfirmed lesson chaser are built-in
# workflows (E33 T05, ``workflows_builtin.py``). The workflows they replaced are no longer
# started; ones already under way still get their signals and finish.
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


bridge.on(
    "lesson_feedback.received",
    signal="answered",
    id=lambda e: feedback_workflow_id(e.organisation_id, e.data["lesson_id"]),
    when=lambda e: _running(feedback_workflow_id(e.organisation_id, e.data["lesson_id"])),
)
