"""The Temporal bridge for job offers and cover requests (E19-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope
from tutortrack.core.workflows import bridge

from .processes import (
    CascadeInput,
    CoverInput,
    CoverRequestWorkflow,
    JobOfferCascadeWorkflow,
    cover_workflow_id,
    offer_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


def _cascade_input(e: EventEnvelope) -> CascadeInput:
    from .models import OfferBatch

    batch = OfferBatch.objects.get(pk=e.subject["id"])
    return CascadeInput(
        organisation_id=str(e.organisation_id),
        batch_id=str(batch.pk),
        expiry_hours=batch.expiry_hours,
        admin_confirms=batch.admin_confirms,
    )


bridge.on(
    "job_offer.batch_started",
    start=JobOfferCascadeWorkflow,
    id=lambda e: offer_workflow_id(e.organisation_id, e.subject["id"]),
    input=_cascade_input,
)
for _answer in ("job_offer.accepted", "job_offer.declined", "job_offer.withdrawn"):
    bridge.on(
        _answer,
        signal="responded",
        id=lambda e: offer_workflow_id(e.organisation_id, e.data["batch_id"]),
        when=lambda e: _running(offer_workflow_id(e.organisation_id, e.data["batch_id"])),
    )
bridge.on(
    "job_offer.decided",
    signal="decided",
    id=lambda e: offer_workflow_id(e.organisation_id, e.data["batch_id"]),
    when=lambda e: _running(offer_workflow_id(e.organisation_id, e.data["batch_id"])),
)
bridge.on(
    "job_offer.batch_closed",
    signal="cancelled",
    id=lambda e: offer_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: (
        e.data["status"] == "cancelled"
        and _running(offer_workflow_id(e.organisation_id, e.subject["id"]))
    ),
)
bridge.on(
    "cover_request.created",
    start=CoverRequestWorkflow,
    id=lambda e: cover_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: CoverInput(
        organisation_id=str(e.organisation_id),
        request_id=e.subject["id"],
        deadline=e.data["deadline"],
    ),
)
for _event, _signal in (
    ("cover_request.accepted", "accepted"),
    ("cover_request.cancelled", "cancelled"),
):
    bridge.on(
        _event,
        signal=_signal,
        id=lambda e: cover_workflow_id(e.organisation_id, e.subject["id"]),
        when=lambda e: _running(cover_workflow_id(e.organisation_id, e.subject["id"])),
    )
