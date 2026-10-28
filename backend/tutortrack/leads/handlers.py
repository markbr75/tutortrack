"""Leads reactions to domain events and the Temporal bridge (E17-TW1).

The Enquiry follow-up and stage time limits built-in workflows acknowledge enquiries and
watch the stage time limits (E33 T06, ``workflows_builtin.py``)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    OfferInput,
    ProposalInput,
    ProposalWorkflow,
    WaitlistOfferWorkflow,
    offer_workflow_id,
    proposal_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("lesson.missed")
def trial_lesson_missed(event: EventEnvelope) -> None:
    """E33: the trial lesson was missed: ``trial_lesson.no_show`` for the enquiry."""
    from . import services

    services.note_trial_no_show(event.subject["id"])


@subscribe("job.status_changed", "job.tutor_removed")
def place_may_be_free(event: EventEnvelope) -> None:
    """A job ended or lost a tutor: tell staff if students are waiting for that subject."""
    from tutortrack.comms import services as comms
    from tutortrack.jobs.models import Job

    from .models import WaitlistEntry

    if event.type == "job.status_changed" and event.data.get("to_status") not in (
        "completed",
        "cancelled",
        "paused",
    ):
        return
    job = Job.objects.select_related("service__subject").filter(pk=event.subject["id"]).first()
    if job is None:
        return
    subject = job.service.subject.name if job.service and job.service.subject_id else ""
    waiting = WaitlistEntry.objects.filter(status=WaitlistEntry.Status.WAITING)
    if subject:
        waiting = waiting.filter(subject__iexact=subject)
    count = waiting.count()
    if count:
        title = f"{count} waiting" + (f" for {subject}" if subject else "")
        comms.notify(
            "staff_enquiry_sla",
            (title, "A place may have come free.", "/leads/waitlist"),
            key=f"waitlist:{job.pk}:{event.id}",
        )


@subscribe(
    "availability.updated",
    "job.status_changed",
    "job.tutor_removed",
    "tutor.status_changed",
    "tutor.unrestricted",
)
def suggest_on_capacity(event: EventEnvelope) -> None:
    """Gap G5c (FR-17-6): a tutor may have room, so suggest them for waiting students.
    Idempotent: one suggestion per entry and tutor; the staff notice is keyed on the event."""
    from .suggestions import capacity_appeared

    capacity_appeared(event)


bridge.on(
    "waitlist.place_offered",
    start=WaitlistOfferWorkflow,
    id=lambda e: offer_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: OfferInput(
        organisation_id=str(e.organisation_id),
        entry_id=e.subject["id"],
        expires_at=e.data["expires_at"],
    ),
)
for _responded in ("waitlist.place_accepted", "waitlist.place_declined"):
    bridge.on(
        _responded,
        signal="responded",
        id=lambda e: offer_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(offer_workflow_id(e.organisation_id, e.subject["id"])),
    )


# --- proposals (E17-T09) --------------------------------------------------------------------

bridge.on(
    "proposal.sent",
    start=ProposalWorkflow,
    id=lambda e: proposal_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: ProposalInput(
        organisation_id=str(e.organisation_id),
        proposal_id=e.subject["id"],
        expires_at=e.data["expires_at"],
    ),
)
for _answered in ("proposal.accepted", "proposal.declined", "proposal.withdrawn"):
    bridge.on(
        _answered,
        signal="responded",
        id=lambda e: proposal_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(proposal_workflow_id(e.organisation_id, e.subject["id"])),
    )
