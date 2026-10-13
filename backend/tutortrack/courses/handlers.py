"""Courses reactions to domain events (idempotent) and the Temporal bridge (E20-TW1)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows import bridge

from .processes import (
    EnrolmentInput,
    EnrolmentPaymentWorkflow,
    RolloverInput,
    TermRolloverWorkflow,
    payment_workflow_id,
    rollover_workflow_id,
)


def _running(workflow_id: str) -> bool:
    from tutortrack.core.models import WorkflowLink

    return WorkflowLink.objects.filter(workflow_id=workflow_id, status="running").exists()


@subscribe("class.places_freed")
def offer_free_places(event: EventEnvelope) -> None:
    """FR-20-5: offer free places to the class waitlist (time-limited offers, E17)."""
    from . import services

    services.fill_vacancies(event.subject["id"])


@subscribe("waitlist.expired", "waitlist.place_declined")
def offer_to_the_next(event: EventEnvelope) -> None:
    """A class place offer ran out or was turned down: offer it to the next student."""
    from . import services

    if event.data.get("group_class_id"):
        services.fill_vacancies(event.data["group_class_id"])


@subscribe("waitlist.place_accepted")
def enrol_from_waitlist(event: EventEnvelope) -> None:
    from . import services

    if event.data.get("group_class_id"):
        services.enrol_from_waitlist(event.subject["id"])


@subscribe("lesson.completed")
def session_delivered(event: EventEnvelope) -> None:
    from . import services

    services.session_lesson_completed(event.subject["id"])


@subscribe("enrolment.created", "enrolment.confirmed")
def tell_the_family(event: EventEnvelope) -> None:
    from tutortrack.comms import services as comms

    from .notifications import load_enrolment

    if event.type == "enrolment.created" and event.data.get("status") != "enrolled":
        return  # trials and places held for payment are confirmed later
    enrolment = load_enrolment(event.subject["id"])
    if enrolment is not None:
        comms.notify("class_enrolment_confirmed", enrolment, key=f"enrolment:{enrolment.pk}")


@subscribe("class.below_minimum", "class.full")
def tell_staff(event: EventEnvelope) -> None:
    from tutortrack.comms import services as comms

    from .models import GroupClass

    group_class = GroupClass.objects.select_related("course").filter(pk=event.subject["id"]).first()
    if group_class is None:
        return
    name = f"{group_class.course.name} \N{EN DASH} {group_class.name}"
    if event.type == "class.full":
        payload = (f"{name} is full", "New families can join the waitlist.")
        key = "staff_class_full"
    else:
        payload = (
            f"{name} is below its minimum size",
            f"{event.data.get('enrolled')} enrolled; the minimum is {event.data.get('min_size')}.",
        )
        key = "staff_class_below_minimum"
    comms.notify(key, (*payload, f"/classes/{group_class.pk}"), key=f"{key}:{event.id}")


# --- Temporal bridge (E20-TW1) ------------------------------------------------------------------


def _enrolment_for_request(event: EventEnvelope) -> str | None:
    from .models import Enrolment

    enrolment = Enrolment.objects.filter(payment_request_id=event.subject["id"]).first()
    return str(enrolment.pk) if enrolment is not None else None


bridge.on(
    "enrolment.created",
    start=EnrolmentPaymentWorkflow,
    when=lambda e: e.data.get("status") == "pending_payment",
    id=lambda e: payment_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: EnrolmentInput(
        organisation_id=str(e.organisation_id), enrolment_id=e.subject["id"]
    ),
)
bridge.on(
    "payment_request.paid",
    signal="payment_received",
    id=lambda e: payment_workflow_id(e.organisation_id, _enrolment_for_request(e)),
    when=lambda e: (
        _enrolment_for_request(e) is not None
        and _running(payment_workflow_id(e.organisation_id, _enrolment_for_request(e)))
    ),
)
bridge.on(
    "enrolment.released",
    signal="cancelled",
    id=lambda e: payment_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: (
        e.data.get("reason") != "unpaid"
        and _running(payment_workflow_id(e.organisation_id, e.subject["id"]))
    ),
)
bridge.on(
    "term.rollover_started",
    start=TermRolloverWorkflow,
    id=lambda e: rollover_workflow_id(e.organisation_id, e.subject["id"]),
    input=lambda e: RolloverInput(
        organisation_id=str(e.organisation_id), rollover_id=e.subject["id"]
    ),
)
bridge.on(
    "term.rollover_responded",
    signal="responded",
    id=lambda e: rollover_workflow_id(e.organisation_id, e.subject["id"]),
    when=lambda e: _running(rollover_workflow_id(e.organisation_id, e.subject["id"])),
)
