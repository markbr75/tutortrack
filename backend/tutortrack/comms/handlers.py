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
    if event.data.get("series_id") or not event.data.get("notify", True):
        return  # the series gets one summary message instead; imports stay quiet
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
    if not event.data.get("notify", True):
        return  # imported series (E28)
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


@subscribe("package.expiring")
def package_expiring(event: EventEnvelope) -> None:
    purchase = catalogue.load_package(_id(event))
    if purchase is not None and purchase.status == "active":
        notify("package_expiring", purchase, key=str(event.id))


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


@subscribe("attendance.absence_notified")
def absence_notified(event: EventEnvelope) -> None:
    from tutortrack.people.models import Student

    lesson = catalogue.load_lesson(_id(event))
    student = Student.objects.filter(pk=event.data.get("student_id")).first()
    if lesson is not None and student is not None:
        payload = (lesson, student.full_name, event.data.get("note", ""))
        notify("absence_notified", payload, key=str(event.id))


@subscribe("lesson_report.commented")
def report_commented(event: EventEnvelope) -> None:
    from tutortrack.delivery.models import LessonReportComment

    if event.data.get("visibility") != "client":
        return
    comment = LessonReportComment.objects.filter(pk=event.data.get("comment_id")).first()
    report = catalogue.load_report(_id(event))
    if comment is None or report is None or comment.author_id is None:
        return
    if report.tutor.membership and comment.author_id == report.tutor.membership.user_id:
        return  # the tutor's own comment
    notify("report_comment", (report, comment.author_name, comment.body), key=str(comment.pk))


@subscribe("portal.sensitive_updated")
def sensitive_updated(event: EventEnvelope) -> None:
    _alert(
        "staff_profile_change",
        _("A family updated %(student)s's support needs") % {"student": event.data.get("name", "")},
        _("Check the change on the student's record."),
        f"/students/{_id(event)}",
        key=str(event.id),
    )


@subscribe("payout.paid")
def payout_paid(event: EventEnvelope) -> None:
    payout = catalogue.load_payout(_id(event))
    if payout is not None:
        notify("payout_paid", payout, key=str(event.id))


# --- Phase 2: inbox alerts, marketing sync and the broadcast workflow (E13-T10..T12) -------------


@subscribe("message.received")
def inbox_message_received(event: EventEnvelope) -> None:
    """Staff hear about new messages (the assignee, else whoever assigns conversations):
    at most one alert per thread an hour per person (dedupe key)."""
    from .phase2_types import load_thread_message

    entry = load_thread_message(_id(event))
    if entry is None:
        return
    bucket = event.occurred_at.strftime("%Y%m%d%H")
    notify("inbox_new_message", entry, key=f"{entry.thread_id}:{bucket}")


@subscribe("consent.granted", "consent.withdrawn")
def marketing_consent_changed(event: EventEnvelope) -> None:
    """Keep Mailchimp/Brevo audiences in step with marketing consent (E13-T12)."""
    if not str(event.data.get("category", "")).startswith("marketing_"):
        return
    if event.data.get("person_type") != "people.contact":
        return
    from . import marketing

    marketing.queue_contact_sync(str(event.data.get("person_id", "")))


@subscribe("contact.updated")
def marketing_contact_updated(event: EventEnvelope) -> None:
    from . import marketing

    marketing.queue_contact_sync(_id(event))


def _broadcast_bridge() -> None:
    from tutortrack.core.workflows import bridge

    from .broadcasts import broadcast_workflow_id
    from .processes import BroadcastInput, BroadcastWorkflow

    bridge.on(
        "broadcast.scheduled",
        start=BroadcastWorkflow,
        id=lambda e: broadcast_workflow_id(e.organisation_id, e.subject["id"]),
        input=lambda e: BroadcastInput(
            organisation_id=str(e.organisation_id), broadcast_id=e.subject["id"]
        ),
        subject=lambda e: ("broadcast", e.subject["id"]),
    )


_broadcast_bridge()
