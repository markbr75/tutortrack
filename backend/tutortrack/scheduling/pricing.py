"""Price a lesson with the E06 rate engine and snapshot the result (FR-06-4, E08-T01).

Snapshots are taken when a lesson is created and refreshed on edit while it is unlocked.
Locked (invoiced or paid) lessons keep their snapshot; E10/E12 adjust from the event.
"""

from __future__ import annotations

from typing import Any

from tutortrack.catalogue import rates

from .models import Lesson, LessonAttendee, LessonTutor


def build_context(
    lesson: Lesson,
    attendees: list[LessonAttendee],
    tutors: list[LessonTutor],
    minutes: int | None = None,
) -> rates.RateContext:
    job = lesson.job
    job_students: dict[Any, Any] = {}
    job_tutors: dict[Any, Any] = {}
    if job is not None:
        job_students = {link.student_id: link for link in job.students.all()}
        job_tutors = {link.tutor_id: link for link in job.tutors.filter(status="active")}
    return rates.RateContext(
        service=lesson.service,
        duration_minutes=minutes or lesson.duration_minutes,
        currency=job.currency if job else lesson.service.currency,
        job_charge_rate=job.charge_rate if job else None,
        attendees=[
            rates.AttendeeInput(
                student_id=str(a.student_id),
                client_id=str(a.client_id),
                rate_override=a.charge_rate_override,
                job_rate_override=(
                    job_students[a.student_id].charge_rate_override
                    if a.student_id in job_students
                    else None
                ),
            )
            for a in attendees
        ],
        tutors=[
            rates.TutorInput(
                tutor_id=str(t.tutor_id),
                rate_override=t.pay_rate_override,
                job_rate_override=(
                    job_tutors[t.tutor_id].pay_rate_override if t.tutor_id in job_tutors else None
                ),
            )
            for t in tutors
        ],
    )


def lesson_currency(lesson: Lesson) -> str:
    return lesson.job.currency if lesson.job_id and lesson.job else lesson.service.currency


def price_lesson(lesson: Lesson, *, minutes: int | None = None) -> rates.RateQuote:
    """Resolve and store charge and pay amounts on the lesson's attendees and tutors.
    ``minutes`` prices the actual duration instead of the scheduled one (E09)."""
    attendees = list(lesson.attendees.all())
    tutors = list(lesson.tutors.all())
    quote = rates.resolve_rates(build_context(lesson, attendees, tutors, minutes))
    snapshot = quote.as_dict()
    by_student = {line["student_id"]: line for line in snapshot["charges"]}
    by_tutor = {line["tutor_id"]: line for line in snapshot["pay"]}
    charge_lines = {line.student_id: line for line in quote.charges}
    pay_lines = {line.tutor_id: line for line in quote.pay}
    for a in attendees:
        line = charge_lines[str(a.student_id)]
        a.currency = quote.currency
        a.charge_amount = line.amount
        a.tax_amount = line.tax_amount
        a.charge_snapshot = by_student[str(a.student_id)]
        a.save(
            update_fields=[
                "currency",
                "charge_amount_amount",
                "tax_amount_amount",
                "charge_snapshot",
                "updated_at",
            ]
        )
    for t in tutors:
        pay = pay_lines[str(t.tutor_id)]
        t.currency = quote.currency
        t.pay_amount = pay.amount
        t.pay_snapshot = by_tutor[str(t.tutor_id)]
        t.save(update_fields=["currency", "pay_amount_amount", "pay_snapshot", "updated_at"])
    return quote
