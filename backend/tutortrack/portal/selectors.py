"""Portal reads (E15): every function takes the viewer's ``Household``."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db.models import Q, QuerySet

from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from .household import Household
from .models import Announcement


def lesson_card(lesson: Any, household: Household) -> dict[str, Any]:
    """A lesson as families see it (no internal notes, no pay)."""
    show_contact = bool(get_setting("portal.show_tutor_contact"))
    students = [a for a in lesson.attendees.all() if a.student_id in set(household.student_ids)]
    return {
        "id": str(lesson.pk),
        "title": lesson.title,
        "start": lesson.start,
        "end": lesson.end,
        "timezone": lesson.timezone,
        "status": lesson.status,
        "online": lesson.online,
        "meeting_url": lesson.meeting_url,
        "location": lesson.location.name if lesson.location else "",
        "notes_for_client": lesson.notes_for_client,
        "tutors": [
            {
                "name": t.tutor.full_name,
                "email": t.tutor.email if show_contact else "",
                "phone": t.tutor.phone if show_contact else "",
            }
            for t in lesson.tutors.all()
        ],
        "students": [
            {"id": str(a.student_id), "name": a.student.full_name, "outcome": a.outcome}
            for a in students
        ],
    }


def lessons(household: Household) -> QuerySet[Any]:
    return (
        household.lessons()
        .select_related("location", "service")
        .prefetch_related("tutors__tutor", "attendees__student")
    )


def schedule(
    household: Household, start: datetime, end: datetime, student: str | None = None
) -> list[dict[str, Any]]:
    qs = lessons(household).filter(start__lt=end, end__gt=start).order_by("start")
    if student:
        qs = qs.filter(attendees__student_id=student)
    return [lesson_card(lesson, household) for lesson in qs]


def shared_reports(household: Household) -> QuerySet[Any]:
    from tutortrack.delivery.models import LessonReport

    return (
        LessonReport.objects.filter(
            shared_at__isnull=False, lesson__attendees__student_id__in=household.student_ids
        )
        .distinct()
        .select_related("lesson", "tutor", "template_version")
        .order_by("-lesson__start")
    )


def report_out(report: Any, household: Household) -> dict[str, Any]:
    from tutortrack.delivery import templates

    audience = "client" if household.is_client else "student"
    fields = report.template_version.fields
    visible = templates.visible_answers(fields, report.answers or {}, audience)
    return {
        "id": str(report.pk),
        "lesson_title": report.lesson.title,
        "lesson_start": report.lesson.start,
        "tutor_name": report.tutor.full_name,
        "shared_at": report.shared_at,
        "answers": [
            {"label": f["label"], "type": f["type"], "value": visible[f["key"]]}
            for f in fields
            if f["key"] in visible
        ],
        "comments": [
            {"author": c.author_name, "body": c.body, "created_at": c.created_at}
            for c in report.comments.filter(visibility="client")
        ],
    }


def announcements(household: Household | None, audience: str = "clients") -> QuerySet[Any]:
    moment = now()
    return Announcement.objects.filter(
        audience__in=[audience, Announcement.Audience.EVERYONE], published_at__lte=moment
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=moment))


def billing(household: Household) -> dict[str, Any]:
    from tutortrack.billing import ledger
    from tutortrack.billing.models import CreditNote, Invoice, PaymentRequest

    invoices = Invoice.objects.filter(client_id__in=household.client_ids).exclude(
        status__in=[Invoice.Status.DRAFT, Invoice.Status.VOID]
    )
    requests = PaymentRequest.objects.filter(
        client_id__in=household.client_ids, status=PaymentRequest.Status.OPEN
    )
    return {
        "accounts": [
            {
                "client": str(c.pk),
                "name": c.display_name,
                "balances": ledger.balances(c).as_dict(),
                "auto_pay": c.auto_pay,
            }
            for c in household.clients
        ],
        "invoices": [
            {
                "id": str(i.pk),
                "number": i.number,
                "status": i.status,
                "issue_date": i.issue_date,
                "due_date": i.due_date,
                "total": i.total.to_dict(),
                "balance_due": i.balance_due.to_dict(),
                "pay_token": i.pay_token if i.is_open else "",
                "pdf_token": i.pay_token,
            }
            for i in invoices.order_by("-issue_date")[:100]
        ],
        "payment_requests": [
            {
                "id": str(r.pk),
                "number": r.number,
                "description": r.description,
                "amount": (r.amount - r.amount_paid).to_dict(),
                "pay_token": r.pay_token,
            }
            for r in requests
        ],
        "credit_notes": [
            {
                "id": str(n.pk),
                "number": n.number,
                "invoice_number": n.invoice.number,
                "total": n.total.to_dict(),
                "issued_at": n.issued_at,
            }
            for n in CreditNote.objects.filter(client_id__in=household.client_ids)
            .select_related("invoice")
            .order_by("-issued_at")[:50]
        ],
    }


def dashboard(household: Household) -> dict[str, Any]:
    moment = now()
    upcoming = list(
        lessons(household)
        .filter(status="planned", end__gt=moment, start__lt=moment + timedelta(days=7))
        .order_by("start")[:20]
    )
    out: dict[str, Any] = {
        "next_lesson": lesson_card(upcoming[0], household) if upcoming else None,
        "upcoming": [lesson_card(lesson, household) for lesson in upcoming[1:]],
        "reports": (
            [report_out(r, household) for r in shared_reports(household)[:3]]
            if get_setting("portal.show_reports")
            else []
        ),
        "announcements": [
            {"id": str(a.pk), "title": a.title, "body": a.body, "published_at": a.published_at}
            for a in announcements(household)[:3]
        ],
        "amount_due": None,
        "credit": None,
    }
    if household.is_client and get_setting("portal.show_invoices") and household.clients:
        from tutortrack.billing import ledger

        first = ledger.balances(household.clients[0])
        out["amount_due"] = first.invoice_balance.to_dict()
        out["credit"] = first.available_credit.to_dict()
    return out
