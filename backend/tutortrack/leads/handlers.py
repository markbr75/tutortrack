"""Leads reactions to domain events and the Temporal bridge (E17-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    EnquiryFollowUpWorkflow,
    EnquiryInput,
    OfferInput,
    WaitlistOfferWorkflow,
    enquiry_workflow_id,
    offer_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("lesson.completed")
def trial_lesson_done(event: EventEnvelope) -> None:
    """A trial lesson happened: the follow-up workflow reminds the owner for the outcome."""
    from .models import Enquiry

    enquiry = Enquiry.objects.filter(trial_lesson_id=event.subject["id"]).first()
    if enquiry is None:
        return
    wid = enquiry_workflow_id(enquiry.organisation_id, enquiry.pk)
    if _running(wid):
        from tutortrack.core.workflows import signal_now

        signal_now(wid, "trial_done")


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


bridge.on(
    "enquiry.received",
    start=EnquiryFollowUpWorkflow,
    id=lambda e: enquiry_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: EnquiryInput(
        organisation_id=str(e.organisation_id), enquiry_id=e.subject["id"]
    ),
)
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
