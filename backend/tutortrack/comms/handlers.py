"""Domain events → notifications (FR-13-2, E13-T05). Each delivery is keyed so redelivered
events never send twice."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.events import EventEnvelope, subscribe

from . import catalogue
from .services import notify


def _id(event: EventEnvelope) -> str:
    return str(event.subject["id"])


@subscribe("lesson.scheduled")
def lesson_booked(event: EventEnvelope) -> None:
    if event.data.get("series_id"):
        return  # the series gets one summary message instead
    lesson = catalogue.load_lesson(_id(event))
    if lesson is not None:
        notify("lesson_booked", lesson, key=str(event.id))


@subscribe("lesson.rescheduled")
def lesson_changed(event: EventEnvelope) -> None:
    if not event.data.get("notify", True):
        return
    lesson = catalogue.load_lesson(_id(event))
    if lesson is not None:
        notify("lesson_changed", lesson, key=str(event.id))


@subscribe("lesson.cancelled")
def lesson_cancelled(event: EventEnvelope) -> None:
    if not event.data.get("notify", True):
        return
    lesson = catalogue.load_lesson(_id(event))
    if lesson is not None:
        notify("lesson_cancelled", lesson, key=str(event.id))


@subscribe("lesson_series.created")
def series_created(event: EventEnvelope) -> None:
    series = catalogue.load_series(_id(event))
    if series is not None:
        notify("series_created", series, key=_id(event))


@subscribe("job.tutor_assigned")
def tutor_assigned(event: EventEnvelope) -> None:
    from tutortrack.people.models import TutorProfile

    job = catalogue.load_job(_id(event))
    tutor = TutorProfile.objects.filter(pk=event.data.get("tutor_id")).first()
    if job is not None and tutor is not None:
        notify("tutor_assigned", (job, tutor), key=str(event.id))


@subscribe("lesson_report.shared")
def report_shared(event: EventEnvelope) -> None:
    report = catalogue.load_report(_id(event))
    if report is not None:
        notify("report_shared", report, key=_id(event))


@subscribe("lesson_report.due", "lesson_report.overdue")
def report_reminders(event: EventEnvelope) -> None:
    report = catalogue.load_report(_id(event))
    if report is not None:
        kind = "report_due" if event.type.endswith(".due") else "report_overdue"
        notify(kind, report, key=_id(event))


@subscribe("lesson.unconfirmed")
def lesson_unconfirmed(event: EventEnvelope) -> None:
    lesson = catalogue.load_lesson(_id(event))
    if lesson is not None:
        notify("lesson_unconfirmed", lesson, key=str(event.id))


@subscribe("invoice.reminder")
def invoice_reminder(event: EventEnvelope) -> None:
    invoice = catalogue.load_invoice(_id(event))
    if invoice is not None and invoice.is_open:
        offset = int(event.data.get("offset_days", 0))
        notify("invoice_reminder", (invoice, offset), key=f"{invoice.pk}:{offset}")


@subscribe("payment.failed")
def payment_failed(event: EventEnvelope) -> None:
    invoice = catalogue.load_invoice(_id(event))
    if invoice is None:
        return
    attempt = event.data.get("attempt", 1)
    notify("payment_failed", invoice, key=f"{invoice.pk}:{attempt}")
    if event.data.get("final"):
        _alert(
            "staff_payment_failed",
            _("Automatic payment failed for invoice %(n)s") % {"n": invoice.number},
            _("Every retry failed. The client has been sent a pay-now link."),
            f"/invoices/{invoice.pk}",
            key=f"{invoice.pk}",
        )


@subscribe("payment_request.created", "payment_request.sent")
def payment_request(event: EventEnvelope) -> None:
    request = catalogue.load_request(_id(event))
    if request is not None and request.status == "open":
        notify("payment_request", request, key=str(event.id))


@subscribe("client.balance_low")
def balance_low(event: EventEnvelope) -> None:
    client = catalogue.load_client(_id(event))
    if client is not None:
        notify("balance_low", (client, event.data.get("available")), key=str(event.id))


def _alert(type_key: str, title: str, body: str, link: str, *, key: str) -> None:
    notify(type_key, (title, body, link), key=key)


@subscribe("lesson_report.escalated")
def report_escalated(event: EventEnvelope) -> None:
    report = catalogue.load_report(_id(event))
    if report is not None:
        _alert(
            "staff_report_escalated",
            _("Report overdue: %(lesson)s") % {"lesson": report.lesson.title},
            _("%(tutor)s hasn't written it yet.") % {"tutor": report.tutor.full_name},
            f"/reports/{report.pk}",
            key=_id(event),
        )


@subscribe("lesson.completion_blocked")
def completion_blocked(event: EventEnvelope) -> None:
    lesson = catalogue.load_lesson(_id(event))
    if lesson is not None:
        _alert(
            "staff_completion_blocked",
            _("A client needs to top up: %(lesson)s") % {"lesson": lesson.title},
            _("The tutor couldn't complete the lesson because the client has too little credit."),
            "/billing",
            key=str(event.id),
        )


@subscribe("payment.disputed")
def payment_disputed(event: EventEnvelope) -> None:
    amount: Any = event.data.get("amount") or {}
    _alert(
        "staff_dispute",
        _("A card payment was disputed (%(amount)s %(currency)s)")
        % {"amount": amount.get("amount", ""), "currency": amount.get("currency", "")},
        _("Respond in Stripe before the evidence deadline."),
        "/billing",
        key=str(event.data.get("dispute_id") or event.id),
    )


@subscribe("task.created")
def task_assigned(event: EventEnvelope) -> None:
    if not event.data.get("assignee_id"):
        return
    task = catalogue.load_task(_id(event))
    if task is not None:
        notify("task_assigned", task, key=_id(event))
