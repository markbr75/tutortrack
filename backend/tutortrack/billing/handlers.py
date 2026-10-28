"""Billing reactions to domain events (idempotent). Payment chasing and payment request
reminders are built-in workflows (E33 T04, ``workflows_builtin.py``)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe(
    "lesson.completed",
    "lesson.cancelled",
    "attendance.recorded",
    "lesson.updated",
    "lesson.locked_edited",
)
def sync_charges(event: EventEnvelope) -> None:
    """Charges follow what happened to the lesson (FR-10-2)."""
    from . import services

    services.sync_lesson_charges(event.subject["id"])


@subscribe("invoice_run.tutor_review_requested")
def ask_tutors(event: EventEnvelope) -> None:
    """Gap G3: tell each tutor to check their lessons on the drafts (deduplicated)."""
    from tutortrack.comms.services import notify
    from tutortrack.people.models import TutorProfile

    from .models import InvoiceRun

    run = InvoiceRun.objects.filter(pk=event.subject["id"]).first()
    if run is None:
        return
    for tutor in TutorProfile.objects.filter(pk__in=event.data.get("tutor_ids") or []):
        notify("tutor_invoice_review", (run, tutor), key=f"{run.pk}:{tutor.pk}")


@subscribe("invoice_run.tutor_reviewed")
def tell_staff_about_flags(event: EventEnvelope) -> None:
    if event.data.get("status") != "flagged":
        return
    from django.utils.translation import gettext as _

    from tutortrack.comms.services import notify
    from tutortrack.people.models import TutorProfile

    tutor = TutorProfile.objects.filter(pk=event.data.get("tutor_id")).first()
    held = len(event.data.get("held_invoice_ids") or [])
    title = _("%(tutor)s reported a problem with draft invoices") % {
        "tutor": tutor.full_name if tutor else _("A tutor")
    }
    body = _("%(n)s draft invoice(s) are held until you check them.") % {"n": held}
    notify(
        "staff_invoice_review_flagged",
        (title, body, f"/billing?run={event.subject['id']}"),
        key=str(event.id),
    )


@subscribe("invoice.issued", "invoice.paid")
def activate_packages(event: EventEnvelope) -> None:
    """A package can be used once its invoice is paid (or issued, setting) (E10-T12)."""
    from . import packages

    packages.activate_for_invoice(event.subject["id"])


@subscribe("package.depleted")
def renew_package(event: EventEnvelope) -> None:
    if event.data.get("auto_renew"):
        from . import packages

        packages.renew(event.subject["id"])


@subscribe("invoice.paid", "invoice.voided", "invoice.written_off")
def leave_collections(event: EventEnvelope) -> None:
    """Nothing overdue on the invoice any more: its collections case closes (E10-T14)."""
    from . import dunning

    dunning.close_collections(event.subject["id"], reason=event.type)
