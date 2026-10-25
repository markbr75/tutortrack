"""Scheduling writes (E08). Lessons are priced with the E06 engine and audited."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.catalogue.models import Service
from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import Student, TutorProfile

from . import conflicts as conflict_engine
from . import events, pricing, recurrence
from .models import (
    AvailabilityException,
    AvailabilityTemplate,
    AvailabilityWindow,
    CalendarEvent,
    CalendarEventParticipant,
    ICalFeedToken,
    Lesson,
    LessonAttendee,
    LessonSeries,
    LessonTutor,
)

MIN_MINUTES, MAX_MINUTES = 5, 12 * 60
FINANCIAL_FIELDS = {"start", "end", "service", "attendees", "tutors"}
SIMPLE_FIELDS = {
    "title",
    "location",
    "room",
    "online",
    "meeting_url",
    "meeting_provider",
    "notes_internal",
    "notes_for_tutor",
    "notes_for_client",
    "colour",
    "custom_fields",
}


class ConflictError(BusinessRuleViolation):
    """Hard conflicts; ``extra["conflicts"]`` lists them for the UI."""


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _increment() -> int:
    from tutortrack.tenancy.settings_service import get_setting

    return int(get_setting("scheduling.minute_increment"))


def _check_times(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise _invalid("start", _("Give times with a timezone."))
    minutes = (end - start).total_seconds() / 60
    if minutes < MIN_MINUTES or minutes > MAX_MINUTES:
        raise _invalid("end", _("Lessons last between 5 minutes and 12 hours."))
    step = _increment()
    for name, value in (("start", start), ("end", end)):
        if value.second or value.microsecond or value.minute % step:
            raise _invalid(name, _("Use times in %(n)s-minute steps.") % {"n": step})


def _people_inputs(
    job: Any, attendees: Iterable[dict[str, Any]] | None, tutors: Iterable[dict[str, Any]] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Explicit people, or the job's current students and active tutors."""
    if attendees is None:
        attendees = (
            [
                {"student": link.student}
                for link in job.students.filter(active_to__isnull=True).select_related("student")
            ]
            if job is not None
            else []
        )
    if tutors is None:
        tutors = (
            [
                {"tutor": link.tutor}
                for link in job.tutors.filter(status="active").select_related("tutor")
            ]
            if job is not None
            else []
        )
    return list(attendees), list(tutors)


def _validate_people(
    service: Service,
    attendees: list[dict[str, Any]],
    tutors: list[dict[str, Any]],
    *,
    allow_empty: bool = False,
) -> None:
    """``allow_empty``: group-class sessions (E20) start without students; the class
    roster fills them."""
    if not attendees and not allow_empty:
        raise _invalid("attendees", _("Add at least one student."))
    students = [a["student"] for a in attendees]
    if len({s.pk for s in students}) != len(students):
        raise _invalid("attendees", _("A student is listed twice."))
    if len(students) > service.max_students:
        raise _invalid(
            "attendees",
            _("%(service)s takes at most %(n)s students.")
            % {"service": service.name, "n": service.max_students},
        )
    for student in students:
        if student.archived_at is not None:
            raise _invalid("attendees", _("%(name)s is archived.") % {"name": student.full_name})
    from tutortrack.people.assignability import check_assignable

    for row in tutors:
        check_assignable(row["tutor"], "tutors")


def _title(service: Service, job: Any, students: list[Student]) -> str:
    if job is not None:
        return job.name[:200]
    names = ", ".join(s.full_name for s in students[:3])
    return f"{service.name} \N{EN DASH} {names}"[:200]


def _set_people(
    lesson: Lesson, attendees: list[dict[str, Any]], tutors: list[dict[str, Any]], currency: str
) -> None:
    lesson.attendees.all().delete()
    lesson.tutors.all().delete()
    bill_to = lesson.job.bill_to_id if lesson.job_id and lesson.job else None
    for row in attendees:
        a = LessonAttendee(
            lesson=lesson,
            student=row["student"],
            client_id=bill_to or row["student"].client_id,
            currency=currency,
        )
        a.charge_rate_override = row.get("charge_rate_override")
        a.save()
    for row in tutors:
        t = LessonTutor(lesson=lesson, tutor=row["tutor"], currency=currency)
        t.pay_rate_override = row.get("pay_rate_override")
        t.save()


def _enforce(
    found: list[conflict_engine.Conflict], override: bool
) -> list[conflict_engine.Conflict]:
    hard = conflict_engine.hard(found)
    if override:
        hard = [c for c in hard if c.kind in conflict_engine.UNOVERRIDABLE]
    if hard:
        raise ConflictError(
            hard[0].message,
            extra={
                "conflicts": [c.as_dict() for c in found],
                "errors": {"start": [hard[0].message]},
            },
        )
    return found


def _check_room(fields: dict[str, Any], current_location: Any = None) -> None:
    """A room belongs to the lesson's location (the location follows the room)."""
    room = fields.get("room")
    if room is None:
        return
    if not room.active:
        raise _invalid("room", _("This room is not in use."))
    location = fields.get("location", current_location)
    if location is not None and location.pk != room.location_id:
        raise _invalid("room", _("Choose a room at the lesson's location."))
    fields["location"] = room.location
    if fields.get("online"):
        raise _invalid("room", _("Online lessons don't use a room."))


def _room_clash(exc: IntegrityError) -> ConflictError:
    """The exclusion constraint caught a clash the check missed (a concurrent booking)."""
    message = _("The room is already booked then.")
    if "lesson_room_no_overlap" not in str(exc):
        raise exc
    return ConflictError(
        message,
        extra={
            "conflicts": [{"kind": "room_double_booked", "severity": "hard", "message": message}],
            "errors": {"room": [message]},
        },
    )


def _check_rates(currency: str, rows: Iterable[dict[str, Any]], key: str) -> None:
    for row in rows:
        value: Money | None = row.get(key)
        if value is not None and (value.currency != currency or value.is_negative()):
            raise _invalid(key, _("Use a non-negative rate in %(c)s.") % {"c": currency})


# --- lessons ------------------------------------------------------------------------------------


@dataclass
class LessonResult:
    lesson: Lesson
    warnings: list[conflict_engine.Conflict] = field(default_factory=list)


@transaction.atomic
def create_lesson(
    *,
    start: datetime,
    end: datetime,
    service: Service | None = None,
    job: Any = None,
    timezone: str | None = None,
    attendees: Iterable[dict[str, Any]] | None = None,
    tutors: Iterable[dict[str, Any]] | None = None,
    branch: Any = None,
    created_via: str = Lesson.CreatedVia.ADMIN,
    override_conflicts: bool = False,
    check_conflicts: bool = True,
    notify: bool = True,
    exclude_hold_ids: Iterable[Any] = (),
    **fields: Any,
) -> LessonResult:
    unknown = set(fields) - SIMPLE_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown lesson fields: {', '.join(sorted(unknown))}")
    if job is not None and job.status in {"completed", "cancelled"}:
        raise _invalid("job", _("The job is closed."))
    service = service or (job.service if job is not None else None)
    if service is None:
        raise _invalid("service", _("Choose a service."))
    _check_times(start, end)
    attendee_rows, tutor_rows = _people_inputs(job, attendees, tutors)
    _validate_people(service, attendee_rows, tutor_rows)
    currency = job.currency if job is not None else service.currency
    _check_rates(currency, attendee_rows, "charge_rate_override")
    _check_rates(currency, tutor_rows, "pay_rate_override")
    if fields.get("location") is None and job is not None and "location" not in fields:
        fields["location"] = job.location
        fields.setdefault("online", job.online)
    _check_room(fields)
    tz = timezone or _default_tz(job, branch)
    found: list[conflict_engine.Conflict] = []
    if check_conflicts:
        found = _enforce(
            conflict_engine.check(
                start=start,
                end=end,
                tz=tz,
                tutors=[r["tutor"] for r in tutor_rows],
                students=[r["student"] for r in attendee_rows],
                location=fields.get("location"),
                online=bool(fields.get("online")),
                job=job,
                room=fields.get("room"),
                exclude_hold_ids=exclude_hold_ids,
            ),
            override_conflicts,
        )
    students = [r["student"] for r in attendee_rows]
    lesson = Lesson(
        job=job,
        service=service,
        branch=branch or (job.branch if job is not None else students[0].branch),
        title=fields.pop("title", "") or _title(service, job, students),
        start=start,
        end=end,
        timezone=tz,
        created_via=created_via,
        colour=fields.pop("colour", "") or service.colour,
        **fields,
    )
    try:
        with transaction.atomic():
            lesson.save()
    except IntegrityError as exc:
        raise _room_clash(exc) from exc
    _set_people(lesson, attendee_rows, tutor_rows, currency)
    pricing.price_lesson(lesson)
    audit.record_create(lesson)
    publish(
        events.LessonScheduled(
            subject_id=lesson.pk,
            start=start.isoformat(),
            end=end.isoformat(),
            job_id=str(job.pk) if job else None,
            tutor_ids=[str(r["tutor"].pk) for r in tutor_rows],
            student_ids=[str(s.pk) for s in students],
            notify=notify,
        ),
        branch_id=lesson.branch_id,
    )
    if job is not None and job.hours_cap is not None:
        from tutortrack.jobs.services import check_hours, notify_hours

        notify_hours(job, check_hours(job, on=start.date()))
    return LessonResult(lesson, found)


def _default_tz(job: Any, branch: Any) -> str:
    if job is not None and job.branch_id:
        return str(job.branch.timezone)
    if branch is not None:
        return str(branch.timezone)
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).timezone)


def _totals(lesson: Lesson) -> dict[str, str]:
    charge = sum((a.charge_amount.amount for a in lesson.attendees.all() if a.charge_amount), 0)
    pay = sum((t.pay_amount.amount for t in lesson.tutors.all() if t.pay_amount), 0)
    return {
        "charge": str(charge),
        "pay": str(pay),
        "start": lesson.start.isoformat(),
        "end": lesson.end.isoformat(),
    }


@transaction.atomic
def update_lesson(
    lesson: Lesson,
    *,
    can_edit_locked: bool = False,
    override_conflicts: bool = False,
    notify: bool = True,
    reason: str = "",
    from_series: bool = False,
    **changes: Any,
) -> LessonResult:
    """Edit one lesson. Changing time, service, students or tutors re-prices it; a lesson
    in a series becomes an exception (kept when the series is edited later)."""
    allowed = SIMPLE_FIELDS | {"start", "end", "timezone", "service", "attendees", "tutors"}
    unknown = set(changes) - allowed
    if unknown:
        raise BusinessRuleViolation(f"Unknown lesson fields: {', '.join(sorted(unknown))}")
    if lesson.status == Lesson.Status.CANCELLED:
        raise BusinessRuleViolation(_("Cancelled lessons can't be changed; schedule a new one."))
    financial = FINANCIAL_FIELDS & set(changes)
    if lesson.is_locked and financial and not can_edit_locked:
        raise BusinessRuleViolation(
            _("This lesson is %(state)s; changing it needs permission to edit locked lessons.")
            % {"state": lesson.get_lock_state_display().lower()}
        )
    before = _totals(lesson)
    old_start = lesson.start
    start = changes.pop("start", lesson.start)
    end = changes.pop("end", lesson.end)
    if start != lesson.start or end != lesson.end:
        _check_times(start, end)
    attendee_rows = changes.pop("attendees", None)
    tutor_rows = changes.pop("tutors", None)
    service = changes.pop("service", lesson.service)
    current_attendees = [
        {"student": a.student, "charge_rate_override": a.charge_rate_override}
        for a in lesson.attendees.select_related("student")
    ]
    current_tutors = [
        {"tutor": t.tutor, "pay_rate_override": t.pay_rate_override}
        for t in lesson.tutors.select_related("tutor")
    ]
    new_attendees = list(attendee_rows) if attendee_rows is not None else current_attendees
    new_tutors = list(tutor_rows) if tutor_rows is not None else current_tutors
    _validate_people(service, new_attendees, new_tutors)
    currency = pricing.lesson_currency(lesson)
    _check_rates(currency, new_attendees, "charge_rate_override")
    _check_rates(currency, new_tutors, "pay_rate_override")
    tz = changes.pop("timezone", lesson.timezone)
    moved = start != lesson.start or end != lesson.end
    people_changed = attendee_rows is not None or tutor_rows is not None
    if "location" in changes and "room" not in changes and lesson.room_id is not None:
        location = changes["location"]
        room = lesson.room
        if location is None or room is None or location.pk != room.location_id:
            changes["room"] = None  # the room was at the old location
    if changes.get("online") and lesson.room_id is not None and "room" not in changes:
        changes["room"] = None
    if changes.get("room") is not None:
        _check_room(changes, lesson.location)
    place_changed = "location" in changes or "room" in changes
    found: list[conflict_engine.Conflict] = []
    if moved or people_changed or place_changed:
        found = _enforce(
            conflict_engine.check(
                start=start,
                end=end,
                tz=tz,
                tutors=[r["tutor"] for r in new_tutors],
                students=[r["student"] for r in new_attendees],
                exclude_lesson_ids=[lesson.pk],
                location=changes.get("location", lesson.location),
                online=changes.get("online", lesson.online),
                job=lesson.job,
                room=changes.get("room", lesson.room),
            ),
            override_conflicts,
        )
    with audit.track(lesson):
        for k, v in changes.items():
            setattr(lesson, k, v)
        lesson.start, lesson.end, lesson.timezone, lesson.service = start, end, tz, service
        if moved and lesson.status == Lesson.Status.PLANNED:
            lesson.rescheduled_from = lesson.rescheduled_from or old_start
            lesson.reschedule_reason = reason[:300]
        if lesson.series_id and not from_series and (moved or people_changed or place_changed):
            lesson.is_exception = True
        try:
            with transaction.atomic():
                lesson.save()
        except IntegrityError as exc:
            raise _room_clash(exc) from exc
    if people_changed:
        _set_people(lesson, new_attendees, new_tutors, currency)
    if (financial or people_changed) and (not lesson.is_locked or can_edit_locked):
        pricing.price_lesson(lesson)
    if lesson.is_locked and financial:
        publish(
            events.LockedLessonEdited(
                subject_id=lesson.pk,
                lock_state=lesson.lock_state,
                before=before,
                after=_totals(lesson),
            )
        )
    if moved:
        publish(
            events.LessonRescheduled(
                subject_id=lesson.pk,
                old_start=old_start.isoformat(),
                new_start=start.isoformat(),
                new_end=end.isoformat(),
                reason=reason,
                notify=notify,
            ),
            branch_id=lesson.branch_id,
        )
    changed = sorted(
        set(changes)
        | ({"attendees"} if attendee_rows is not None else set())
        | ({"tutors"} if tutor_rows is not None else set())
    )
    if changed:
        publish(events.LessonUpdated(subject_id=lesson.pk, fields=changed, notify=notify))
    return LessonResult(lesson, found)


ONE_HUNDRED = Decimal(100)
CANCEL_OUTCOMES = {
    "client": LessonAttendee.Outcome.CANCELLED_CLIENT,
    "student": LessonAttendee.Outcome.CANCELLED_CLIENT,
    "tutor": LessonAttendee.Outcome.CANCELLED_TUTOR,
    "admin": LessonAttendee.Outcome.CANCELLED_ADMIN,
}


@dataclass(frozen=True)
class AttendanceInput:
    """One attendee's outcome; ``charge_percent`` comes from the cancellation policy (E09)."""

    attendee_id: Any
    outcome: str
    charge_percent: Decimal = ONE_HUNDRED
    late_minutes: int | None = None


def attendee_rows(lesson: Lesson) -> list[dict[str, object]]:
    return [
        {
            "id": str(a.pk),
            "student_id": str(a.student_id),
            "client_id": str(a.client_id),
            "outcome": a.outcome,
            "charge_percent": str(a.charge_percent),
            "chargeable": a.chargeable,
        }
        for a in lesson.attendees.order_by("created_at", "id")
    ]


def tutor_rows(lesson: Lesson) -> list[dict[str, object]]:
    return [
        {
            "id": str(t.pk),
            "tutor_id": str(t.tutor_id),
            "pay_percent": str(t.pay_percent),
            "payable": t.payable,
        }
        for t in lesson.tutors.order_by("created_at", "id")
    ]


def _check_percent(value: Decimal) -> Decimal:
    if not ONE_HUNDRED >= value >= 0:
        raise _invalid("charge_percent", _("Percentages run from 0 to 100."))
    return value


def _apply_attendance(
    lesson: Lesson, attendance: Iterable[AttendanceInput], recorded_by: Any
) -> None:
    by_id = {str(a.pk): a for a in lesson.attendees.all()}
    stamp = now()
    for row in attendance:
        attendee = by_id.get(str(row.attendee_id))
        if attendee is None:
            raise _invalid("attendance", _("That student isn't in this lesson."))
        if row.outcome not in LessonAttendee.Outcome.values:
            raise _invalid("attendance", _("Unknown attendance outcome."))
        attendee.outcome = row.outcome
        attendee.late_minutes = (
            row.late_minutes if row.outcome == LessonAttendee.Outcome.LATE else None
        )
        attendee.charge_percent = _check_percent(row.charge_percent)
        attendee.chargeable = row.charge_percent > 0
        attendee.recorded_by = recorded_by
        attendee.recorded_at = stamp
        attendee.save(
            update_fields=[
                "outcome",
                "late_minutes",
                "charge_percent",
                "chargeable",
                "recorded_by",
                "recorded_at",
                "updated_at",
            ]
        )


def _apply_pay(lesson: Lesson, pay_percent: Decimal) -> None:
    pay_percent = _check_percent(pay_percent)
    lesson.tutors.update(pay_percent=pay_percent, payable=pay_percent > 0)


@transaction.atomic
def cancel_lesson(
    lesson: Lesson,
    *,
    reason: str = "",
    chargeable: bool = False,
    notify: bool = True,
    cancelled_by: str = "admin",
    charge_percent: Decimal | None = None,
    pay_percent: Decimal | None = None,
    policy_kind: str = "",
    recorded_by: Any = None,
) -> Lesson:
    """Cancel a lesson. E09's policy engine supplies ``charge_percent``/``pay_percent``
    (otherwise ``chargeable`` means 100%/100% and not chargeable 0%/0%)."""
    if lesson.status != Lesson.Status.PLANNED:
        raise BusinessRuleViolation(_("Only planned lessons can be cancelled."))
    if lesson.is_locked:
        raise BusinessRuleViolation(_("This lesson is already invoiced or paid."))
    if cancelled_by not in CANCEL_OUTCOMES:
        raise _invalid("cancelled_by", _("Say who cancelled."))
    charge = charge_percent if charge_percent is not None else ONE_HUNDRED * chargeable
    pay = pay_percent if pay_percent is not None else ONE_HUNDRED * chargeable
    with audit.track(lesson, action="cancel"):
        lesson.status = Lesson.Status.CANCELLED
        lesson.status_reason = reason[:300]
        lesson.status_changed_at = now()
        lesson.chargeable_cancellation = charge > 0
        lesson.cancelled_by = cancelled_by
        lesson.save(
            update_fields=[
                "status",
                "status_reason",
                "status_changed_at",
                "chargeable_cancellation",
                "cancelled_by",
                "updated_at",
            ]
        )
    outcome = CANCEL_OUTCOMES[cancelled_by]
    _apply_attendance(
        lesson,
        [AttendanceInput(a.pk, outcome, charge) for a in lesson.attendees.all()],
        recorded_by,
    )
    _apply_pay(lesson, pay)
    publish(
        events.LessonCancelled(
            subject_id=lesson.pk,
            reason=reason,
            chargeable=charge > 0,
            notify=notify,
            cancelled_by=cancelled_by,
            policy_kind=policy_kind,
            attendees=attendee_rows(lesson),
            tutors=tutor_rows(lesson),
        ),
        branch_id=lesson.branch_id,
    )
    return lesson


@transaction.atomic
def complete_lesson(
    lesson: Lesson,
    *,
    attendance: Iterable[AttendanceInput] | None = None,
    pay_percent: Decimal = ONE_HUNDRED,
    actual_start: datetime | None = None,
    actual_end: datetime | None = None,
    reprice_actual: bool = False,
    recorded_by: Any = None,
    auto: bool = False,
    earliest: datetime | None = None,
) -> Lesson:
    """Mark delivered with attendance (E09 supplies outcomes and policy percentages; by
    default everyone was present). ``earliest`` is when completion opens (default: start)."""
    if lesson.status not in {Lesson.Status.PLANNED, Lesson.Status.MISSED}:
        raise BusinessRuleViolation(_("Only planned lessons can be completed."))
    if (earliest or lesson.start) > now():
        raise BusinessRuleViolation(_("This lesson hasn't started yet."))
    if lesson.is_locked:
        raise BusinessRuleViolation(_("This lesson is already invoiced or paid."))
    if actual_start and actual_end:
        _check_times(actual_start, actual_end)
    with audit.track(lesson, action="complete"):
        lesson.status = Lesson.Status.COMPLETED
        lesson.status_changed_at = now()
        lesson.actual_start = actual_start
        lesson.actual_end = actual_end
        lesson.auto_completed = auto
        lesson.unconfirmed_at = None
        lesson.save(
            update_fields=[
                "status",
                "status_changed_at",
                "actual_start",
                "actual_end",
                "auto_completed",
                "unconfirmed_at",
                "updated_at",
            ]
        )
    rows = list(attendance) if attendance is not None else []
    given = {str(row.attendee_id) for row in rows}
    rows += [
        AttendanceInput(a.pk, LessonAttendee.Outcome.PRESENT)
        for a in lesson.attendees.all()
        if str(a.pk) not in given
    ]
    _apply_attendance(lesson, rows, recorded_by)
    _apply_pay(lesson, pay_percent)
    if reprice_actual and actual_start and actual_end:
        minutes = int((actual_end - actual_start).total_seconds() // 60)
        if minutes != lesson.duration_minutes:
            pricing.price_lesson(lesson, minutes=minutes)
    publish(
        events.LessonCompleted(
            subject_id=lesson.pk,
            job_id=str(lesson.job_id) if lesson.job_id else None,
            auto=auto,
            attendees=attendee_rows(lesson),
            tutors=tutor_rows(lesson),
        ),
        branch_id=lesson.branch_id,
    )
    return lesson


@transaction.atomic
def record_attendance(
    lesson: Lesson, attendance: Iterable[AttendanceInput], *, recorded_by: Any = None
) -> Lesson:
    """Correct attendance after completion (unlocked lessons; E10 updates charges)."""
    if lesson.status != Lesson.Status.COMPLETED:
        raise BusinessRuleViolation(_("Attendance is recorded when the lesson is completed."))
    if lesson.is_locked:
        raise BusinessRuleViolation(
            _("This lesson is already invoiced or paid; raise a credit note instead.")
        )
    with audit.track(lesson, action="attendance"):
        _apply_attendance(lesson, attendance, recorded_by)
    publish(
        events.AttendanceRecorded(subject_id=lesson.pk, attendees=attendee_rows(lesson)),
        branch_id=lesson.branch_id,
    )
    return lesson


@transaction.atomic
def set_expected_absence(
    lesson: Lesson,
    attendee: LessonAttendee,
    *,
    charge_percent: Decimal,
    note: str = "",
    recorded_by: Any = None,
) -> LessonAttendee:
    """Before a lesson: one student won't come (the register starts with them absent)."""
    if lesson.status != Lesson.Status.PLANNED:
        raise BusinessRuleViolation(_("Only planned lessons can take absence notices."))
    _apply_attendance(
        lesson,
        [AttendanceInput(attendee.pk, LessonAttendee.Outcome.ABSENT_NOTIFIED, charge_percent)],
        recorded_by,
    )
    publish(
        events.AbsenceNotified(
            subject_id=lesson.pk, student_id=str(attendee.student_id), note=note[:300]
        ),
        branch_id=lesson.branch_id,
    )
    attendee.refresh_from_db()
    return attendee


@transaction.atomic
def flag_unconfirmed(lesson: Lesson) -> bool:
    """FR-09-8: a past lesson still planned is flagged (shown in the unconfirmed queue)."""
    updated = Lesson.objects.filter(
        pk=lesson.pk, status=Lesson.Status.PLANNED, unconfirmed_at__isnull=True
    ).update(unconfirmed_at=now())
    return bool(updated)


@transaction.atomic
def mark_missed(lesson: Lesson, *, reason: str = "") -> Lesson:
    if lesson.status != Lesson.Status.PLANNED or lesson.start > now():
        raise BusinessRuleViolation(_("Only past planned lessons can be marked missed."))
    with audit.track(lesson, action="missed"):
        lesson.status = Lesson.Status.MISSED
        lesson.status_reason = reason[:300]
        lesson.status_changed_at = now()
        lesson.save(update_fields=["status", "status_reason", "status_changed_at", "updated_at"])
    publish(events.LessonMissed(subject_id=lesson.pk), branch_id=lesson.branch_id)
    return lesson


@transaction.atomic
def duplicate_lesson(
    lesson: Lesson, *, start: datetime, override_conflicts: bool = False
) -> LessonResult:
    return create_lesson(
        start=start,
        end=start + (lesson.end - lesson.start),
        service=lesson.service,
        job=lesson.job,
        timezone=lesson.timezone,
        branch=lesson.branch,
        attendees=[
            {"student": a.student, "charge_rate_override": a.charge_rate_override}
            for a in lesson.attendees.select_related("student")
        ],
        tutors=[
            {"tutor": t.tutor, "pay_rate_override": t.pay_rate_override}
            for t in lesson.tutors.select_related("tutor")
        ],
        override_conflicts=override_conflicts,
        **{
            k: getattr(lesson, k)
            for k in ("title", "location", "online", "notes_for_tutor", "notes_for_client")
        },
    )


@transaction.atomic
def delete_lesson(lesson: Lesson) -> None:
    """Planned, unlocked lessons that were never delivered can be removed outright."""
    if lesson.status != Lesson.Status.PLANNED or lesson.is_locked:
        raise BusinessRuleViolation(
            _("Only planned, unbilled lessons can be deleted; cancel it instead.")
        )
    audit.record(lesson, "delete")
    lesson.delete()


@transaction.atomic
def set_lock(lessons: Iterable[Lesson], state: str) -> int:
    """Called by billing/payroll (E10/E12) when lessons are invoiced or paid."""
    ids = [lesson.pk for lesson in lessons]
    return Lesson.objects.filter(pk__in=ids).update(lock_state=state)


@transaction.atomic
def sync_group_roster(
    lesson: Lesson,
    *,
    attendees: Iterable[dict[str, Any]] | None = None,
    tutors: Iterable[dict[str, Any]] | None = None,
) -> bool:
    """Make a planned group-class session's people match its class (E20-T02/T03).

    ``attendees``: ``[{"student", "client_id"?, "charge_rate_override"?}]``; ``tutors``:
    ``[{"tutor", "pay_rate_override"?}]`` (``None`` leaves that side alone). People who
    stay are not touched, so absence notices given beforehand survive; people who left are
    removed and newcomers added. Re-prices and publishes ``lesson.updated`` (without
    notifications) when something changed. Delivered, cancelled and locked lessons never
    change. Returns whether anything changed."""
    lesson = Lesson.objects.select_for_update().select_related("service").get(pk=lesson.pk)
    if lesson.status != Lesson.Status.PLANNED or lesson.is_locked:
        return False
    currency = pricing.lesson_currency(lesson)
    changed: set[str] = set()
    if attendees is not None:
        wanted = {str(r["student"].pk): r for r in attendees}
        if len(wanted) > lesson.service.max_students:
            raise _invalid(
                "attendees",
                _("%(service)s takes at most %(n)s students.")
                % {"service": lesson.service.name, "n": lesson.service.max_students},
            )
        _check_rates(currency, wanted.values(), "charge_rate_override")
        current = {str(a.student_id): a for a in lesson.attendees.all()}
        for student_id, row in current.items():
            if student_id not in wanted:
                row.delete()
                changed.add("attendees")
        for student_id, want in wanted.items():
            client_id = want.get("client_id") or want["student"].client_id
            rate = want.get("charge_rate_override")
            have = current.get(student_id)
            if have is None:
                a = LessonAttendee(
                    lesson=lesson, student=want["student"], client_id=client_id, currency=currency
                )
                a.charge_rate_override = rate
                a.save()
                changed.add("attendees")
            elif str(have.client_id) != str(client_id) or have.charge_rate_override != rate:
                have.client_id = client_id
                have.charge_rate_override = rate
                have.save()
                changed.add("attendees")
    if tutors is not None:
        wanted_t = {str(r["tutor"].pk): r for r in tutors}
        _check_rates(currency, wanted_t.values(), "pay_rate_override")
        current_t = {str(t.tutor_id): t for t in lesson.tutors.all()}
        for tutor_id, row_t in current_t.items():
            if tutor_id not in wanted_t:
                row_t.delete()
                changed.add("tutors")
        from tutortrack.people.assignability import check_assignable

        for tutor_id, want_t in wanted_t.items():
            rate = want_t.get("pay_rate_override")
            have_t = current_t.get(tutor_id)
            if have_t is None:
                check_assignable(want_t["tutor"], "tutors")
                t = LessonTutor(lesson=lesson, tutor=want_t["tutor"], currency=currency)
                t.pay_rate_override = rate
                t.save()
                changed.add("tutors")
            elif have_t.pay_rate_override != rate:
                have_t.pay_rate_override = rate
                have_t.save()
                changed.add("tutors")
    if not changed:
        return False
    pricing.price_lesson(lesson)
    publish(events.LessonUpdated(subject_id=lesson.pk, fields=sorted(changed), notify=False))
    return True


@transaction.atomic
def note_first_lessons(lesson: Lesson) -> int:
    """E33: ``client.first_lesson_completed`` for each family on a completed lesson that had
    no completed lesson before it (once per family)."""
    if lesson.status != Lesson.Status.COMPLETED:
        return 0
    published = 0
    for client_id in set(lesson.attendees.values_list("client_id", flat=True)):
        earlier = (
            Lesson.objects.filter(
                attendees__client_id=client_id,
                status=Lesson.Status.COMPLETED,
                start__lt=lesson.start,
            )
            .exclude(pk=lesson.pk)
            .exists()
        )
        if earlier:
            continue
        publish(
            events.ClientFirstLessonCompleted(subject_id=client_id, lesson_id=str(lesson.pk)),
            branch_id=lesson.branch_id,
            dedupe_key=f"first-lesson:{client_id}",
        )
        published += 1
    return published


# --- series -------------------------------------------------------------------------------------


@dataclass
class SeriesResult:
    series: LessonSeries
    created: list[Lesson] = field(default_factory=list)
    skipped: list[tuple[date, list[conflict_engine.Conflict]]] = field(default_factory=list)
    conflicting: list[tuple[Lesson, list[conflict_engine.Conflict]]] = field(default_factory=list)


def _horizon() -> date:
    from tutortrack.tenancy.settings_service import get_setting

    months = int(get_setting("scheduling.series_horizon_months"))
    return now().date() + timedelta(days=31 * months)


def holiday_dates(branch_id: Any, start: date, end: date, tz: str) -> set[date]:
    """Local dates covered by organisation-wide holiday/closure events and by E06 holiday
    calendars marked to skip lessons."""
    from zoneinfo import ZoneInfo

    from tutortrack.catalogue.pricing_rules import holiday_dates as calendar_dates

    zone = ZoneInfo(tz)
    closures = CalendarEvent.objects.filter(
        org_wide=True,
        type=CalendarEvent.Type.HOLIDAY,
        start__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
        end__gt=datetime.combine(start, time.min, tzinfo=zone),
    ).filter(Q(branch__isnull=True) | Q(branch_id=branch_id))
    days: set[date] = calendar_dates(branch_id, start, end, skipping=True)
    for closure in closures:
        day = closure.start.astimezone(zone).date()
        last = (closure.end - timedelta(microseconds=1)).astimezone(zone).date()
        while day <= last:
            days.add(day)
            day += timedelta(days=1)
    return days


SkipDateProvider = Callable[[LessonSeries, date, date], set[date]]
_skip_date_providers: list[SkipDateProvider] = []


def register_skip_dates(provider: SkipDateProvider) -> SkipDateProvider:
    """Other apps add dates a series skips (E20: term breaks skip class sessions)."""
    if provider not in _skip_date_providers:
        _skip_date_providers.append(provider)
    return provider


def extra_skip_dates(series: LessonSeries, start: date, end: date) -> set[date]:
    days: set[date] = set()
    for provider in _skip_date_providers:
        days |= provider(series, start, end)
    return days


def _template_people(series: LessonSeries) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tpl = series.template or {}
    students = {
        str(s.pk): s
        for s in Student.objects.filter(pk__in=[r["student"] for r in tpl.get("attendees", [])])
    }
    tutors = {
        str(t.pk): t
        for t in TutorProfile.objects.filter(pk__in=[r["tutor"] for r in tpl.get("tutors", [])])
    }

    def money(value: Any) -> Money | None:
        return Money(value["amount"], value["currency"]) if value else None

    attendees = [
        {
            "student": students[r["student"]],
            "charge_rate_override": money(r.get("charge_rate_override")),
        }
        for r in tpl.get("attendees", [])
        if r["student"] in students
    ]
    tutor_rows = [
        {"tutor": tutors[r["tutor"]], "pay_rate_override": money(r.get("pay_rate_override"))}
        for r in tpl.get("tutors", [])
        if r["tutor"] in tutors
    ]
    return attendees, tutor_rows


def _template(
    attendees: list[dict[str, Any]], tutors: list[dict[str, Any]], **extra: Any
) -> dict[str, Any]:
    def money(value: Money | None) -> dict[str, str] | None:
        return value.to_dict() if value is not None else None

    return {
        "attendees": [
            {
                "student": str(r["student"].pk),
                "charge_rate_override": money(r.get("charge_rate_override")),
            }
            for r in attendees
        ],
        "tutors": [
            {"tutor": str(r["tutor"].pk), "pay_rate_override": money(r.get("pay_rate_override"))}
            for r in tutors
        ],
        **{k: (str(v.pk) if hasattr(v, "pk") else v) for k, v in extra.items()},
    }


def _busy_map(
    tutor_ids: list[Any], start: datetime, end: datetime
) -> dict[str, list[tuple[datetime, datetime]]]:
    """Each tutor's hard-busy intervals in the window, fetched once for a whole series."""
    busy: dict[str, list[tuple[datetime, datetime]]] = {str(t): [] for t in tutor_ids}
    for row in (
        LessonTutor.objects.filter(
            tutor_id__in=tutor_ids, lesson__start__lt=end, lesson__end__gt=start
        )
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .values("tutor_id", "lesson__start", "lesson__end")
    ):
        busy[str(row["tutor_id"])].append((row["lesson__start"], row["lesson__end"]))
    for row in CalendarEventParticipant.objects.filter(
        tutor_id__in=tutor_ids, event__start__lt=end, event__end__gt=start
    ).values("tutor_id", "event__start", "event__end"):
        busy[str(row["tutor_id"])].append((row["event__start"], row["event__end"]))
    for row in AvailabilityException.objects.filter(
        tutor_id__in=tutor_ids, type="off", status="approved", start__lt=end, end__gt=start
    ).values("tutor_id", "start", "end"):
        busy[str(row["tutor_id"])].append((row["start"], row["end"]))
    return busy


def _materialise(
    series: LessonSeries,
    window_start: date,
    window_end: date,
    *,
    conflict_mode: str = "skip",
    result: SeriesResult | None = None,
) -> SeriesResult:
    """Create the series' lessons with local dates in the window that don't exist yet.
    Pricing is resolved once (every occurrence has the same people and duration)."""
    result = result or SeriesResult(series)
    skip = (
        holiday_dates(series.branch_id, window_start, window_end, series.timezone)
        | extra_skip_dates(series, window_start, window_end)
        if series.skip_holidays
        else set()
    )
    existing = set(series.lessons.values_list("occurrence_date", flat=True))
    occurrences = [
        o
        for o in recurrence.expand(
            rule=series.rrule,
            start_date=series.start_date,
            start_time=series.start_time,
            tz=series.timezone,
            duration_minutes=series.duration_minutes,
            window_start=window_start,
            window_end=window_end,
            until=series.until,
            count=series.count,
            skip_dates=skip,
        )
        if o.date not in existing
    ]
    if not occurrences:
        series.horizon_generated_until = max(
            series.horizon_generated_until or window_end, window_end
        )
        series.save(update_fields=["horizon_generated_until", "updated_at"])
        return result
    attendees, tutors = _template_people(series)
    busy = _busy_map([r["tutor"].pk for r in tutors], occurrences[0].start, occurrences[-1].end)
    tpl = series.template or {}
    room_id = tpl.get("room") or None
    room_busy = (
        list(
            Lesson.objects.filter(
                room_id=room_id, start__lt=occurrences[-1].end, end__gt=occurrences[0].start
            )
            .exclude(status=Lesson.Status.CANCELLED)
            .values_list("start", "end")
        )
        if room_id
        else []
    )
    job = series.job
    currency = job.currency if job is not None else series.service.currency
    created: list[Lesson] = []
    for occ in occurrences:
        hard = [
            conflict_engine.Conflict(
                "tutor_double_booked",
                conflict_engine.HARD,
                _("%(tutor)s is busy then.") % {"tutor": r["tutor"].full_name},
                tutor_id=str(r["tutor"].pk),
            )
            for r in tutors
            if any(
                b_start < occ.end and b_end > occ.start
                for b_start, b_end in busy[str(r["tutor"].pk)]
            )
        ]
        room_taken = any(b_start < occ.end and b_end > occ.start for b_start, b_end in room_busy)
        if room_taken:
            hard.append(
                conflict_engine.Conflict(
                    "room_double_booked", conflict_engine.HARD, _("The room is booked then.")
                )
            )
        if room_taken and conflict_mode == "create":
            result.skipped.append((occ.date, hard))  # a room clash can't be created anyway
            continue
        if hard and conflict_mode == "fail":
            raise ConflictError(
                _("%(date)s: %(message)s")
                % {"date": occ.date.isoformat(), "message": hard[0].message},
                extra={"conflicts": [{**c.as_dict(), "date": occ.date.isoformat()} for c in hard]},
            )
        if hard and conflict_mode == "skip":
            result.skipped.append((occ.date, hard))
            continue
        created.append(
            Lesson(
                organisation_id=series.organisation_id,
                job=job,
                series=series,
                occurrence_date=occ.date,
                service=series.service,
                branch_id=series.branch_id,
                title=tpl.get("title")
                or _title(series.service, job, [a["student"] for a in attendees]),
                start=occ.start,
                end=occ.end,
                timezone=series.timezone,
                location_id=tpl.get("location") or None,
                room_id=room_id,
                online=bool(tpl.get("online")),
                notes_for_tutor=tpl.get("notes_for_tutor", ""),
                colour=series.service.colour,
                created_via=Lesson.CreatedVia.SERIES,
            )
        )
        if hard:
            result.conflicting.append((created[-1], hard))
        for r in tutors:
            busy[str(r["tutor"].pk)].append((occ.start, occ.end))
        if room_id:
            room_busy.append((occ.start, occ.end))
    Lesson.objects.bulk_create(created)
    if created:
        first = created[0]
        _set_people(first, attendees, tutors, currency)
        pricing.price_lesson(first)
        template_attendees = list(first.attendees.all())
        template_tutors = list(first.tutors.all())
        bill_to = job.bill_to_id if job is not None else None
        LessonAttendee.objects.bulk_create(
            [
                _copy_attendee(lesson, a, bill_to)
                for lesson in created[1:]
                for a in template_attendees
            ]
        )
        LessonTutor.objects.bulk_create(
            [_copy_tutor(lesson, t) for lesson in created[1:] for t in template_tutors]
        )
        from tutortrack.catalogue.pricing_rules import has_date_rules

        if len(created) > 1 and has_date_rules():
            # Premiums, discounts, tiers and price lists can differ per date (E06 Phase 2):
            # price each occurrence (the copy above is the fast path without such rules).
            for lesson in created[1:]:
                pricing.price_lesson(lesson)
    result.created.extend(created)
    series.horizon_generated_until = max(series.horizon_generated_until or window_end, window_end)
    series.save(update_fields=["horizon_generated_until", "updated_at"])
    return result


def _copy_attendee(lesson: Lesson, a: LessonAttendee, bill_to: Any) -> LessonAttendee:
    row = LessonAttendee(
        organisation_id=lesson.organisation_id,
        lesson=lesson,
        student_id=a.student_id,
        client_id=bill_to or a.client_id,
        currency=a.currency,
        charge_snapshot=a.charge_snapshot,
    )
    row.charge_rate_override = a.charge_rate_override
    row.charge_amount = a.charge_amount
    row.tax_amount = a.tax_amount
    return row


def _copy_tutor(lesson: Lesson, t: LessonTutor) -> LessonTutor:
    row = LessonTutor(
        organisation_id=lesson.organisation_id,
        lesson=lesson,
        tutor_id=t.tutor_id,
        currency=t.currency,
        pay_snapshot=t.pay_snapshot,
    )
    row.pay_rate_override = t.pay_rate_override
    row.pay_amount = t.pay_amount
    return row


@transaction.atomic
def create_series(
    *,
    rrule: str,
    start_date: date,
    start_time: time,
    duration_minutes: int,
    service: Service | None = None,
    job: Any = None,
    timezone: str | None = None,
    attendees: Iterable[dict[str, Any]] | None = None,
    tutors: Iterable[dict[str, Any]] | None = None,
    until: date | None = None,
    count: int | None = None,
    skip_holidays: bool = True,
    location: Any = None,
    online: bool = False,
    notes_for_tutor: str = "",
    conflict_mode: str = "skip",
    branch: Any = None,
    notify: bool = True,
    room: Any = None,
    title: str = "",
    extra_template: dict[str, Any] | None = None,
    allow_empty_roster: bool = False,
) -> SeriesResult:
    """A recurring lesson (FR-08-2). ``conflict_mode``: ``skip`` occurrences where a tutor
    is busy, ``create`` them anyway (needs override permission), or ``fail``.
    ``allow_empty_roster`` and ``title``: group-class sessions (E20) whose attendees come
    from the class roster."""
    service = service or (job.service if job is not None else None)
    if service is None:
        raise _invalid("service", _("Choose a service."))
    if until and count:
        raise _invalid("until", _("End by a date or after a number of lessons, not both."))
    if until and until < start_date:
        raise _invalid("until", _("The end date is before the start."))
    if not (MIN_MINUTES <= duration_minutes <= MAX_MINUTES) or duration_minutes % _increment():
        raise _invalid("duration_minutes", _("Lessons last between 5 minutes and 12 hours."))
    attendee_rows, tutor_rows = _people_inputs(job, attendees, tutors)
    _validate_people(service, attendee_rows, tutor_rows, allow_empty=allow_empty_roster)
    if not attendee_rows and branch is None and job is None:
        raise _invalid("branch", _("Choose a branch."))
    tz = timezone or _default_tz(job, branch)
    if location is None and job is not None:
        location, online = job.location, online or job.online
    if room is not None:
        place = {"room": room, "location": location, "online": online}
        _check_room(place)
        location = place["location"]
    series = LessonSeries.objects.create(
        job=job,
        service=service,
        branch=branch or (job.branch if job is not None else attendee_rows[0]["student"].branch),
        rrule=recurrence.clean_rrule(rrule),
        start_date=start_date,
        start_time=start_time,
        timezone=tz,
        duration_minutes=duration_minutes,
        until=until,
        count=count,
        skip_holidays=skip_holidays,
        template=_template(
            attendee_rows,
            tutor_rows,
            location=location,
            online=online,
            notes_for_tutor=notes_for_tutor,
            room=room,
            **({"title": title[:200]} if title else {}),
            **(extra_template or {}),
        ),
    )
    audit.record_create(series)
    result = _materialise(
        series, start_date, max(_horizon(), start_date), conflict_mode=conflict_mode
    )
    publish(
        events.SeriesCreated(
            subject_id=series.pk,
            job_id=str(job.pk) if job else None,
            lessons_created=len(result.created),
            notify=notify,
        )
    )
    return result


def extend_series(series: LessonSeries, *, until: date | None = None) -> SeriesResult:
    """Generate lessons up to the rolling horizon (nightly task)."""
    if series.status != LessonSeries.Status.ACTIVE:
        return SeriesResult(series)
    target = until or _horizon()
    start = (series.horizon_generated_until or series.start_date) + timedelta(days=1)
    if start > target:
        return SeriesResult(series)
    with transaction.atomic():
        return _materialise(series, max(start, series.start_date), target)


SERIES_FIELDS = {
    "start_time",
    "duration_minutes",
    "rrule",
    "until",
    "count",
    "skip_holidays",
    "attendees",
    "tutors",
    "location",
    "online",
    "notes_for_tutor",
}
REGENERATE = {"rrule", "until", "count", "skip_holidays"}


@transaction.atomic
def edit_series(
    series: LessonSeries,
    *,
    scope: str,
    from_lesson: Lesson | None = None,
    overwrite_exceptions: bool = False,
    allow_empty_roster: bool = False,
    **changes: Any,
) -> SeriesResult:
    """Change a series: ``following`` (from ``from_lesson``, splitting the series) or ``all``
    future lessons. Completed, cancelled and locked lessons never change; individually
    edited lessons (exceptions) are kept unless ``overwrite_exceptions``."""
    unknown = set(changes) - SERIES_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown series fields: {', '.join(sorted(unknown))}")
    if scope not in {"following", "all"}:
        raise _invalid("scope", _("Choose this and following, or all future lessons."))
    if scope == "following":
        if from_lesson is None or from_lesson.series_id != series.pk:
            raise _invalid("lesson", _("Choose a lesson of this series."))
        series = _split(series, from_lesson)
        cutoff = from_lesson.start
    else:
        cutoff = now()
    if "rrule" in changes:
        changes["rrule"] = recurrence.clean_rrule(changes["rrule"])
    attendee_rows = changes.pop("attendees", None)
    tutor_rows = changes.pop("tutors", None)
    old_attendees, old_tutors = _template_people(series)
    attendees = list(attendee_rows) if attendee_rows is not None else old_attendees
    tutors = list(tutor_rows) if tutor_rows is not None else old_tutors
    _validate_people(series.service, attendees, tutors, allow_empty=allow_empty_roster)
    tpl = dict(series.template or {})
    for key in ("location", "online", "notes_for_tutor"):
        if key in changes:
            value = changes.pop(key)
            tpl[key] = str(value.pk) if hasattr(value, "pk") else value
    with audit.track(series):
        for k, v in changes.items():
            setattr(series, k, v)
        series.template = {**tpl, **_template(attendees, tutors)}
        series.save()
    affected = series.lessons.filter(
        start__gte=cutoff, status=Lesson.Status.PLANNED, lock_state=Lesson.Lock.UNLOCKED
    )
    if not overwrite_exceptions:
        affected = affected.exclude(is_exception=True)
    result = SeriesResult(series)
    if REGENERATE & set(changes) or "start_time" in changes:
        # The dates or times change: rebuild the affected lessons from the new rule.
        affected_ids = list(affected.values_list("pk", flat=True))
        Lesson.objects.filter(pk__in=affected_ids).delete()
        start_day = recurrence.local_date_of(cutoff, series.timezone)
        series.horizon_generated_until = start_day - timedelta(days=1)
        _materialise(series, max(start_day, series.start_date), _horizon(), result=result)
    else:
        location_id = tpl.get("location") or None
        for lesson in affected.select_related("service", "job"):
            lesson.end = lesson.start + timedelta(minutes=series.duration_minutes)
            lesson.location_id = location_id
            lesson.online = bool(tpl.get("online"))
            lesson.notes_for_tutor = tpl.get("notes_for_tutor", "")
            lesson.is_exception = False
            lesson.save()
            _set_people(lesson, attendees, tutors, pricing.lesson_currency(lesson))
            pricing.price_lesson(lesson)
            result.created.append(lesson)
    audit.record(series, "edit", {"scope": [None, scope]})
    publish(
        events.SeriesUpdated(subject_id=series.pk, scope=scope, lessons_changed=len(result.created))
    )
    return result


def _split(series: LessonSeries, from_lesson: Lesson) -> LessonSeries:
    """End ``series`` the day before ``from_lesson`` and continue in a new series."""
    split_date = from_lesson.occurrence_date or recurrence.local_date_of(
        from_lesson.start, series.timezone
    )
    if split_date <= series.start_date:
        return series  # editing from the first lesson is the whole series
    remaining = None
    if series.count:
        before = series.lessons.filter(occurrence_date__lt=split_date).count()
        remaining = max(series.count - before, 1)
    new = LessonSeries.objects.create(
        job=series.job,
        service=series.service,
        branch=series.branch,
        rrule=series.rrule,
        start_date=split_date,
        start_time=series.start_time,
        timezone=series.timezone,
        duration_minutes=series.duration_minutes,
        until=series.until,
        count=remaining,
        horizon_generated_until=series.horizon_generated_until,
        skip_holidays=series.skip_holidays,
        template=series.template,
        split_from=series,
    )
    series.lessons.filter(occurrence_date__gte=split_date).update(series=new)
    with audit.track(series, action="split"):
        series.until = split_date - timedelta(days=1)
        series.count = None
        series.save()
    audit.record_create(new)
    return new


@transaction.atomic
def end_series(series: LessonSeries, *, after: date | None = None, reason: str = "") -> int:
    """Stop a series: cancel its planned lessons after ``after`` (default: today)."""
    last = after or now().date()
    with audit.track(series, action="end"):
        series.until = last
        series.status = LessonSeries.Status.ENDED
        series.save()
    cancelled = 0
    for lesson in series.lessons.filter(
        occurrence_date__gt=last, status=Lesson.Status.PLANNED, lock_state=Lesson.Lock.UNLOCKED
    ):
        cancel_lesson(lesson, reason=reason or _("Series ended"), chargeable=False)
        cancelled += 1
    publish(events.SeriesEnded(subject_id=series.pk))
    return cancelled


WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def schedule_from_job(job: Any) -> list[SeriesResult]:
    """Create weekly series from a job's ``default_schedule`` (once per job)."""
    if not job.default_schedule or LessonSeries.objects.filter(job=job).exists():
        return []
    start = job.start_date or now().date()
    results = []
    for slot in job.default_schedule:
        weekday = int(slot["weekday"])
        hour, minute = (int(x) for x in slot["time"].split(":"))
        results.append(
            create_series(
                job=job,
                rrule=f"FREQ=WEEKLY;BYDAY={WEEKDAYS[weekday]}",
                start_date=start + timedelta(days=(weekday - start.weekday()) % 7),
                start_time=time(hour, minute),
                duration_minutes=int(
                    slot.get("duration_minutes") or job.default_duration_minutes or 60
                ),
                until=job.expected_end_date,
            )
        )
    return results


# --- calendar events ----------------------------------------------------------------------------


@transaction.atomic
def save_event(
    event: CalendarEvent | None, *, tutors: Iterable[TutorProfile] | None = None, **data: Any
) -> tuple[CalendarEvent, int]:
    """Create or update an event. An organisation-wide closure with ``cancel_lessons``
    cancels planned lessons in its range (not chargeable). Returns (event, cancelled)."""
    start, end = (
        data.get("start", event.start if event else None),
        data.get("end", event.end if event else None),
    )
    if start is None or end is None or end <= start:
        raise _invalid("end", _("The end must be after the start."))
    if (
        data.get("org_wide")
        and data.get("type", event.type if event else "") != CalendarEvent.Type.HOLIDAY
        and tutors
    ):
        raise _invalid("tutors", _("Organisation-wide events are for everyone; don't pick tutors."))
    if event is None:
        event = CalendarEvent(**data)
        event.save()
        audit.record_create(event)
    else:
        with audit.track(event):
            for k, v in data.items():
                setattr(event, k, v)
            event.save()
    if tutors is not None:
        event.participants.all().delete()
        for tutor in tutors:
            CalendarEventParticipant.objects.create(event=event, tutor=tutor)
    cancelled = 0
    if event.org_wide and event.cancel_lessons:
        lessons = Lesson.objects.filter(
            start__lt=event.end,
            end__gt=event.start,
            status=Lesson.Status.PLANNED,
            lock_state=Lesson.Lock.UNLOCKED,
        )
        if event.branch_id:
            lessons = lessons.filter(branch_id=event.branch_id)
        for lesson in lessons:
            cancel_lesson(lesson, reason=event.title, chargeable=False)
            cancelled += 1
    return event, cancelled


@transaction.atomic
def delete_event(event: CalendarEvent) -> None:
    audit.record(event, "delete")
    event.delete()


# --- availability -------------------------------------------------------------------------------


@transaction.atomic
def set_availability(
    tutor: TutorProfile, *, windows: Iterable[dict[str, Any]], effective_from: date, timezone: str
) -> AvailabilityTemplate:
    """Replace the tutor's weekly availability from ``effective_from``."""
    rows = list(windows)
    for row in rows:
        if not (0 <= int(row["weekday"]) <= 6) or row["end_time"] <= row["start_time"]:
            raise _invalid("windows", _("Each window needs a day and a start before its end."))
    AvailabilityTemplate.objects.filter(tutor=tutor, effective_from__gte=effective_from).delete()
    AvailabilityTemplate.objects.filter(tutor=tutor, effective_from__lt=effective_from).filter(
        Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from)
    ).update(effective_to=effective_from - timedelta(days=1))
    template = AvailabilityTemplate.objects.create(
        tutor=tutor, effective_from=effective_from, timezone=timezone
    )
    for row in rows:
        AvailabilityWindow.objects.create(
            template=template,
            weekday=int(row["weekday"]),
            start_time=row["start_time"],
            end_time=row["end_time"],
            mode=row.get("mode", AvailabilityWindow.Mode.ANY),
        )
    audit.record(tutor, "set_availability", {"windows": [None, len(rows)]})
    publish(events.AvailabilityUpdated(subject_id=tutor.pk))
    return template


@transaction.atomic
def add_exception(
    tutor: TutorProfile,
    *,
    type: str,
    start: datetime,
    end: datetime,
    reason: str = "",
    needs_approval: bool = False,
    user: Any = None,
) -> tuple[AvailabilityException, list[Lesson]]:
    """Extra availability or time off. Time off returns the lessons that now need cover.

    With ``needs_approval`` (a tutor asking, and ``scheduling.time_off_approval`` on), time
    off waits for an admin (``TimeOffApprovalWorkflow``); otherwise it is approved at once
    and clashing lessons are flagged for cover (E08-T15)."""
    if end <= start:
        raise _invalid("end", _("The end must be after the start."))
    is_off = type == AvailabilityException.Type.OFF
    pending = is_off and needs_approval
    exception = AvailabilityException.objects.create(
        tutor=tutor,
        type=type,
        start=start,
        end=end,
        reason=reason[:300],
        status=(
            AvailabilityException.Status.REQUESTED
            if pending
            else AvailabilityException.Status.APPROVED
        ),
        requested_by=user if getattr(user, "is_authenticated", False) else None,
    )
    audit.record_create(exception)
    publish(events.AvailabilityUpdated(subject_id=tutor.pk))
    clashes = _time_off_clashes(exception) if is_off else []
    if pending:
        publish(
            events.TimeOffRequested(
                subject_id=exception.pk,
                tutor_id=str(tutor.pk),
                start=start.isoformat(),
                end=end.isoformat(),
                clashes=len(clashes),
            )
        )
        _staff_alert(
            "staff_time_off_requested",
            _("%(tutor)s asked for time off") % {"tutor": tutor.full_name},
            f"{start:%d %b %Y} \N{EN DASH} {end:%d %b %Y}",
            "/availability?tab=requests",
            f"time-off-{exception.pk}",
        )
    elif is_off:
        publish(
            events.TimeOffApproved(subject_id=exception.pk, tutor_id=str(tutor.pk), automatic=True)
        )
        flag_cover(exception)
        exception.refresh_from_db()
    return exception, clashes


def _staff_alert(type_key: str, title: str, body: str, link: str, key: str) -> None:
    from tutortrack.comms import services as comms
    from tutortrack.core.context import require_organisation_id, tenant_context

    organisation_id = require_organisation_id()  # captured now, not when the hook runs

    def send() -> None:
        with tenant_context(organisation_id):
            comms.notify(type_key, (title, body, link), key=key)

    transaction.on_commit(send)


def _time_off_clashes(exception: AvailabilityException) -> list[Lesson]:
    return list(
        Lesson.objects.filter(
            tutors__tutor_id=exception.tutor_id,
            start__lt=exception.end,
            end__gt=exception.start,
            status=Lesson.Status.PLANNED,
        ).order_by("start")
    )


@transaction.atomic
def decide_time_off(
    exception: AvailabilityException, *, approve: bool, user: Any = None, note: str = ""
) -> AvailabilityException:
    """An admin approves or declines requested time off. Approval flags clashing lessons
    for cover (done by the workflow's next step, ``flag_cover``)."""
    exception = AvailabilityException.objects.select_for_update().get(pk=exception.pk)
    if exception.status != AvailabilityException.Status.REQUESTED:
        raise BusinessRuleViolation(_("This request has already been decided."))
    with audit.track(exception, action="approve" if approve else "decline"):
        exception.status = (
            AvailabilityException.Status.APPROVED
            if approve
            else AvailabilityException.Status.DECLINED
        )
        exception.decided_by = user if getattr(user, "is_authenticated", False) else None
        exception.decided_at = now()
        exception.decision_note = note[:300]
        exception.save()
    tutor_id = str(exception.tutor_id)
    if approve:
        publish(events.TimeOffApproved(subject_id=exception.pk, tutor_id=tutor_id))
    else:
        publish(events.TimeOffDeclined(subject_id=exception.pk, tutor_id=tutor_id))
    publish(events.AvailabilityUpdated(subject_id=exception.tutor_id))
    return exception


@transaction.atomic
def expire_time_off(exception_id: Any) -> bool:
    """Nobody decided before the time off began: it is declined (activity)."""
    exception = AvailabilityException.objects.select_for_update().filter(pk=exception_id).first()
    if exception is None or exception.status != AvailabilityException.Status.REQUESTED:
        return False
    with audit.track(exception, action="expire"):
        exception.status = AvailabilityException.Status.DECLINED
        exception.decided_at = now()
        exception.decision_note = _("Not decided before it started.")
        exception.save()
    publish(
        events.TimeOffDeclined(
            subject_id=exception.pk, tutor_id=str(exception.tutor_id), expired=True
        )
    )
    return True


def remind_time_off(exception_id: Any) -> bool:
    exception = (
        AvailabilityException.objects.select_related("tutor").filter(pk=exception_id).first()
    )
    if exception is None or exception.status != AvailabilityException.Status.REQUESTED:
        return False
    _staff_alert(
        "staff_time_off_requested",
        _("Reminder: %(tutor)s's time off needs a decision") % {"tutor": exception.tutor.full_name},
        f"{exception.start:%d %b %Y} \N{EN DASH} {exception.end:%d %b %Y}",
        "/availability?tab=requests",
        f"time-off-reminder-{exception.pk}",
    )
    return True


def time_off_state(exception_id: Any) -> dict[str, str]:
    exception = AvailabilityException.objects.filter(pk=exception_id).first()
    if exception is None:
        return {"status": "missing", "start": ""}
    return {"status": exception.status, "start": exception.start.isoformat()}


@transaction.atomic
def flag_cover(exception: AvailabilityException) -> list[Lesson]:
    """Approved time off: mark the tutor's clashing future lessons and ask for cover
    (E19 ``create_cover`` starts ``CoverRequestWorkflow``). Idempotent."""
    from tutortrack.tenancy.settings_service import get_setting

    exception = AvailabilityException.objects.select_for_update().get(pk=exception.pk)
    if exception.status != AvailabilityException.Status.APPROVED or exception.cover_request_id:
        return []
    lessons = [lesson for lesson in _time_off_clashes(exception) if lesson.start > now()]
    if not lessons:
        return []
    Lesson.objects.filter(pk__in=[lesson.pk for lesson in lessons]).update(cover_flagged_at=now())
    request_id: str | None = None
    if get_setting("scheduling.time_off_cover"):
        from tutortrack.matching import services as matching

        try:
            with transaction.atomic():
                request = matching.create_cover(
                    lessons, reason=exception.reason or _("Time off"), tutor=exception.tutor
                )
            request_id = str(request.pk)
            exception.cover_request_id = request.pk
            exception.save(update_fields=["cover_request_id", "updated_at"])
        except BusinessRuleViolation:
            request_id = None  # too late, or cover already being found: staff reassign
    publish(
        events.CoverFlagged(
            subject_id=exception.pk,
            tutor_id=str(exception.tutor_id),
            lesson_ids=[str(lesson.pk) for lesson in lessons],
            cover_request_id=request_id,
        )
    )
    return lessons


@transaction.atomic
def delete_exception(exception: AvailabilityException) -> None:
    audit.record(exception, "delete")
    exception.delete()
    publish(events.AvailabilityUpdated(subject_id=exception.tutor_id))


# --- iCal feeds ---------------------------------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@transaction.atomic
def create_feed(user: Any, *, kind: str, subject_id: Any) -> tuple[ICalFeedToken, str]:
    """A new secret feed URL token (shown once). Revokes the user's previous one for it."""
    ICalFeedToken.objects.filter(
        user=user, kind=kind, subject_id=subject_id, revoked_at__isnull=True
    ).update(revoked_at=now())
    token = secrets.token_urlsafe(32)
    feed = ICalFeedToken.objects.create(
        user=user, kind=kind, subject_id=subject_id, token_hash=hash_token(token)
    )
    audit.record_create(feed)
    return feed, token


@transaction.atomic
def revoke_feed(feed: ICalFeedToken) -> None:
    with audit.track(feed, action="revoke"):
        feed.revoked_at = now()
        feed.save(update_fields=["revoked_at", "updated_at"])


# --- imports (E28) ------------------------------------------------------------------------------


def is_imported_history(lesson: Lesson) -> bool:
    """A past lesson brought over by an import: settled history that never creates charges
    or pay (billing and payroll check this)."""
    return lesson.created_via == Lesson.CreatedVia.IMPORT and lesson.lock_state == Lesson.Lock.PAID


@transaction.atomic
def import_lesson(
    *,
    start: datetime,
    end: datetime,
    service: Service,
    job: Any = None,
    timezone: str | None = None,
    attendees: Iterable[dict[str, Any]] | None = None,
    tutors: Iterable[dict[str, Any]] | None = None,
    status: str = Lesson.Status.PLANNED,
    historic: bool = False,
    **fields: Any,
) -> Lesson:
    """A lesson from an import (E28). Nobody is notified and conflicts aren't enforced (the
    source system already had them). ``historic`` lessons keep their outcome, are locked
    as settled and never create charges or pay: balances come over as opening balances."""
    if status not in Lesson.Status.values:
        raise _invalid("status", _("Unknown status."))
    if not historic and status != Lesson.Status.PLANNED:
        raise _invalid("status", _("Only past lessons can be imported as delivered."))
    result = create_lesson(
        start=start,
        end=end,
        service=service,
        job=job if job is None or job.status not in {"completed", "cancelled"} else None,
        timezone=timezone,
        attendees=attendees,
        tutors=tutors,
        created_via=Lesson.CreatedVia.IMPORT,
        check_conflicts=False,
        notify=False,
        **fields,
    )
    lesson = result.lesson
    if job is not None and lesson.job_id is None:
        lesson.job = job  # a closed job's history
        lesson.save(update_fields=["job", "updated_at"])
    if historic:
        outcomes: dict[str, str] = {
            Lesson.Status.COMPLETED: LessonAttendee.Outcome.PRESENT,
            Lesson.Status.CANCELLED: LessonAttendee.Outcome.CANCELLED_ADMIN,
            Lesson.Status.MISSED: "",
        }
        outcome = outcomes.get(status, "")
        lesson.status = status
        lesson.status_changed_at = end
        lesson.lock_state = Lesson.Lock.PAID
        lesson.save(update_fields=["status", "status_changed_at", "lock_state", "updated_at"])
        if outcome:
            lesson.attendees.update(outcome=outcome, recorded_at=end)
    return lesson


@transaction.atomic
def discard_imported_lesson(lesson: Lesson) -> None:
    """An import is rolled back: its lesson is removed (planned ones like ``delete_lesson``;
    imported history too, which never created charges or pay)."""
    if lesson.created_via != Lesson.CreatedVia.IMPORT and lesson.series_id is None:
        raise BusinessRuleViolation(_("Only imported lessons can be removed this way."))
    if not is_imported_history(lesson) and (
        lesson.status != Lesson.Status.PLANNED or lesson.is_locked
    ):
        raise BusinessRuleViolation(_("The lesson was delivered or billed, so it was kept."))
    audit.record(lesson, "delete", {"reason": [None, "import rolled back"]})
    lesson.delete()


@transaction.atomic
def discard_imported_series(series: LessonSeries) -> bool:
    """An import is rolled back: the series and its untouched future lessons go. Lessons
    already delivered, billed or changed keep the series (it is ended instead)."""
    kept = 0
    for lesson in series.lessons.all():
        if (
            lesson.status == Lesson.Status.PLANNED
            and not lesson.is_locked
            and not lesson.is_exception
        ):
            audit.record(lesson, "delete", {"reason": [None, "import rolled back"]})
            lesson.delete()
        else:
            kept += 1
    if kept:  # some lessons were delivered or changed: end the series instead
        end_series(series, reason=_("Import rolled back"))
        return False
    audit.record(series, "delete", {"reason": [None, "import rolled back"]})
    series.delete()
    return True


def _windows(tutor: TutorProfile) -> tuple[list[dict[str, Any]], str]:
    from .availability import template_for

    template = template_for(tutor.pk, now().date())
    if template is None:
        return [], ""
    return [
        {"weekday": w.weekday, "start_time": w.start_time, "end_time": w.end_time, "mode": w.mode}
        for w in template.windows.all()
    ], template.timezone


@transaction.atomic
def add_availability_window(tutor: TutorProfile, window: dict[str, Any], *, timezone: str) -> bool:
    """Add one weekly window to the tutor's current availability (imports, E28). False when
    the same window is already there."""
    windows, tz = _windows(tutor)
    key = (int(window["weekday"]), window["start_time"], window["end_time"])
    if any((w["weekday"], w["start_time"], w["end_time"]) == key for w in windows):
        return False
    set_availability(
        tutor, windows=[*windows, window], effective_from=now().date(), timezone=tz or timezone
    )
    return True


@transaction.atomic
def remove_availability_window(
    tutor: TutorProfile, weekday: int, start_time: time, end_time: time
) -> bool:
    windows, tz = _windows(tutor)
    remaining = [
        w
        for w in windows
        if (w["weekday"], w["start_time"], w["end_time"]) != (weekday, start_time, end_time)
    ]
    if len(remaining) == len(windows):
        return False
    set_availability(tutor, windows=remaining, effective_from=now().date(), timezone=tz or "UTC")
    return True


# --- re-pricing (FR-06-4 "apply to future lessons?", E06-T07 retroactive tool) -------------------


def repriceable_lessons(
    *,
    start: date | None = None,
    end: date | None = None,
    tutor_id: Any = None,
    service_id: Any = None,
    include_past: bool = False,
) -> Any:
    """Unlocked lessons the current pricing rules may re-price: planned future lessons, or
    with ``include_past`` also delivered ones not yet invoiced or paid."""
    qs = Lesson.objects.filter(lock_state=Lesson.Lock.UNLOCKED).exclude(
        status=Lesson.Status.CANCELLED
    )
    if not include_past:
        qs = qs.filter(status=Lesson.Status.PLANNED, start__gte=now())
    if start is not None:
        qs = qs.filter(start__gte=datetime.combine(start, time.min, tzinfo=UTC) - timedelta(days=1))
    if end is not None:
        qs = qs.filter(start__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC))
    if tutor_id is not None:
        qs = qs.filter(tutors__tutor_id=tutor_id)
    if service_id is not None:
        qs = qs.filter(service_id=service_id)
    return qs.distinct()


@transaction.atomic
def reprice_lessons(*, dry_run: bool = False, **filters: Any) -> int:
    """Re-resolve prices of the matching unlocked lessons; returns how many (changed or
    not). Locked lessons are never touched."""
    from .recurrence import local_date_of

    lessons = list(repriceable_lessons(**filters).select_related("job", "service"))
    start = filters.get("start")
    if start is not None:  # the day boundary is local to each lesson
        lessons = [x for x in lessons if local_date_of(x.start, x.timezone) >= start]
    if dry_run:
        return len(lessons)
    for lesson in lessons:
        before = _totals(lesson)
        pricing.price_lesson(lesson)
        after = _totals(lesson)
        if before != after:
            audit.record(lesson, "reprice", {"charge": [before["charge"], after["charge"]],
                                             "pay": [before["pay"], after["pay"]]})  # fmt: skip
    return len(lessons)


# --- reschedule requests (FR-08-8, E08-T13) -----------------------------------------------------


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


def _month_requests(lesson: Lesson, requester: str) -> int:
    from .models import RescheduleRequest

    current = now()
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = RescheduleRequest.objects.filter(requester=requester, created_at__gte=month_start).exclude(
        status=RescheduleRequest.Status.CANCELLED
    )
    if requester == RescheduleRequest.Party.TUTOR:
        tutors = lesson.tutors.values("tutor_id")
        return qs.filter(lesson__tutors__tutor_id__in=tutors).distinct().count()
    students = lesson.attendees.values("student_id")
    return qs.filter(lesson__attendees__student_id__in=students).distinct().count()


@transaction.atomic
def request_reschedule(
    lesson: Lesson,
    *,
    options: list[tuple[datetime, datetime]],
    requester: str,
    reason: str = "",
    user: Any = None,
) -> Any:
    """Ask to move ``lesson`` to one of ``options`` (FR-08-8). Policies: requests close
    ``scheduling.reschedule_min_notice_hours`` before the lesson and are limited per student
    (or tutor) per month; staff and calendar-sync requests skip the limits."""
    from .models import RescheduleRequest

    party = RescheduleRequest.Party
    lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    limited = requester in {party.CLIENT, party.TUTOR}
    if limited and not _setting("scheduling.reschedule_requests"):
        raise BusinessRuleViolation(_("Reschedule requests are turned off."))
    if lesson.status != Lesson.Status.PLANNED or lesson.start <= now():
        raise BusinessRuleViolation(_("Only upcoming planned lessons can be moved."))
    if lesson.is_locked:
        raise BusinessRuleViolation(_("This lesson has been invoiced or paid; ask the office."))
    notice = timedelta(hours=int(_setting("scheduling.reschedule_min_notice_hours")))
    if limited and lesson.start - now() < notice:
        raise BusinessRuleViolation(
            _("Requests close %(n)s hours before the lesson; please contact us.")
            % {"n": int(notice.total_seconds() // 3600)}
        )
    limit = int(_setting("scheduling.reschedule_max_per_month"))
    if limited and limit and _month_requests(lesson, requester) >= limit:
        raise BusinessRuleViolation(
            _("You've reached the limit of %(n)s reschedule requests this month.") % {"n": limit}
        )
    if RescheduleRequest.objects.filter(lesson=lesson, status="pending").exists():
        raise BusinessRuleViolation(_("There is already a request to move this lesson."))
    if not options or len(options) > 3:
        raise _invalid("options", _("Suggest between one and three new times."))
    clean = []
    for start, end in options:
        _check_times(start, end)
        if start <= now():
            raise _invalid("options", _("Suggest times in the future."))
        if (start, end) == (lesson.start, lesson.end):
            raise _invalid("options", _("That's the lesson's current time."))
        clean.append({"start": start.isoformat(), "end": end.isoformat()})
    window = timedelta(hours=int(_setting("scheduling.reschedule_decision_hours")))
    earliest_option = min(start for start, _end in options)
    deadline = min(now() + window, lesson.start, earliest_option)
    request = RescheduleRequest.objects.create(
        lesson=lesson,
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        requester=requester,
        proposed=clean,
        reason=reason[:300],
        deadline=deadline,
        original_start=lesson.start,
        original_end=lesson.end,
    )
    audit.record_create(request)
    publish(
        events.RescheduleRequested(
            subject_id=request.pk,
            lesson_id=str(lesson.pk),
            requester=requester,
            deadline=deadline.isoformat(),
            options=len(clean),
        ),
        branch_id=lesson.branch_id,
    )
    _staff_alert(
        "staff_reschedule_requested",
        _("Request to move %(lesson)s") % {"lesson": lesson.title},
        reason[:200],
        f"/calendar?lesson={lesson.pk}",
        f"reschedule-{request.pk}",
    )
    return request


def _option(request: Any, index: int) -> tuple[datetime, datetime]:
    try:
        row = request.proposed[index]
    except (IndexError, TypeError) as exc:
        raise _invalid("choice", _("Choose one of the suggested times.")) from exc
    return datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])


@transaction.atomic
def decide_reschedule(
    request: Any,
    *,
    approve: bool,
    choice: int = 0,
    user: Any = None,
    note: str = "",
    override_conflicts: bool = False,
) -> Any:
    """Approve (the lesson moves to the chosen time, with conflict checks) or decline."""
    from .models import RescheduleRequest

    request = (
        RescheduleRequest.objects.select_for_update().select_related("lesson").get(pk=request.pk)
    )
    if request.status != RescheduleRequest.Status.PENDING:
        raise BusinessRuleViolation(_("This request has already been answered."))
    lesson = request.lesson
    if approve:
        start, end = _option(request, choice)
        if start <= now():
            raise _invalid("choice", _("That time has passed."))
        update_lesson(
            lesson,
            start=start,
            end=end,
            reason=_("Rescheduled on request: %(reason)s") % {"reason": request.reason}
            if request.reason
            else _("Rescheduled on request"),
            override_conflicts=override_conflicts,
        )
    with audit.track(request, action="approve" if approve else "decline"):
        request.status = (
            RescheduleRequest.Status.APPROVED if approve else RescheduleRequest.Status.DECLINED
        )
        request.chosen = choice if approve else None
        request.decided_by = user if getattr(user, "is_authenticated", False) else None
        request.decided_at = now()
        request.decision_note = note[:300]
        request.save()
    if approve:
        publish(
            events.RescheduleApproved(
                subject_id=request.pk, lesson_id=str(lesson.pk), new_start=start.isoformat()
            ),
            branch_id=lesson.branch_id,
        )
    else:
        publish(
            events.RescheduleDeclined(subject_id=request.pk, lesson_id=str(lesson.pk)),
            branch_id=lesson.branch_id,
        )
    return request


@transaction.atomic
def cancel_reschedule(request: Any, *, user: Any = None) -> Any:
    from .models import RescheduleRequest

    request = RescheduleRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != RescheduleRequest.Status.PENDING:
        raise BusinessRuleViolation(_("This request has already been answered."))
    with audit.track(request, action="cancel"):
        request.status = RescheduleRequest.Status.CANCELLED
        request.decided_at = now()
        request.save()
    publish(
        events.RescheduleDeclined(
            subject_id=request.pk, lesson_id=str(request.lesson_id), reason="cancelled"
        )
    )
    return request


@transaction.atomic
def expire_reschedule(request_id: Any) -> bool:
    """The deadline passed without an answer: declined automatically (activity)."""
    from .models import RescheduleRequest

    request = RescheduleRequest.objects.select_for_update().filter(pk=request_id).first()
    if request is None or request.status != RescheduleRequest.Status.PENDING:
        return False
    with audit.track(request, action="expire"):
        request.status = RescheduleRequest.Status.EXPIRED
        request.decided_at = now()
        request.save()
    publish(
        events.RescheduleDeclined(
            subject_id=request.pk, lesson_id=str(request.lesson_id), reason="expired"
        )
    )
    return True


def remind_reschedule(request_id: Any) -> bool:
    from .models import RescheduleRequest

    request = RescheduleRequest.objects.select_related("lesson").filter(pk=request_id).first()
    if request is None or request.status != RescheduleRequest.Status.PENDING:
        return False
    _staff_alert(
        "staff_reschedule_requested",
        _("Reminder: answer the request to move %(lesson)s") % {"lesson": request.lesson.title},
        _("It will be declined automatically at %(when)s.")
        % {"when": f"{request.deadline:%d %b %H:%M} UTC"},
        f"/calendar?lesson={request.lesson_id}",
        f"reschedule-reminder-{request.pk}",
    )
    return True


def reschedule_state(request_id: Any) -> dict[str, str]:
    from .models import RescheduleRequest

    request = RescheduleRequest.objects.filter(pk=request_id).first()
    if request is None:
        return {"status": "missing", "deadline": ""}
    return {"status": request.status, "deadline": request.deadline.isoformat()}


# --- online self-booking (FR-08-9, E08-T14) -----------------------------------------------------

BOOKING_SETTINGS_FIELDS = {
    "enabled",
    "allow_new_clients",
    "min_notice_hours",
    "max_advance_days",
    "slot_interval_minutes",
    "buffer_minutes",
    "approval_required",
    "payment",
    "hold_minutes",
    "cancellation_window_hours",
    "tutors",
    "location",
    "terms",
}


class BookingUnavailable(BusinessRuleViolation):
    problem_type = "booking-unavailable"
    title = "That time can't be booked"


def booking_settings() -> Any:
    from .models import BookingSettings

    found, _created = BookingSettings.objects.get_or_create()
    return found


@transaction.atomic
def save_booking_settings(**data: Any) -> Any:
    unknown = set(data) - BOOKING_SETTINGS_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown booking settings: {', '.join(sorted(unknown))}")
    current = booking_settings()
    if "tutors" in data:
        data["tutors"] = sorted({str(t) for t in data["tutors"]})
    if data.get("slot_interval_minutes") is not None and not (
        5 <= int(data["slot_interval_minutes"]) <= 240
    ):
        raise _invalid("slot_interval_minutes", _("Use 5 to 240 minutes."))
    if data.get("hold_minutes") is not None and not (2 <= int(data["hold_minutes"]) <= 60):
        raise _invalid("hold_minutes", _("Hold slots for 2 to 60 minutes."))
    with audit.track(current):
        for k, v in data.items():
            setattr(current, k, v)
        current.save()
    return current


def bookable_services() -> list[Service]:
    return list(Service.objects.filter(active=True, bookable_online=True).order_by("name"))


def bookable_tutors(service: Service) -> list[TutorProfile]:
    """Active tutors offered for ``service``: those listed in the settings (or all), and,
    when the service has a subject, those who teach it."""
    settings_row = booking_settings()
    qs = TutorProfile.objects.filter(status="active", archived_at__isnull=True)
    if settings_row.tutors:
        qs = qs.filter(pk__in=settings_row.tutors)
    if service.subject_id:
        subject = service.subject
        qs = qs.filter(
            Q(subjects__catalogue_subject_id=service.subject_id)
            | Q(subjects__subject__iexact=subject.name if subject else "")
        )
    return list(qs.distinct().order_by("first_name", "last_name"))


@dataclass(frozen=True)
class BookingSlot:
    tutor_id: str
    start: datetime
    end: datetime


def _held(
    tutor_ids: list[Any], start: datetime, end: datetime
) -> dict[str, list[tuple[datetime, datetime]]]:
    from .models import BookingHold

    out: dict[str, list[tuple[datetime, datetime]]] = {}
    for tutor_id, s, e in BookingHold.objects.filter(
        tutor_id__in=tutor_ids, status__in=BookingHold.ACTIVE, start__lt=end, end__gt=start
    ).values_list("tutor_id", "start", "end"):
        out.setdefault(str(tutor_id), []).append((s, e))
    return out


def booking_slots(
    service: Service, *, start: date, end: date, tutor: TutorProfile | None = None
) -> list[BookingSlot]:
    """Bookable start times between ``start`` and ``end`` (local dates) for one tutor or
    any offered tutor, respecting the booking settings (notice, advance window, interval,
    buffer) and slots already held by other bookings."""
    from . import availability

    settings_row = booking_settings()
    if not settings_row.enabled or not service.bookable_online or not service.active:
        return []
    last = min(end, now().date() + timedelta(days=settings_row.max_advance_days))
    if last < start:
        return []
    tutors = [tutor] if tutor is not None else bookable_tutors(service)
    if tutor is not None and tutor.pk not in {t.pk for t in bookable_tutors(service)}:
        return []
    duration = service.default_duration_minutes
    slots: list[BookingSlot] = []
    window_start = datetime.combine(start - timedelta(days=1), time.min, tzinfo=UTC)
    window_end = datetime.combine(last + timedelta(days=2), time.min, tzinfo=UTC)
    held = _held([t.pk for t in tutors], window_start, window_end)
    for candidate in tutors:
        for slot in availability.free_slots(
            candidate.pk,
            start=start,
            end=last,
            duration_minutes=duration,
            step_minutes=settings_row.slot_interval_minutes,
            buffer_minutes=settings_row.buffer_minutes,
            min_notice_hours=settings_row.min_notice_hours,
        ):
            if any(s < slot.end and e > slot.start for s, e in held.get(str(candidate.pk), [])):
                continue
            slots.append(BookingSlot(str(candidate.pk), slot.start, slot.end))
    return sorted(slots, key=lambda s: (s.start, s.tutor_id))


def _student_history(student: Student | None) -> dict[str, tuple[bool, int]]:
    if student is None:
        return {}
    has_any = (
        LessonAttendee.objects.filter(student=student)
        .exclude(lesson__status=Lesson.Status.CANCELLED)
        .exists()
    )
    return {str(student.pk): (not has_any, 1)}


def quote_booking(
    service: Service,
    tutor: TutorProfile,
    start: datetime,
    *,
    tz: str,
    student: Student | None = None,
    promo: Any = None,
    online: bool = False,
    location: Any = None,
) -> dict[str, Any]:
    """The price shown before booking (charge side only)."""
    from tutortrack.catalogue import pricing_rules, rates

    end = start + timedelta(minutes=service.default_duration_minutes)
    student_id = str(student.pk) if student else "new"
    attendee = rates.AttendeeInput(
        student_id=student_id, client_id=str(student.client_id) if student else None
    )
    tutor_input = rates.TutorInput(tutor_id=str(tutor.pk))
    rules = pricing_rules.load_rules(
        service=service,
        currency=service.currency,
        start=start,
        timezone=tz,
        location=location,
        online=online,
        attendees=[attendee],
        tutors=[tutor_input],
        booked_at=now(),
        promo_code=promo,
        history=_student_history(student) if student else {"new": (True, 1)},
    )
    quote = rates.resolve_rates(
        rates.RateContext(
            service=service,
            duration_minutes=int((end - start).total_seconds() // 60),
            attendees=[attendee],
            tutors=[tutor_input],
            rules=rules,
        )
    )
    line = quote.charges[0]
    return {
        "currency": quote.currency,
        "amount": line.amount.to_dict(),
        "undiscounted_amount": line.undiscounted_amount.to_dict(),
        "tax_amount": line.tax_amount.to_dict(),
        "trace": line.trace,
        "discounts": [d.as_dict() for d in line.discounts],
    }


def _booking_tz(tutor: TutorProfile, branch: Any) -> str:
    from .models import AvailabilityTemplate

    template = AvailabilityTemplate.objects.filter(tutor=tutor).order_by("-effective_from").first()
    return template.timezone if template else str(branch.timezone)


@transaction.atomic
def hold_slot(
    *,
    service: Service,
    start: datetime,
    tutor: TutorProfile | None = None,
    student: Student | None = None,
    contact: dict[str, Any] | None = None,
    promo_code: str = "",
    source: str = "portal",
    user: Any = None,
    makeup_credit: Any = None,
) -> tuple[Any, str]:
    """Hold a slot while the person finishes booking (FR-08-9). Returns the hold and, for
    bookings without an account, the secret token for its status link. With a
    ``makeup_credit`` (E15-T09) the lesson is free and uses the credit when booked."""
    from tutortrack.catalogue import services as catalogue
    from tutortrack.tenancy.models import Branch
    from tutortrack.tenancy.selectors import default_branch_id

    from .models import BookingHold

    settings_row = booking_settings()
    if not settings_row.enabled:
        raise BookingUnavailable(_("Online booking is turned off."))
    if student is not None:
        _check_collections(student.client_id)
    if student is None and not (settings_row.allow_new_clients and contact):
        raise _invalid("student", _("Choose who the lesson is for."))
    if student is None:
        for name in ("first_name", "last_name", "email", "student_first_name"):
            if not str((contact or {}).get(name, "")).strip():
                raise _invalid(name, _("This field is required."))
    if start.tzinfo is None:
        raise _invalid("start", _("Give times with a timezone."))
    end = start + timedelta(minutes=service.default_duration_minutes)
    tutors = [tutor] if tutor is not None else bookable_tutors(service)
    # Lock the candidate tutors so two people can't hold the same slot at once.
    locked = list(
        TutorProfile.objects.select_for_update()
        .filter(pk__in=[t.pk for t in tutors])
        .order_by("pk")
    )
    wanted = {str(t.pk) for t in locked}
    free = [
        s
        for s in booking_slots(service, start=start.date() - timedelta(days=1),
                               end=end.date() + timedelta(days=1), tutor=tutor)
        if s.start == start and s.tutor_id in wanted
    ]  # fmt: skip
    if not free:
        raise BookingUnavailable(_("Sorry, that time has just been taken. Please pick another."))
    chosen = next(t for t in locked if str(t.pk) == free[0].tutor_id)
    client = student.client if student else None
    promo = None
    if promo_code:
        promo = catalogue.check_promo(promo_code, client=client, service=service)
    branch = (
        student.branch
        if student is not None and getattr(student, "branch_id", None)
        else Branch.objects.get(pk=default_branch_id(require_org()))
    )
    tz = _booking_tz(chosen, branch)
    online = service.delivery_mode == Service.DeliveryMode.ONLINE
    location = None if online else settings_row.location
    token = secrets.token_urlsafe(24) if student is None else ""
    quote = quote_booking(
        service,
        chosen,
        start,
        tz=tz,
        student=student,
        promo=promo,
        online=online,
        location=location,
    )
    if makeup_credit is not None:
        quote = _makeup_quote(quote, makeup_credit, student)
    hold = BookingHold.objects.create(
        service=service,
        tutor=chosen,
        branch=branch,
        location=location,
        online=online,
        start=start,
        end=end,
        timezone=tz,
        client=client,
        student=student,
        contact={k: str(v)[:200] for k, v in (contact or {}).items()} if student is None else {},
        promo_code=promo,
        trial=student is None or _student_history(student)[str(student.pk)][0],
        quote=quote,
        source=source,
        expires_at=now() + timedelta(minutes=settings_row.hold_minutes),
        token_hash=hash_token(token) if token else "",
        created_by_user=user if getattr(user, "is_authenticated", False) else None,
    )  # fmt: skip
    audit.record_create(hold)
    publish(
        events.BookingHeld(
            subject_id=hold.pk,
            tutor_id=str(chosen.pk),
            start=start.isoformat(),
            expires_at=hold.expires_at.isoformat(),
        )
    )
    return hold, token


def _makeup_quote(quote: dict[str, Any], credit: Any, student: Student | None) -> dict[str, Any]:
    """A makeup lesson booked with a credit costs nothing now (E15-T09)."""
    if student is None or str(credit.student_id) != str(student.pk):
        raise _invalid("makeup_credit", _("That makeup credit belongs to another student."))
    if credit.status_at(now()) != "available":
        raise _invalid("makeup_credit", _("This makeup credit has been used or has expired."))
    zero = Money(Decimal("0.00"), quote["currency"]).to_dict()
    return {**quote, "amount": zero, "tax_amount": zero, "makeup_credit_id": str(credit.pk)}


def _check_collections(client_id: Any) -> None:
    """E10 hook: a client in collections with a hard block can't book online."""
    from tutortrack.billing.selectors import booking_block

    if client_id and booking_block(client_id) == "hard":
        raise BookingUnavailable(
            _("Online booking isn't available for your account at the moment. Please contact us.")
        )


def require_org() -> Any:
    from tutortrack.core.context import require_organisation_id

    return require_organisation_id()


def _booking_client(hold: Any) -> tuple[Any, Student, bool]:
    """The hold's client and student, creating them for a new family."""
    if hold.student_id:
        return hold.student.client, hold.student, False
    from tutortrack.people import services as people

    c = hold.contact or {}
    client, _contact, students = people.quick_add_family(
        contact={
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "email": c.get("email", ""),
            "phone": c.get("phone", ""),
        },
        students=[{"first_name": c.get("student_first_name", "")}],
    )
    hold.client, hold.student = client, students[0]
    hold.save(update_fields=["client", "student", "updated_at"])
    return client, students[0], True


def _hold_for_update(hold_id: Any) -> Any:
    from .models import BookingHold

    return BookingHold.objects.select_for_update().filter(pk=hold_id).first()


@transaction.atomic
def submit_hold(hold: Any, *, user: Any = None) -> tuple[Any, str]:
    """The person pressed Book. Returns the hold and a pay link when payment is due now."""
    from tutortrack.payments import services as payments

    from .models import BookingHold, BookingSettings

    hold = _hold_for_update(hold.pk)
    if hold.status != BookingHold.Status.HELD:
        raise BookingUnavailable(_("This booking can't be changed now."))
    if hold.expires_at <= now():
        raise BookingUnavailable(_("The time we held for you has run out. Please pick again."))
    _check_collections(hold.client_id)
    settings_row = booking_settings()
    amount = Money(hold.quote.get("amount", {}).get("amount", "0"), hold.quote.get("currency"))
    pay_link = ""
    if settings_row.payment == BookingSettings.Payment.AT_BOOKING and amount.is_positive():
        client, _student, _new = _booking_client(hold)
        # E11 hook: a payment request and the pay page; ``payment_request.paid`` signals
        # BookingHoldWorkflow when it is paid.
        payment = payments.request_booking_payment(
            client=client,
            amount=amount,
            description=_("Booking: %(service)s on %(when)s")
            % {"service": hold.service.name, "when": f"{hold.start:%d %b %Y %H:%M} UTC"},
            user=user if getattr(user, "is_authenticated", False) else None,
        )
        hold.payment_request_id = payment["payment_request_id"]
        hold.status = BookingHold.Status.AWAITING_PAYMENT
        hold.expires_at = now() + timedelta(minutes=settings_row.hold_minutes)
        pay_link = str(payment["pay_url"])
    elif settings_row.approval_required:
        hold.status = BookingHold.Status.AWAITING_APPROVAL
    with audit.track(hold, action="submit"):
        hold.save()
    if hold.status == BookingHold.Status.HELD:
        _book(hold)
    elif hold.status == BookingHold.Status.AWAITING_APPROVAL:
        _request_approval(hold)
    publish(events.BookingSubmitted(subject_id=hold.pk, status=hold.status))
    return hold, pay_link


def _request_approval(hold: Any) -> None:
    publish(
        events.BookingRequested(
            subject_id=hold.pk, tutor_id=str(hold.tutor_id), start=hold.start.isoformat()
        )
    )
    _staff_alert(
        "staff_booking_requested",
        _("New online booking for %(service)s") % {"service": hold.service.name},
        f"{hold.start:%d %b %Y %H:%M} UTC",
        "/calendar?tab=bookings",
        f"booking-{hold.pk}",
    )


def _book(hold: Any) -> Lesson:
    """Create the lesson for a hold and confirm it."""
    from .models import BookingHold

    client, student, new_client = _booking_client(hold)
    result = create_lesson(
        start=hold.start,
        end=hold.end,
        service=hold.service,
        timezone=hold.timezone,
        branch=hold.branch,
        attendees=[{"student": student}],
        tutors=[{"tutor": hold.tutor}],
        created_via=Lesson.CreatedVia.CLIENT_BOOKING,
        location=hold.location,
        online=hold.online,
        exclude_hold_ids=[hold.pk],
    )
    lesson = result.lesson
    credit_id = (hold.quote or {}).get("makeup_credit_id")
    if credit_id:
        from tutortrack.delivery import services as delivery
        from tutortrack.delivery.models import MakeupCredit

        credit = MakeupCredit.objects.filter(pk=credit_id).first()
        if credit is None:
            raise BusinessRuleViolation(_("This makeup credit has been used or has expired."))
        delivery.consume_makeup_credit(credit, lesson)
    if hold.promo_code_id:
        from tutortrack.catalogue import services as catalogue

        lesson.attendees.update(promo_code=hold.promo_code_id)
        pricing.price_lesson(lesson)
        catalogue.redeem_promo(hold.promo_code, client=client, reference=f"booking:{hold.pk}")
    with audit.track(hold, action="confirm"):
        hold.lesson = lesson
        hold.status = BookingHold.Status.CONFIRMED
        hold.save()
    publish(
        events.BookingConfirmed(
            subject_id=hold.pk,
            lesson_id=str(lesson.pk),
            client_id=str(client.pk),
            new_client=new_client,
        )
    )
    return lesson


@transaction.atomic
def payment_received(hold_id: Any) -> str:
    """The booking was paid (activity after ``payment_request.paid``): confirm it, or wait
    for approval when bookings need it."""
    from .models import BookingHold

    hold = _hold_for_update(hold_id)
    if hold is None or hold.status != BookingHold.Status.AWAITING_PAYMENT:
        return hold.status if hold else "missing"
    if booking_settings().approval_required:
        with audit.track(hold, action="paid"):
            hold.status = BookingHold.Status.AWAITING_APPROVAL
            hold.save()
        _request_approval(hold)
        return hold.status
    try:
        with transaction.atomic():
            _book(hold)
    except ConflictError:
        hold.decision_note = _("The time was taken before the payment arrived.")
        _close_hold(hold, BookingHold.Status.DECLINED, "conflict")
    return hold.status


@transaction.atomic
def decide_booking(hold: Any, *, approve: bool, user: Any = None, note: str = "") -> Any:
    from .models import BookingHold

    hold = _hold_for_update(hold.pk)
    if hold.status != BookingHold.Status.AWAITING_APPROVAL:
        raise BusinessRuleViolation(_("This booking isn't waiting for approval."))
    hold.decision_note = note[:300]
    if approve:
        _book(hold)
    else:
        _close_hold(hold, BookingHold.Status.DECLINED, "declined")
    return hold


def _close_hold(hold: Any, status: str, reason: str) -> None:
    """Release a hold. An unpaid payment request is cancelled; money already paid stays
    on the client's account as credit (refunds are a payments decision)."""
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import PaymentRequest

    if hold.payment_request_id:
        request = PaymentRequest.objects.filter(pk=hold.payment_request_id).first()
        if request is not None and request.status == PaymentRequest.Status.OPEN:
            try:
                with transaction.atomic():
                    billing.cancel_payment_request(request)
            except BusinessRuleViolation:
                pass  # part-paid: keep it for the office
    with audit.track(hold, action=reason):
        hold.status = status
        hold.save()
    publish(events.BookingDeclined(subject_id=hold.pk, reason=reason))


@transaction.atomic
def release_hold(hold_id: Any) -> bool:
    """The hold ran out before the booking was finished or paid (activity)."""
    from tutortrack.billing.models import PaymentRequest

    from .models import BookingHold

    hold = _hold_for_update(hold_id)
    if hold is None or hold.status not in (
        BookingHold.Status.HELD,
        BookingHold.Status.AWAITING_PAYMENT,
    ):
        return False
    if (
        hold.payment_request_id
        and PaymentRequest.objects.filter(
            pk=hold.payment_request_id, status=PaymentRequest.Status.PAID
        ).exists()
    ):
        payment_received(hold.pk)  # paid, but the signal was missed
        return False
    _close_hold(hold, BookingHold.Status.EXPIRED, "expired")
    return True


@transaction.atomic
def decline_unanswered_booking(hold_id: Any) -> bool:
    """Nobody approved the booking before its deadline (activity)."""
    from .models import BookingHold

    hold = _hold_for_update(hold_id)
    if hold is None or hold.status != BookingHold.Status.AWAITING_APPROVAL:
        return False
    hold.decision_note = _("Not approved in time.")
    _close_hold(hold, BookingHold.Status.DECLINED, "expired")
    return True


@transaction.atomic
def cancel_hold(hold: Any, *, user: Any = None) -> Any:
    from .models import BookingHold

    hold = _hold_for_update(hold.pk)
    if hold.status not in BookingHold.ACTIVE:
        raise BusinessRuleViolation(_("This booking can't be cancelled here."))
    _close_hold(hold, BookingHold.Status.CANCELLED, "cancelled")
    return hold


def hold_state(hold_id: Any) -> dict[str, str]:
    from .models import BookingHold

    hold = BookingHold.objects.filter(pk=hold_id).first()
    if hold is None:
        return {"status": "missing", "expires_at": "", "start": ""}
    return {
        "status": hold.status,
        "expires_at": hold.expires_at.isoformat(),
        "start": hold.start.isoformat(),
        "created_at": hold.created_at.isoformat(),
    }
