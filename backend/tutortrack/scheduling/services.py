"""Scheduling writes (E08). Lessons are priced with the E06 engine and audited."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import transaction
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
    service: Service, attendees: list[dict[str, Any]], tutors: list[dict[str, Any]]
) -> None:
    if not attendees:
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
    for row in tutors:
        tutor = row["tutor"]
        if tutor.status not in {TutorProfile.Status.ACTIVE, TutorProfile.Status.ONBOARDING}:
            raise _invalid("tutors", _("%(name)s isn't available.") % {"name": tutor.full_name})


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
    if hard and not override:
        raise ConflictError(
            hard[0].message,
            extra={
                "conflicts": [c.as_dict() for c in found],
                "errors": {"start": [hard[0].message]},
            },
        )
    return found


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
    lesson.save()
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
    found: list[conflict_engine.Conflict] = []
    if moved or people_changed or "location" in changes:
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
        if (
            lesson.series_id
            and not from_series
            and (moved or people_changed or "location" in changes)
        ):
            lesson.is_exception = True
        lesson.save()
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


@transaction.atomic
def cancel_lesson(
    lesson: Lesson, *, reason: str = "", chargeable: bool = False, notify: bool = True
) -> Lesson:
    """Cancel (E09 decides chargeability from policy; here the caller says)."""
    if lesson.status != Lesson.Status.PLANNED:
        raise BusinessRuleViolation(_("Only planned lessons can be cancelled."))
    if lesson.is_locked:
        raise BusinessRuleViolation(_("This lesson is already invoiced or paid."))
    with audit.track(lesson, action="cancel"):
        lesson.status = Lesson.Status.CANCELLED
        lesson.status_reason = reason[:300]
        lesson.status_changed_at = now()
        lesson.chargeable_cancellation = chargeable
        lesson.save(
            update_fields=[
                "status",
                "status_reason",
                "status_changed_at",
                "chargeable_cancellation",
                "updated_at",
            ]
        )
    if not chargeable:
        lesson.attendees.update(chargeable=False)
        lesson.tutors.update(payable=False)
    publish(
        events.LessonCancelled(
            subject_id=lesson.pk, reason=reason, chargeable=chargeable, notify=notify
        ),
        branch_id=lesson.branch_id,
    )
    return lesson


@transaction.atomic
def complete_lesson(lesson: Lesson) -> Lesson:
    """Mark delivered (E09 adds attendance and the report)."""
    if lesson.status not in {Lesson.Status.PLANNED, Lesson.Status.MISSED}:
        raise BusinessRuleViolation(_("Only planned lessons can be completed."))
    if lesson.start > now():
        raise BusinessRuleViolation(_("This lesson hasn't started yet."))
    with audit.track(lesson, action="complete"):
        lesson.status = Lesson.Status.COMPLETED
        lesson.status_changed_at = now()
        lesson.save(update_fields=["status", "status_changed_at", "updated_at"])
    publish(
        events.LessonCompleted(
            subject_id=lesson.pk, job_id=str(lesson.job_id) if lesson.job_id else None
        ),
        branch_id=lesson.branch_id,
    )
    return lesson


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
    """Local dates covered by organisation-wide holiday/closure events."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    closures = CalendarEvent.objects.filter(
        org_wide=True,
        type=CalendarEvent.Type.HOLIDAY,
        start__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
        end__gt=datetime.combine(start, time.min, tzinfo=zone),
    ).filter(Q(branch__isnull=True) | Q(branch_id=branch_id))
    days: set[date] = set()
    for closure in closures:
        day = closure.start.astimezone(zone).date()
        last = (closure.end - timedelta(microseconds=1)).astimezone(zone).date()
        while day <= last:
            days.add(day)
            day += timedelta(days=1)
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
) -> SeriesResult:
    """A recurring lesson (FR-08-2). ``conflict_mode``: ``skip`` occurrences where a tutor
    is busy, ``create`` them anyway (needs override permission), or ``fail``."""
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
    _validate_people(service, attendee_rows, tutor_rows)
    tz = timezone or _default_tz(job, branch)
    if location is None and job is not None:
        location, online = job.location, online or job.online
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
    _validate_people(series.service, attendees, tutors)
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
    tutor: TutorProfile, *, type: str, start: datetime, end: datetime, reason: str = ""
) -> tuple[AvailabilityException, list[Lesson]]:
    """Extra availability or time off. Time off returns the lessons that now need cover."""
    if end <= start:
        raise _invalid("end", _("The end must be after the start."))
    exception = AvailabilityException.objects.create(
        tutor=tutor, type=type, start=start, end=end, reason=reason[:300]
    )
    audit.record_create(exception)
    publish(events.AvailabilityUpdated(subject_id=tutor.pk))
    clashes: list[Lesson] = []
    if type == AvailabilityException.Type.OFF:
        clashes = list(
            Lesson.objects.filter(
                tutors__tutor=tutor, start__lt=end, end__gt=start, status=Lesson.Status.PLANNED
            )
        )
    return exception, clashes


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
