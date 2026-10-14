"""Price a lesson with the E06 rate engine and snapshot the result (FR-06-4, E08-T01).

Snapshots are taken when a lesson is created and refreshed on edit while it is unlocked.
Locked (invoiced or paid) lessons keep their snapshot; E10/E12 adjust from the event.
Phase 2 (E06-T07..T09): the lesson's date, place and each student's history feed the
pricing rules (tiers, price lists, premiums, discounts) through
``catalogue.pricing_rules.load_rules``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from tutortrack.catalogue import pricing_rules, rates

from .models import Lesson, LessonAttendee, LessonTutor

HOUR = Decimal(60)


def student_history(lesson: Lesson, attendees: list[LessonAttendee]) -> dict[str, tuple[bool, int]]:
    """``{student: (first lesson?, the client's lessons this month incl. this one)}``."""
    if not attendees:
        return {}
    zone = ZoneInfo(lesson.timezone)
    local = lesson.start.astimezone(zone)
    month_start = datetime.combine(local.date().replace(day=1), time.min, tzinfo=zone)
    month_end = datetime.combine(
        (month_start + timedelta(days=32)).date().replace(day=1), time.min, tzinfo=zone
    )
    live = LessonAttendee.objects.exclude(lesson__status=Lesson.Status.CANCELLED)
    out: dict[str, tuple[bool, int]] = {}
    for a in attendees:
        earlier = (
            live.filter(student_id=a.student_id, lesson__start__lt=lesson.start)
            .exclude(lesson_id=lesson.pk)
            .exists()
        )
        in_month = (
            live.filter(
                client_id=a.client_id, lesson__start__gte=month_start, lesson__start__lt=month_end
            )
            .values("lesson_id")
            .distinct()
            .count()
        )
        if lesson.pk is None or not live.filter(lesson_id=lesson.pk).exists():
            in_month += 1
        out[str(a.student_id)] = (not earlier, in_month)
    return out


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
    currency = job.currency if job else lesson.service.currency
    attendee_inputs = [
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
    ]
    tutor_inputs = [
        rates.TutorInput(
            tutor_id=str(t.tutor_id),
            rate_override=t.pay_rate_override,
            job_rate_override=(
                job_tutors[t.tutor_id].pay_rate_override if t.tutor_id in job_tutors else None
            ),
        )
        for t in tutors
    ]
    promo = next((a.promo_code for a in attendees if a.promo_code_id), None)
    rules = pricing_rules.load_rules(
        service=lesson.service,
        currency=currency,
        start=lesson.start,
        timezone=lesson.timezone,
        branch_id=lesson.branch_id,
        location=lesson.location,
        online=lesson.online,
        attendees=attendee_inputs,
        tutors=tutor_inputs,
        booked_at=lesson.created_at,
        promo_code=promo,
        history=student_history(lesson, attendees),
    )
    return rates.RateContext(
        service=lesson.service,
        duration_minutes=minutes or lesson.duration_minutes,
        currency=currency,
        job_charge_rate=job.charge_rate if job else None,
        attendees=attendee_inputs,
        tutors=tutor_inputs,
        rules=rules,
    )


def _price_tutors_only(
    lesson: Lesson, tutors: list[LessonTutor], minutes: int | None
) -> rates.RateQuote:
    """A group-class session nobody has joined yet (E20): the engine needs students, so
    only explicit pay overrides are priced (the class sets them); others wait for a roster."""
    from tutortrack.catalogue.models import Service

    currency = lesson_currency(lesson)
    duration = Decimal(minutes or lesson.duration_minutes)
    per_hour = lesson.service.pay_unit == Service.PayUnit.PER_HOUR
    for t in tutors:
        rate = t.pay_rate_override
        t.currency = currency
        t.pay_amount = (
            (rate * (duration / HOUR) if per_hour else rate).round_to_minor()
            if rate is not None
            else None
        )
        t.pay_snapshot = (
            {"tutor_id": str(t.tutor_id), "rate": rate.to_dict(), "source": "class_override"}
            if rate is not None
            else {}
        )
        t.save(update_fields=["currency", "pay_amount_amount", "pay_snapshot", "updated_at"])
    return rates.RateQuote(currency=currency, duration_minutes=int(duration), charges=[], pay=[])


def lesson_currency(lesson: Lesson) -> str:
    return lesson.job.currency if lesson.job_id and lesson.job else lesson.service.currency


def price_lesson(lesson: Lesson, *, minutes: int | None = None) -> rates.RateQuote:
    """Resolve and store charge and pay amounts on the lesson's attendees and tutors.
    ``minutes`` prices the actual duration instead of the scheduled one (E09)."""
    attendees = list(lesson.attendees.select_related("promo_code__discount"))
    tutors = list(lesson.tutors.all())
    if not attendees:
        return _price_tutors_only(lesson, tutors, minutes)
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
