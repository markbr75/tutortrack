"""The MVP notification catalogue (FR-13-2): types, recipients, template variables and
default templates. Contexts are plain dicts of whitelisted values (never models)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from django.utils.translation import gettext_lazy as _

from .registry import Delivery, NotificationType, Recipient, register

# --- helpers --------------------------------------------------------------------------------------


def organisation() -> dict[str, str]:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return {"name": org.name, "timezone": org.timezone}


def tenant_link(path: str) -> str:
    from django.conf import settings

    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return f"https://{org.slug}.{settings.TENANT_BASE_DOMAIN}{path}"


def contact_recipient(contact: Any) -> Recipient:
    return Recipient(
        kind="contact",
        id=str(contact.pk),
        name=contact.full_name,
        first_name=contact.first_name,
        email=contact.email,
        phone=contact.mobile,
        target=("people.client", str(contact.client_id)),
    )


def tutor_recipient(tutor: Any) -> Recipient:
    membership = tutor.membership
    active = membership is not None and membership.status == "active"
    return Recipient(
        kind="tutor",
        id=str(tutor.pk),
        name=tutor.full_name,
        first_name=tutor.display_name or tutor.first_name,
        email=tutor.email,
        phone=tutor.phone,
        user_id=str(membership.user_id) if active else None,
        target=("people.tutor", str(tutor.pk)),
    )


def user_recipient(user: Any) -> Recipient:
    return Recipient(
        kind="user",
        id=str(user.pk),
        name=user.get_full_name() or user.email,
        first_name=user.first_name or user.email,
        email=user.email,
        user_id=str(user.pk),
    )


def client_contacts(client: Any, flag: str | None = None) -> list[Any]:
    """Who hears about a client's matters: contacts who opted in (``receives_*``), else
    the billing/primary contact."""
    contacts = list(client.contacts.all())
    chosen = [c for c in contacts if getattr(c, flag)] if flag else contacts
    if not chosen:
        fallback = client.billing_contact or client.primary_contact
        chosen = [fallback] if fallback else []
    return chosen


def staff_with(codename: str) -> list[Recipient]:
    """Active staff members holding a permission (for staff alerts)."""
    from tutortrack.core.permission_registry import matches
    from tutortrack.identity.models import Membership
    from tutortrack.identity.rbac import grants_for

    out = []
    staff_roles = ["owner", "admin", "branch_manager", "coordinator", "finance"]
    for membership in Membership.objects.filter(
        status=Membership.Status.ACTIVE, role__in=staff_roles
    ).select_related("user"):
        grants, denies = grants_for(membership)
        if any(matches(d, codename) for d in denies):
            continue
        if any(matches(g.pattern, codename) for g in grants):
            out.append(user_recipient(membership.user))
    return out


def _dedupe(recipients: Iterable[Recipient]) -> list[Recipient]:
    seen: dict[tuple[str, str], Recipient] = {}
    for r in recipients:
        seen.setdefault((r.kind, r.id), r)
    return list(seen.values())


# --- lessons ------------------------------------------------------------------------------------


def load_lesson(pk: str) -> Any:
    from tutortrack.scheduling.models import Lesson

    return (
        Lesson.objects.select_related("location", "service")
        .prefetch_related("tutors__tutor__membership", "attendees__student", "attendees__client")
        .filter(pk=pk)
        .first()
    )


def lesson_context(lesson: Any) -> dict[str, Any]:
    tutors = [t.tutor for t in lesson.tutors.all()]
    students = [a.student for a in lesson.attendees.all()]
    return {
        "title": lesson.title,
        "service": lesson.service.name,
        "start": lesson.start,
        "end": lesson.end,
        "timezone": lesson.timezone,
        "duration_minutes": lesson.duration_minutes,
        "online": lesson.online,
        "meeting_url": lesson.meeting_url,
        "location": lesson.location.name if lesson.location else "",
        "tutor_names": ", ".join(t.full_name for t in tutors),
        "student_names": ", ".join(s.full_name for s in students),
        "status_reason": lesson.status_reason,
    }


def lesson_people(lesson: Any, *, clients: bool = True, tutors: bool = True) -> list[Recipient]:
    out: list[Recipient] = []
    if clients:
        for client in {a.client_id: a.client for a in lesson.attendees.all()}.values():
            out += [contact_recipient(c) for c in client_contacts(client, "receives_reminders")]
    if tutors:
        out += [tutor_recipient(t.tutor) for t in lesson.tutors.all()]
    return _dedupe(out)


def lesson_deliveries(lesson: Any, **extra: Any) -> list[Delivery]:
    base = {"organisation": organisation(), "lesson": lesson_context(lesson), **extra}
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in lesson_people(lesson)
    ]


SAMPLE_LESSON = {
    "title": "GCSE Maths \N{EN DASH} Arjun Patel",
    "service": "GCSE Maths 1:1",
    "start": "2026-11-02T16:30:00+00:00",
    "end": "2026-11-02T17:30:00+00:00",
    "timezone": "Europe/London",
    "duration_minutes": 60,
    "online": False,
    "meeting_url": "",
    "location": "Bright Minds Centre",
    "tutor_names": "Nia Adeyemi",
    "student_names": "Arjun Patel",
    "status_reason": "",
}
SAMPLE_BASE = {
    "organisation": {"name": "Bright Minds Tutoring", "timezone": "Europe/London"},
    "recipient": {"name": "Priya Patel", "first_name": "Priya"},
}
LESSON_VARS = (
    "recipient.first_name",
    "organisation.name",
    "lesson.title",
    "lesson.start",
    "lesson.end",
    "lesson.location",
    "lesson.online",
    "lesson.meeting_url",
    "lesson.tutor_names",
    "lesson.student_names",
)


def _lesson_type(key: str, label: Any, **options: Any) -> NotificationType:
    return register(
        NotificationType(
            key=key,
            label=str(label),
            category="scheduling",
            audience=options.pop("audience", "client"),
            channels=("email", "sms", "in_app"),
            default_channels=options.pop("default_channels", ("email",)),
            resolve=options.pop("resolve", lambda lesson: lesson_deliveries(lesson)),
            load=load_lesson,
            related_type="scheduling.lesson",
            variables=LESSON_VARS,
            sample={**SAMPLE_BASE, "lesson": SAMPLE_LESSON},
            link=lambda lesson: f"/calendar?lesson={lesson.pk}",
            **options,
        )
    )


_lesson_type("lesson_booked", _("Lesson booked"))
_lesson_type("lesson_changed", _("Lesson moved"), default_channels=("email", "in_app"))
_lesson_type("lesson_cancelled", _("Lesson cancelled"), default_channels=("email", "in_app"))
_lesson_type(
    "lesson_reminder",
    _("Lesson reminder"),
    default_channels=("email", "sms"),
    default_timing=(24 * 60, 120),
)


def _series_resolve(series: Any) -> list[Delivery]:
    from tutortrack.scheduling.models import Lesson

    upcoming = list(
        Lesson.objects.filter(series=series, status=Lesson.Status.PLANNED)
        .order_by("start")
        .prefetch_related("tutors__tutor__membership", "attendees__client", "attendees__student")
        .select_related("service", "location")[:6]
    )
    if not upcoming:
        return []
    first = upcoming[0]
    base = {
        "organisation": organisation(),
        "lesson": lesson_context(first),
        "upcoming": [{"start": lesson.start} for lesson in upcoming],
        "rule": series.rrule,
    }
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in lesson_people(first, tutors=False)
    ]


def load_series(pk: str) -> Any:
    from tutortrack.scheduling.models import LessonSeries

    return LessonSeries.objects.filter(pk=pk).first()


register(
    NotificationType(
        key="series_created",
        label=str(_("Regular lessons arranged")),
        category="scheduling",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_series_resolve,
        load=load_series,
        related_type="scheduling.lessonseries",
        variables=(*LESSON_VARS, "upcoming"),
        sample={
            **SAMPLE_BASE,
            "lesson": SAMPLE_LESSON,
            "upcoming": [{"start": SAMPLE_LESSON["start"]}],
        },
    )
)


def load_job(pk: str) -> Any:
    from tutortrack.jobs.models import Job

    return Job.objects.select_related("client", "service").filter(pk=pk).first()


def _tutor_assigned(payload: Any) -> list[Delivery]:
    job, tutor = payload
    r = tutor_recipient(tutor)
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "job": {"name": job.name, "reference": job.reference, "service": job.service.name},
            },
        )
    ]


register(
    NotificationType(
        key="tutor_assigned",
        label=str(_("Tutor assigned to a job")),
        category="scheduling",
        audience="tutor",
        channels=("email", "in_app"),
        default_channels=("email", "in_app"),
        resolve=_tutor_assigned,
        load=load_job,
        related_type="jobs.job",
        variables=("recipient.first_name", "job.name", "job.reference", "job.service"),
        sample={
            **SAMPLE_BASE,
            "job": {
                "name": "GCSE Maths \N{EN DASH} Arjun",
                "reference": "JOB-000001",
                "service": "GCSE Maths 1:1",
            },
        },
    )
)

# --- reports ------------------------------------------------------------------------------------


def load_report(pk: str) -> Any:
    from tutortrack.delivery.models import LessonReport

    return (
        LessonReport.objects.select_related("lesson", "tutor__membership", "lesson__service")
        .prefetch_related("lesson__attendees__client")
        .filter(pk=pk)
        .first()
    )


def report_context(report: Any) -> dict[str, Any]:
    return {
        "lesson_title": report.lesson.title,
        "lesson_start": report.lesson.start,
        "tutor_name": report.tutor.full_name,
        "due_at": report.due_at,
        "link": tenant_link(f"/reports/{report.pk}"),
    }


def _report_to_clients(report: Any) -> list[Delivery]:
    from tutortrack.delivery import templates

    fields = report.template_version.fields
    visible = templates.visible_answers(fields, report.answers or {}, "client")
    answers = [
        {"label": f["label"], "value": visible[f["key"]]} for f in fields if f["key"] in visible
    ]
    base = {
        "organisation": organisation(),
        "report": {**report_context(report), "answers": answers},
    }
    out = []
    for client in {a.client_id: a.client for a in report.lesson.attendees.all()}.values():
        for c in client_contacts(client, "receives_reports"):
            r = contact_recipient(c)
            out.append(
                Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
            )
    return out


def _report_to_tutor(report: Any) -> list[Delivery]:
    r = tutor_recipient(report.tutor)
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "report": report_context(report),
            },
        )
    ]


SAMPLE_REPORT = {
    "lesson_title": "GCSE Maths \N{EN DASH} Arjun Patel",
    "lesson_start": SAMPLE_LESSON["start"],
    "tutor_name": "Nia Adeyemi",
    "due_at": "2026-11-03T17:30:00+00:00",
    "link": "https://brightminds.tutortrack.app/reports/1",
    "answers": [{"label": "What we covered", "value": "Fractions and ratio"}],
}
REPORT_VARS = ("recipient.first_name", "report.lesson_title", "report.tutor_name",
               "report.due_at", "report.link", "report.answers")  # fmt: skip

register(
    NotificationType(
        key="report_shared",
        label=str(_("Lesson report shared with the family")),
        category="reports",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_report_to_clients,
        load=load_report,
        related_type="delivery.lessonreport",
        variables=REPORT_VARS,
        sample={**SAMPLE_BASE, "report": SAMPLE_REPORT},
    )
)
for _key, _label in (
    ("report_due", _("Report due soon (to the tutor)")),
    ("report_overdue", _("Report overdue (to the tutor)")),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="reports",
            audience="tutor",
            channels=("email", "sms", "in_app"),
            default_channels=("email", "in_app"),
            resolve=_report_to_tutor,
            load=load_report,
            related_type="delivery.lessonreport",
            variables=REPORT_VARS,
            sample={**SAMPLE_BASE, "report": SAMPLE_REPORT},
            link=lambda report: f"/reports/{report.pk}",
        )
    )


def _unconfirmed(lesson: Any) -> list[Delivery]:
    base = {"organisation": organisation(), "lesson": lesson_context(lesson)}
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in lesson_people(lesson, clients=False)
    ]


_lesson_type(
    "lesson_unconfirmed",
    _("Lesson not confirmed (to the tutor)"),
    audience="tutor",
    default_channels=("email", "in_app"),
    resolve=_unconfirmed,
)


def _absence(payload: Any) -> list[Delivery]:
    lesson, student_name, note = payload
    base = {
        "organisation": organisation(),
        "lesson": lesson_context(lesson),
        "absence": {"student": student_name, "note": note},
    }
    return [
        Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
        for r in lesson_people(lesson, clients=False)
    ]


_lesson_type(
    "absence_notified",
    _("Student will be absent (to the tutor)"),
    audience="tutor",
    default_channels=("email", "in_app"),
    resolve=_absence,
)


def _report_comment(payload: Any) -> list[Delivery]:
    report, author, body = payload
    r = tutor_recipient(report.tutor)
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "report": report_context(report),
                "comment": {"author": author, "body": body},
            },
        )
    ]


register(
    NotificationType(
        key="report_comment",
        label=str(_("Family replied to a report (to the tutor)")),
        category="reports",
        audience="tutor",
        channels=("email", "in_app"),
        default_channels=("email", "in_app"),
        resolve=_report_comment,
        load=load_report,
        related_type="delivery.lessonreport",
        variables=(*REPORT_VARS, "comment.author", "comment.body"),
        sample={
            **SAMPLE_BASE,
            "report": SAMPLE_REPORT,
            "comment": {"author": "Priya Patel", "body": "Thank you!"},
        },
        link=lambda payload: f"/reports/{payload[0].pk}",
    )
)

# --- billing ------------------------------------------------------------------------------------


def load_invoice(pk: str) -> Any:
    from tutortrack.billing.models import Invoice

    return Invoice.objects.select_related("client").filter(pk=pk).first()


def money(value: Any) -> dict[str, str]:
    return value.round_to_minor().to_dict()


def invoice_context(invoice: Any) -> dict[str, Any]:
    return {
        "number": invoice.number,
        "total": money(invoice.total),
        "balance_due": money(invoice.balance_due),
        "due_date": invoice.due_date.isoformat() if invoice.due_date else "",
        "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else "",
        "pay_url": tenant_link(f"/pay/{invoice.pay_token}") if invoice.pay_token else "",
    }


def _billing_deliveries(client: Any, extra: dict[str, Any]) -> list[Delivery]:
    base = {"organisation": organisation(), **extra}
    return [
        Delivery(
            contact_recipient(c),
            {**base, "recipient": {"name": c.full_name, "first_name": c.first_name}},
        )
        for c in client_contacts(client, "receives_invoices")
    ]


def _invoice(invoice: Any) -> list[Delivery]:
    return _billing_deliveries(invoice.client, {"invoice": invoice_context(invoice)})


def _invoice_pdf(invoice: Any) -> list[tuple[str, bytes, str]]:
    from tutortrack.billing import pdf

    return [(f"{invoice.number}.pdf", pdf.invoice_pdf(invoice), "application/pdf")]


SAMPLE_INVOICE = {
    "number": "INV-000123",
    "total": {"amount": "160.00", "currency": "GBP"},
    "balance_due": {"amount": "160.00", "currency": "GBP"},
    "due_date": "2026-11-14",
    "issue_date": "2026-10-31",
    "pay_url": "https://brightminds.tutortrack.app/pay/abc",
}
INVOICE_VARS = ("recipient.first_name", "invoice.number", "invoice.total",
                "invoice.balance_due", "invoice.due_date", "invoice.pay_url")  # fmt: skip

register(
    NotificationType(
        key="invoice_issued",
        label=str(_("Invoice issued (with the PDF)")),
        category="billing",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_invoice,
        load=load_invoice,
        related_type="billing.invoice",
        variables=INVOICE_VARS,
        sample={**SAMPLE_BASE, "invoice": SAMPLE_INVOICE},
        transactional=True,
        attachments=_invoice_pdf,
    )
)


def _invoice_reminder(payload: Any) -> list[Delivery]:
    invoice, offset = payload
    return _billing_deliveries(
        invoice.client, {"invoice": invoice_context(invoice), "days_overdue": max(offset, 0)}
    )


register(
    NotificationType(
        key="invoice_reminder",
        label=str(_("Payment reminder")),
        category="billing",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_invoice_reminder,
        load=load_invoice,
        related_type="billing.invoice",
        variables=(*INVOICE_VARS, "days_overdue"),
        sample={**SAMPLE_BASE, "invoice": SAMPLE_INVOICE, "days_overdue": 7},
        transactional=True,
    )
)


def load_payment(pk: str) -> Any:
    from tutortrack.payments.models import Payment

    return Payment.objects.select_related("client").filter(pk=pk).first()


def _payment(payment: Any) -> list[Delivery]:
    return _billing_deliveries(
        payment.client,
        {
            "payment": {
                "amount": money(payment.amount),
                "method": payment.get_method_display(),
                "reference": payment.reference,
                "received_at": payment.received_at,
            }
        },
    )


def _receipt_pdf(payment: Any) -> list[tuple[str, bytes, str]]:
    from tutortrack.payments import pdf

    return [(f"receipt-{payment.pk}.pdf", pdf.receipt_pdf(payment), "application/pdf")]


register(
    NotificationType(
        key="payment_received",
        label=str(_("Payment received (receipt)")),
        category="billing",
        audience="client",
        channels=("email",),
        default_channels=("email",),
        resolve=_payment,
        load=load_payment,
        related_type="payments.payment",
        variables=(
            "recipient.first_name",
            "payment.amount",
            "payment.method",
            "payment.reference",
        ),
        sample={
            **SAMPLE_BASE,
            "payment": {
                "amount": {"amount": "40.00", "currency": "GBP"},
                "method": "Card",
                "reference": "pi_123",
            },
        },
        transactional=True,
        attachments=_receipt_pdf,
    )
)
register(
    NotificationType(
        key="payment_failed",
        label=str(_("Automatic payment failed")),
        category="billing",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_invoice,
        load=load_invoice,
        related_type="billing.invoice",
        variables=INVOICE_VARS,
        sample={**SAMPLE_BASE, "invoice": SAMPLE_INVOICE},
        transactional=True,
    )
)


def load_request(pk: str) -> Any:
    from tutortrack.billing.models import PaymentRequest

    return PaymentRequest.objects.select_related("client").filter(pk=pk).first()


def _request(request: Any) -> list[Delivery]:
    return _billing_deliveries(
        request.client,
        {
            "request": {
                "number": request.number,
                "amount": money(request.amount - request.amount_paid),
                "description": request.description,
                "pay_url": tenant_link(f"/pay/{request.pay_token}") if request.pay_token else "",
            }
        },
    )


register(
    NotificationType(
        key="payment_request",
        label=str(_("Payment request (top-up)")),
        category="billing",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_request,
        load=load_request,
        related_type="billing.paymentrequest",
        variables=(
            "recipient.first_name",
            "request.number",
            "request.amount",
            "request.pay_url",
        ),
        sample={
            **SAMPLE_BASE,
            "request": {
                "number": "PR-000004",
                "amount": {"amount": "200.00", "currency": "GBP"},
                "description": "Credit top-up",
                "pay_url": "https://brightminds.tutortrack.app/pay/xyz",
            },
        },
    )
)


def load_client(pk: str) -> Any:
    from tutortrack.people.models import Client

    return Client.objects.filter(pk=pk).first()


def _balance_low(payload: Any) -> list[Delivery]:
    client, available = payload
    return _billing_deliveries(client, {"available": available})


register(
    NotificationType(
        key="balance_low",
        label=str(_("Prepaid credit running low")),
        category="billing",
        audience="client",
        channels=("email", "sms"),
        default_channels=("email",),
        resolve=_balance_low,
        load=load_client,
        related_type="people.client",
        variables=("recipient.first_name", "available"),
        sample={**SAMPLE_BASE, "available": {"amount": "12.00", "currency": "GBP"}},
    )
)

# --- staff alerts (in-app first) ----------------------------------------------------------------


def _alert(codename: str) -> Any:
    def resolve(payload: Any) -> list[Delivery]:
        title, body, link = payload
        base = {
            "organisation": organisation(),
            "alert": {"title": title, "body": body, "link": link},
        }
        return [
            Delivery(r, {**base, "recipient": {"name": r.name, "first_name": r.first_name}})
            for r in staff_with(codename)
        ]

    return resolve


SAMPLE_ALERT = {**SAMPLE_BASE, "alert": {"title": "A report is overdue", "body": "", "link": "/"}}
for _key, _label, _code in (
    ("staff_report_escalated", _("Overdue report escalated"), "delivery.report.approve"),
    ("staff_completion_blocked", _("Lesson blocked: client needs credit"), "billing.invoice.view"),
    ("staff_payment_failed", _("Automatic payment failed after retries"), "payments.payment.view"),
    ("staff_dispute", _("Card payment disputed"), "payments.payment.view"),
    ("staff_profile_change", _("A family changed sensitive details"), "people.student.edit"),
):
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="staff",
            audience="staff",
            channels=("in_app", "email"),
            default_channels=("in_app",),
            resolve=_alert(_code),
            load=lambda pk: None,
            related_type="",
            variables=("alert.title", "alert.body", "alert.link"),
            sample=SAMPLE_ALERT,
            link=lambda payload: payload[2],
        )
    )


def _task(task: Any) -> list[Delivery]:
    if task.assignee_id is None:
        return []
    r = user_recipient(task.assignee)
    due = task.due_at
    return [
        Delivery(
            r,
            {
                "organisation": organisation(),
                "recipient": {"name": r.name, "first_name": r.first_name},
                "task": {"title": task.title, "due_at": due, "link": "/tasks"},
            },
        )
    ]


def load_task(pk: str) -> Any:
    from tutortrack.crm.models import Task

    return Task.objects.select_related("assignee").filter(pk=pk).first()


register(
    NotificationType(
        key="task_assigned",
        label=str(_("Task assigned to you")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=_task,
        load=load_task,
        related_type="crm.task",
        variables=("task.title", "task.due_at"),
        sample={**SAMPLE_BASE, "task": {"title": "Call the Patels", "due_at": None}},
        link=lambda task: "/tasks",
    )
)


def reminder_window(now: datetime, minutes: int) -> tuple[datetime, datetime]:
    """Lessons whose reminder at ``minutes`` before the start falls due in the last hour."""
    end = now + timedelta(minutes=minutes)
    return end - timedelta(hours=1), end
