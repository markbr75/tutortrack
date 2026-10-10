"""Keep the fact tables in step with the operational apps (E26-T01, FR-26-7).

Every handler re-reads the source record, so they are idempotent and safe to replay.
"""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from . import facts

LESSON_EVENTS = (
    "lesson.scheduled",
    "lesson.updated",
    "lesson.rescheduled",
    "lesson.cancelled",
    "lesson.completed",
    "lesson.missed",
    "lesson.locked_edited",
    "lesson.unconfirmed",
    "attendance.recorded",
)


@subscribe(*LESSON_EVENTS)
def lesson_changed(event: EventEnvelope) -> None:
    from tutortrack.payroll.models import PayItem

    lesson_id = event.subject["id"]
    facts.refresh_lesson(lesson_id)
    # Pay for a cancelled or changed lesson is voided or re-priced without its own event.
    for item_id in PayItem.objects.filter(lesson_id=lesson_id).values_list("pk", flat=True):
        facts.refresh_pay_item(item_id)


@subscribe("charge.created", "charge.voided")
def charge_changed(event: EventEnvelope) -> None:
    facts.refresh_charge(event.subject["id"])


@subscribe(
    "invoice.drafted",
    "invoice.issued",
    "invoice.voided",
    "invoice.written_off",
    "credit_note.issued",
)
def invoice_changed(event: EventEnvelope) -> None:
    """Charges move to "invoiced" (or back) with their invoice."""
    from tutortrack.billing.models import Charge

    from .models import FactCharge

    invoice_id = event.data.get("invoice_id") or event.subject["id"]
    ids = set(Charge.objects.filter(invoice_id=invoice_id).values_list("pk", flat=True))
    ids |= set(FactCharge.objects.filter(invoice_id=invoice_id).values_list("charge_id", flat=True))
    for charge_id in ids:
        facts.refresh_charge(charge_id)


@subscribe(
    "payment.succeeded",
    "payment.pending",
    "payment.refunded",
    "payment.disputed",
    "payment.dispute_closed",
)
def payment_changed(event: EventEnvelope) -> None:
    facts.refresh_payment(event.subject["id"])


@subscribe("pay_item.created", "pay_item.held", "pay_item.released")
def pay_item_changed(event: EventEnvelope) -> None:
    facts.refresh_pay_item(event.subject["id"])


@subscribe("pay_run.created", "pay_run.approved", "pay_run.paid", "pay_run.partially_failed")
def pay_run_changed(event: EventEnvelope) -> None:
    from tutortrack.payroll.models import PayItem

    from .models import FactPayItem

    run_id = event.subject["id"]
    ids = set(PayItem.objects.filter(pay_run_id=run_id).values_list("pk", flat=True))
    ids |= set(FactPayItem.objects.filter(pay_run_id=run_id).values_list("pay_item_id", flat=True))
    for item_id in ids:
        facts.refresh_pay_item(item_id)


@subscribe("scheduled_report.saved", "scheduled_report.deleted")
def follow_schedule(event: EventEnvelope) -> None:
    """Keep the report's Temporal Schedule in step (removed when paused or deleted)."""
    from . import services

    services.sync_schedule(event.subject["id"])
