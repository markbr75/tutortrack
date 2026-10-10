"""The platform's subjects, event triggers, predicates and actions (E14-T01/T04/T07)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .conditions import register_predicate
from .registry import FieldDef as F
from .registry import Subject, register_subject, register_trigger


def _d(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _money(value: Any) -> str | None:
    return str(value.amount) if value is not None else None


def _tags(target: str, pk: Any) -> list[str]:
    from tutortrack.crm.services import tags_for

    return [t.name for t in tags_for(target, [str(pk)]).get(str(pk), [])]


def _manager(client: Any) -> Any:
    """The client's account manager as a user (the field holds a membership)."""
    membership = client.account_manager
    return membership.user if membership is not None else None


def _user_name(user: Any) -> str:
    return (user.get_full_name() or user.email) if user is not None else ""


# --- recipients ---------------------------------------------------------------------------------


def _contacts(client: Any) -> list[Any]:
    from tutortrack.comms.catalogue import client_contacts, contact_recipient

    return [contact_recipient(c) for c in client_contacts(client)] if client is not None else []


def _tutors(tutors: Any) -> list[Any]:
    from tutortrack.comms.catalogue import tutor_recipient

    return [tutor_recipient(t) for t in tutors]


def _user(user: Any) -> list[Any]:
    from tutortrack.comms.catalogue import user_recipient

    return [user_recipient(user)] if user is not None else []


# --- contexts -----------------------------------------------------------------------------------


def client_ctx(client: Any) -> dict[str, Any]:
    from tutortrack.billing.selectors import balance_due

    return {
        "id": str(client.pk),
        "name": client.display_name,
        "status": client.status,
        "type": client.type,
        "auto_pay": client.auto_pay,
        "currency": client.currency,
        "balance_due": str(balance_due(client.pk)),
        "account_manager": _user_name(_manager(client)),
        "created_at": _d(client.created_at),
        "tags": _tags("people.client", client.pk),
        "custom": client.custom_fields or {},
    }


def student_ctx(student: Any) -> dict[str, Any]:
    from tutortrack.scheduling.models import Lesson

    last = (
        Lesson.objects.filter(attendees__student=student)
        .exclude(status=Lesson.Status.CANCELLED)
        .filter(start__lte=_now())
        .order_by("-start")
        .values_list("start", flat=True)
        .first()
    )
    return {
        "id": str(student.pk),
        "first_name": student.preferred_name or student.first_name,
        "last_name": student.last_name,
        "full_name": student.full_name,
        "status": student.status,
        "year_group": student.year_group,
        "school": student.school,
        "date_of_birth": _d(student.date_of_birth),
        "subjects": [s.get("subject", "") for s in student.subjects or [] if isinstance(s, dict)],
        "last_lesson_at": _d(last),
        "created_at": _d(student.created_at),
        "tags": _tags("people.student", student.pk),
        "custom": student.custom_fields or {},
        "client": client_ctx(student.client),
    }


def tutor_ctx(tutor: Any) -> dict[str, Any]:
    return {
        "id": str(tutor.pk),
        "first_name": tutor.display_name or tutor.first_name,
        "last_name": tutor.last_name,
        "full_name": tutor.full_name,
        "email": tutor.email,
        "status": tutor.status,
        "employment_type": tutor.employment_type,
        "years_experience": tutor.years_experience,
        "created_at": _d(tutor.created_at),
        "tags": _tags("people.tutor", tutor.pk),
    }


def _now() -> datetime:
    from tutortrack.core.time import now

    return now()


def lesson_ctx(lesson: Any) -> dict[str, Any]:
    from tutortrack.scheduling.models import Lesson

    attendees = list(lesson.attendees.select_related("student"))
    first = any(
        not Lesson.objects.filter(attendees__student=a.student, start__lt=lesson.start)
        .exclude(status=Lesson.Status.CANCELLED)
        .exists()
        for a in attendees
    )
    job = lesson.job
    return {
        "id": str(lesson.pk),
        "title": lesson.title,
        "status": lesson.status,
        "start": _d(lesson.start),
        "end": _d(lesson.end),
        "timezone": lesson.timezone,
        "online": lesson.online,
        "service": {"name": lesson.service.name},
        "job": {
            "reference": job.reference if job else "",
            "name": job.name if job else "",
            "subject": job.subject.name if job is not None and job.subject is not None else "",
        },
        "students": [a.student.full_name for a in attendees],
        "tutors": [t.tutor.full_name for t in lesson.tutors.select_related("tutor")],
        "first_for_student": first,
    }


def report_ctx(report: Any) -> dict[str, Any]:
    return {
        "id": str(report.pk),
        "status": report.status,
        "due_at": _d(report.due_at),
        "submitted_at": _d(report.submitted_at),
        "tutor": report.tutor.full_name,
        "lesson": lesson_ctx(report.lesson),
    }


def enquiry_ctx(enquiry: Any) -> dict[str, Any]:
    return {
        "id": str(enquiry.pk),
        "title": enquiry.title,
        "status": enquiry.status,
        "stage": enquiry.stage.name,
        "source": enquiry.source,
        "priority": enquiry.priority,
        "owner": _user_name(enquiry.owner),
        "expected_start": _d(enquiry.expected_start),
        "stage_entered_at": _d(enquiry.stage_entered_at),
        "created_at": _d(enquiry.created_at),
        "tags": _tags("leads.enquiry", enquiry.pk),
        "client": client_ctx(enquiry.client),
    }


def invoice_ctx(invoice: Any) -> dict[str, Any]:
    from tutortrack.core.time import now

    days = (now().date() - invoice.due_date).days if invoice.due_date else 0
    return {
        "id": str(invoice.pk),
        "number": invoice.number,
        "status": invoice.status,
        "currency": invoice.currency,
        "total": _money(invoice.total),
        "balance_due": _money(invoice.balance_due),
        "issue_date": _d(invoice.issue_date),
        "due_date": _d(invoice.due_date),
        "days_overdue": max(days, 0),
        "client": client_ctx(invoice.client),
    }


def job_ctx(job: Any) -> dict[str, Any]:
    return {
        "id": str(job.pk),
        "reference": job.reference,
        "name": job.name,
        "status": job.status,
        "subject": job.subject.name if job.subject is not None else "",
        "online": job.online,
        "start_date": _d(job.start_date),
        "created_at": _d(job.created_at),
        "tags": _tags("jobs.job", job.pk),
        "client": client_ctx(job.client),
    }


def application_ctx(application: Any) -> dict[str, Any]:
    return {
        "id": str(application.pk),
        "full_name": application.full_name,
        "email": application.email,
        "status": application.status,
        "stage": application.stage.name,
        "created_at": _d(application.created_at),
    }


def compliance_ctx(record: Any) -> dict[str, Any]:
    return {
        "id": str(record.pk),
        "requirement": record.requirement.name,
        "status": record.status,
        "expiry_date": _d(record.expiry_date),
        "tutor": tutor_ctx(record.tutor),
    }


# --- field lists (what the builder offers) ------------------------------------------------------

CLIENT_FIELDS = (
    F("name", "Name"),
    F("status", "Status", "choice", ("prospect", "active", "dormant", "archived")),
    F("type", "Type"), F("auto_pay", "Pays automatically", "bool"),
    F("balance_due", "Balance due", "number"), F("account_manager", "Account manager"),
    F("created_at", "Created", "datetime"), F("tags", "Tags", "list"),
)  # fmt: skip


def _prefixed(prefix: str, fields: tuple[F, ...]) -> tuple[F, ...]:
    return tuple(F(f"{prefix}.{f.path}", f.label, f.type, f.choices) for f in fields)


STUDENT_FIELDS = (
    F("first_name", "First name"), F("full_name", "Name"),
    F("status", "Status", "choice",
      ("lead", "trial", "active", "waiting", "paused", "finished", "archived")),
    F("year_group", "Year group"), F("school", "School"),
    F("date_of_birth", "Date of birth", "date"), F("subjects", "Subjects", "list"),
    F("last_lesson_at", "Last lesson", "datetime"), F("created_at", "Created", "datetime"),
    F("tags", "Tags", "list"),
)  # fmt: skip
TUTOR_FIELDS = (
    F("first_name", "First name"), F("full_name", "Name"), F("email", "Email"),
    F("status", "Status", "choice", ("onboarding", "active", "restricted", "inactive")),
    F("employment_type", "Employment"), F("years_experience", "Years' experience", "number"),
    F("created_at", "Created", "datetime"), F("tags", "Tags", "list"),
)  # fmt: skip
LESSON_FIELDS = (
    F("title", "Title"),
    F("status", "Status", "choice", ("planned", "completed", "cancelled", "missed")),
    F("start", "Start", "datetime"), F("end", "End", "datetime"), F("online", "Online", "bool"),
    F("service.name", "Service"), F("job.reference", "Job reference"),
    F("job.subject", "Subject"), F("students", "Students", "list"),
    F("tutors", "Tutors", "list"), F("first_for_student", "First lesson for a student", "bool"),
)  # fmt: skip


def _subject_fields(key: str, own: tuple[F, ...], *nested: tuple[str, tuple[F, ...]]) -> Any:
    out = _prefixed(key, own)
    for prefix, fields in nested:
        out += _prefixed(f"{key}.{prefix}", fields)
    return out


# --- setters ------------------------------------------------------------------------------------


def _set_student_status(student: Any, value: Any) -> Any:
    from tutortrack.people.services import change_student_status

    return change_student_status(student, str(value))


def _set_client_status(client: Any, value: Any) -> Any:
    from tutortrack.people.services import update_client

    return update_client(client, status=str(value))


def _set_enquiry_priority(enquiry: Any, value: Any) -> Any:
    from tutortrack.leads.services import update_enquiry

    return update_enquiry(enquiry, priority=str(value))


# --- registrations ------------------------------------------------------------------------------


def _client_of(obj: Any) -> Any:
    return getattr(obj, "client", None)


register_subject(
    Subject(
        key="client", label="Client", model="people.Client", target="people.client",
        fields=_prefixed("client", CLIENT_FIELDS), context=client_ctx,
        recipients={"client": _contacts},
        owner=_manager,
        setters={"status": _set_client_status},
        date_fields=("created_at",),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="student", label="Student", model="people.Student", target="people.student",
        fields=_subject_fields("student", STUDENT_FIELDS, ("client", CLIENT_FIELDS)),
        context=student_ctx,
        recipients={"client": lambda s: _contacts(s.client)},
        owner=lambda s: _manager(s.client),
        setters={"status": _set_student_status},
        date_fields=("date_of_birth", "created_at"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="tutor", label="Tutor", model="people.TutorProfile", target="people.tutor",
        fields=_prefixed("tutor", TUTOR_FIELDS), context=tutor_ctx,
        recipients={"tutor": lambda t: _tutors([t])},
        date_fields=("created_at",),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="lesson", label="Lesson", model="scheduling.Lesson", target="scheduling.lesson",
        fields=_prefixed("lesson", LESSON_FIELDS), context=lesson_ctx,
        recipients={
            "client": lambda lesson: [
                r for a in lesson.attendees.select_related("client")
                for r in _contacts(a.client)
            ],
            "tutor": lambda lesson: _tutors(t.tutor for t in lesson.tutors.select_related("tutor")),
        },
        owner=lambda lesson: lesson.job.account_manager if lesson.job else None,
        date_fields=("start", "end"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="lesson_report", label="Lesson report", model="delivery.LessonReport",
        target="delivery.lesson_report",
        fields=(
            F("lesson_report.status", "Status"), F("lesson_report.due_at", "Due", "datetime"),
            F("lesson_report.tutor", "Tutor"), *_prefixed("lesson_report.lesson", LESSON_FIELDS),
        ),
        context=report_ctx,
        recipients={"tutor": lambda r: _tutors([r.tutor])},
        owner=lambda r: r.lesson.job.account_manager if r.lesson.job else None,
        date_fields=("due_at",),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="enquiry", label="Enquiry", model="leads.Enquiry", target="leads.enquiry",
        fields=_subject_fields("enquiry", (
            F("title", "Title"), F("status", "Status", "choice", ("open", "won", "lost")),
            F("stage", "Stage"), F("source", "Source"), F("priority", "Priority"),
            F("owner", "Owner"), F("expected_start", "Expected start", "date"),
            F("stage_entered_at", "In stage since", "datetime"),
            F("created_at", "Received", "datetime"), F("tags", "Tags", "list"),
        ), ("client", CLIENT_FIELDS)),
        context=enquiry_ctx,
        recipients={"client": lambda e: _contacts(e.client), "owner": lambda e: _user(e.owner)},
        owner=lambda e: e.owner,
        setters={"priority": _set_enquiry_priority},
        date_fields=("created_at", "expected_start"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="invoice", label="Invoice", model="billing.Invoice", target="billing.invoice",
        fields=_subject_fields("invoice", (
            F("number", "Number"), F("status", "Status"), F("total", "Total", "number"),
            F("balance_due", "Balance due", "number"), F("due_date", "Due", "date"),
            F("days_overdue", "Days overdue", "number"),
        ), ("client", CLIENT_FIELDS)),
        context=invoice_ctx,
        recipients={"client": lambda i: _contacts(i.client)},
        owner=lambda i: _manager(i.client),
        date_fields=("due_date", "issue_date"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="job", label="Job", model="jobs.Job", target="jobs.job",
        fields=_subject_fields("job", (
            F("reference", "Reference"), F("name", "Name"), F("status", "Status"),
            F("subject", "Subject"), F("online", "Online", "bool"),
            F("start_date", "Start date", "date"), F("tags", "Tags", "list"),
        ), ("client", CLIENT_FIELDS)),
        context=job_ctx,
        recipients={
            "client": lambda j: _contacts(j.client),
            "tutor": lambda j: _tutors(
                link.tutor for link in j.tutors.filter(status="active").select_related("tutor")
            ),
        },
        owner=lambda j: j.account_manager,
        date_fields=("start_date", "expected_end_date"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="tutor_application", label="Tutor application", model="recruitment.TutorApplication",
        target="recruitment.application",
        fields=_prefixed("tutor_application", (
            F("full_name", "Name"), F("email", "Email"), F("status", "Status"),
            F("stage", "Stage"), F("created_at", "Received", "datetime"),
        )),
        context=application_ctx,
        owner=lambda a: a.owner,
        date_fields=("created_at",),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="compliance_record", label="Compliance record", model="recruitment.ComplianceRecord",
        target="",
        fields=_subject_fields("compliance_record", (
            F("requirement", "Check"), F("status", "Status"),
            F("expiry_date", "Expires", "date"),
        ), ("tutor", TUTOR_FIELDS)),
        context=compliance_ctx,
        recipients={"tutor": lambda r: _tutors([r.tutor])},
        date_fields=("expiry_date",),
    )
)  # fmt: skip

for _event, _label, _subject in (
    ("client.created", "Client added", "client"),
    ("client.balance_low", "Prepaid balance low", "client"),
    ("student.created", "Student added", "student"),
    ("student.status_changed", "Student status changed", "student"),
    ("tutor.created", "Tutor added", "tutor"),
    ("tutor.status_changed", "Tutor status changed", "tutor"),
    ("tutor.restricted", "Tutor restricted (compliance)", "tutor"),
    ("lesson.scheduled", "Lesson scheduled", "lesson"),
    ("lesson.rescheduled", "Lesson rescheduled", "lesson"),
    ("lesson.cancelled", "Lesson cancelled", "lesson"),
    ("lesson.completed", "Lesson completed", "lesson"),
    ("lesson.missed", "Lesson missed", "lesson"),
    ("attendance.absence_notified", "Absence notified", "lesson"),
    ("lesson_report.overdue", "Lesson report overdue", "lesson_report"),
    ("lesson_report.submitted", "Lesson report submitted", "lesson_report"),
    ("lesson_report.approved", "Lesson report approved", "lesson_report"),
    ("enquiry.received", "Enquiry received", "enquiry"),
    ("enquiry.stage_changed", "Enquiry moved stage", "enquiry"),
    ("enquiry.sla_breached", "Enquiry waiting too long", "enquiry"),
    ("enquiry.won", "Enquiry won", "enquiry"),
    ("enquiry.lost", "Enquiry lost", "enquiry"),
    ("trial_lesson.booked", "Trial lesson booked", "enquiry"),
    ("trial_lesson.completed", "Trial lesson completed", "enquiry"),
    ("invoice.issued", "Invoice issued", "invoice"),
    ("invoice.overdue", "Invoice overdue", "invoice"),
    ("invoice.paid", "Invoice paid", "invoice"),
    ("payment.failed", "Payment failed", "invoice"),
    ("job.created", "Job created", "job"),
    ("job.status_changed", "Job status changed", "job"),
    ("job.tutor_assigned", "Tutor assigned to a job", "job"),
    ("job.hours_cap_reached", "Job hours cap reached", "job"),
    ("application.submitted", "Tutor application received", "tutor_application"),
    ("application.approved", "Tutor application approved", "tutor_application"),
    ("compliance.expiring", "Check expiring", "compliance_record"),
    ("compliance.expired", "Check expired", "compliance_record"),
):
    register_trigger(_event, _label, _subject)


def _auto_pay(context: dict[str, Any]) -> bool:
    for root in context.values():
        if isinstance(root, dict):
            if root.get("auto_pay"):
                return True
            client = root.get("client")
            if isinstance(client, dict) and client.get("auto_pay"):
                return True
    return False


register_predicate(
    "first_lesson_for_student",
    "Is a student's first lesson",
    lambda ctx: bool((ctx.get("lesson") or {}).get("first_for_student")),
)
register_predicate("client_has_auto_pay", "Client pays automatically", _auto_pay)

from . import actions  # noqa: E402,F401  (registers the actions)
