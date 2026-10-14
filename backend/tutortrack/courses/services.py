"""Course, class, enrolment, register and rollover writes (E20).

Sessions are E08 lessons (``scheduling.services`` creates and changes them); fees are E10
charges and plans (``billing.services.charge_fee``/``adjust_fee``, ``billing.plans``);
payment at enrolment is E11's ``payments.services.request_booking_payment``; waitlists are
E17 entries (``leads.services``) tagged with the class. Every write is audited and
publishes its events inside the transaction.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.catalogue.models import DiscountRule, Service
from tutortrack.core import audit, entitlements
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import Client, Student
from tutortrack.tenancy.settings_service import get_setting

from . import events, pricing, selectors
from .models import (
    AcademicYear,
    ClassSession,
    ClassTeacher,
    Course,
    Enrolment,
    EnrolmentTransfer,
    GroupClass,
    MakeupBooking,
    RolloverOffer,
    Term,
    TermBreak,
    TermRollover,
)

FEE_MODELS = (
    Course.PricingModel.PER_TERM,
    Course.PricingModel.FULL_COURSE,
    Course.PricingModel.INSTALMENTS,
)


class ClassFull(BusinessRuleViolation):
    """No place left; ``extra["waitlist"]`` says whether the class takes a waitlist."""


class NotEligible(BusinessRuleViolation):
    pass


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _setting(key: str) -> Any:
    return get_setting(f"courses.{key}")


def _zone(branch: Any) -> ZoneInfo:
    return ZoneInfo(str(getattr(branch, "timezone", "") or "UTC"))


def local_today(group_class: GroupClass) -> date:
    return now().astimezone(ZoneInfo(group_class.timezone)).date()


# --- academic years, terms and breaks (T01) -----------------------------------------------------


@transaction.atomic
def save_academic_year(year: AcademicYear | None, **data: Any) -> AcademicYear:
    created = year is None
    year = year or AcademicYear()
    with audit.track(year):
        for key in ("name", "start_date", "end_date", "branch"):
            if key in data:
                setattr(year, key, data[key])
        if year.end_date < year.start_date:
            raise _invalid("end_date", _("The year ends before it starts."))
        if (
            AcademicYear.objects.filter(
                branch_id=year.branch_id or _default_branch(), name=year.name
            )
            .exclude(pk=year.pk)
            .exists()
        ):
            raise _invalid("name", _("There is already a year with this name."))
        year.save()
    if created:
        audit.record_create(year)
    return year


def _default_branch() -> Any:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.selectors import default_branch_id

    return default_branch_id(require_organisation_id())


def _check_breaks(term: Term, breaks: list[dict[str, Any]]) -> None:
    for row in breaks:
        if row["end_date"] < row["start_date"]:
            raise _invalid("breaks", _("A break ends before it starts."))
        if row["start_date"] < term.start_date or row["end_date"] > term.end_date:
            raise _invalid("breaks", _("Breaks must fall inside the term."))


@transaction.atomic
def save_term(
    term: Term | None, *, breaks: list[dict[str, Any]] | None = None, **data: Any
) -> Term:
    """Create or change a term and (optionally) replace its breaks. Classes of the term
    re-plan their sessions when the breaks or dates change, and termly billing plans
    follow the new dates (E10)."""
    created = term is None
    term = term or Term()
    before = (term.start_date, term.end_date) if not created else None
    with audit.track(term):
        for key in (
            "academic_year",
            "name",
            "start_date",
            "end_date",
            "enrolment_opens",
            "enrolment_closes",
        ):
            if key in data:
                setattr(term, key, data[key])
        year = term.academic_year
        term.branch_id = year.branch_id
        if term.end_date < term.start_date:
            raise _invalid("end_date", _("The term ends before it starts."))
        if term.start_date < year.start_date or term.end_date > year.end_date:
            raise _invalid("start_date", _("The term must fall inside its academic year."))
        if (
            term.enrolment_opens
            and term.enrolment_closes
            and term.enrolment_closes < term.enrolment_opens
        ):
            raise _invalid("enrolment_closes", _("Enrolment closes before it opens."))
        clash = (
            Term.objects.filter(
                branch_id=term.branch_id,
                start_date__lte=term.end_date,
                end_date__gte=term.start_date,
            )
            .exclude(pk=term.pk)
            .first()
        )
        if clash is not None:
            raise _invalid("start_date", _("The dates overlap %(term)s.") % {"term": clash.name})
        if not created and term.classes.exists() and before != (term.start_date, term.end_date):
            outside = term.classes.filter(
                Q(start_date__lt=term.start_date) | Q(end_date__gt=term.end_date)
            ).exclude(status=GroupClass.Status.CANCELLED)
            if outside.exists():
                raise _invalid("start_date", _("Some classes would fall outside the term."))
        term.save()
    if created:
        audit.record_create(term)
    breaks_changed = False
    if breaks is not None:
        _check_breaks(term, breaks)
        old = sorted(term.breaks.values_list("start_date", "end_date"))
        new = sorted((b["start_date"], b["end_date"]) for b in breaks)
        if old != new or [b.name for b in term.breaks.all()] != [b["name"] for b in breaks]:
            term.breaks.all().delete()
            for row in breaks:
                TermBreak.objects.create(
                    term=term,
                    name=str(row.get("name") or _("Break"))[:100],
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                )
            audit.record(term, "breaks", {"breaks": [str(old), str(new)]})
            breaks_changed = old != new
    if breaks_changed:
        for group_class in term.classes.exclude(
            status__in=[GroupClass.Status.CANCELLED, GroupClass.Status.COMPLETED]
        ):
            rebuild_sessions(group_class)
    if created or before != (term.start_date, term.end_date):
        from tutortrack.billing import plans

        plans.term_dates_changed(term.branch_id)
    return term


@transaction.atomic
def delete_term(term: Term) -> None:
    if term.classes.exists():
        raise BusinessRuleViolation(_("This term has classes; cancel or move them first."))
    audit.record(term, "delete")
    branch_id = term.branch_id
    term.delete()
    from tutortrack.billing import plans

    plans.term_dates_changed(branch_id)


@transaction.atomic
def delete_academic_year(year: AcademicYear) -> None:
    if year.terms.exists():
        raise BusinessRuleViolation(_("Delete the year's terms first."))
    audit.record(year, "delete")
    year.delete()


# --- courses (T02) ------------------------------------------------------------------------------

COURSE_FIELDS = {
    "name",
    "description",
    "public_description",
    "service",
    "subject",
    "level",
    "min_age",
    "max_age",
    "year_groups",
    "prerequisites",
    "duration_weeks",
    "duration_sessions",
    "delivery_mode",
    "default_capacity",
    "pricing_model",
    "price",
    "instalments",
    "deposit",
    "registration_fee",
    "materials_fee",
    "tax_rate",
    "image",
    "is_public",
}


def _check_course(course: Course) -> None:
    service: Service = course.service
    if course.currency != service.currency:
        raise _invalid("price", _("Use the service's currency (%(c)s).") % {"c": service.currency})
    for name in ("price", "deposit", "registration_fee", "materials_fee"):
        value = getattr(course, name)
        if value is not None and value.is_negative():
            raise _invalid(name, _("Amounts can't be negative."))
    if (
        course.min_age is not None
        and course.max_age is not None
        and course.max_age < course.min_age
    ):
        raise _invalid("max_age", _("The oldest age is below the youngest."))
    if course.default_capacity > service.max_students:
        raise _invalid(
            "default_capacity",
            _("%(service)s takes at most %(n)s students; raise it in the catalogue first.")
            % {"service": service.name, "n": service.max_students},
        )
    if course.pricing_model == Course.PricingModel.PER_SESSION:
        if service.pricing_unit in (Service.PricingUnit.PER_MONTH, Service.PricingUnit.PER_TERM):
            raise _invalid("service", _("Pay-as-you-go courses need a service priced per session."))
        if service.group_charge == Service.GroupCharge.SPLIT:
            raise _invalid("service", _("Pay-as-you-go courses need each student to pay the rate."))
    if course.pricing_model == Course.PricingModel.INSTALMENTS and course.instalments < 2:
        raise _invalid("instalments", _("Instalments need at least two payments."))
    if course.pricing_model != Course.PricingModel.INSTALMENTS:
        course.instalments = 1


def _money(course: Course, data: dict[str, Any]) -> None:
    for name in ("price", "deposit", "registration_fee", "materials_fee"):
        if name in data:
            value = data.pop(name)
            if value is not None and value.currency != course.currency:
                raise _invalid(name, _("Use the course currency (%(c)s).") % {"c": course.currency})
            setattr(course, name, value.round_to_minor() if value is not None else None)


@transaction.atomic
def save_course(course: Course | None, **data: Any) -> Course:
    unknown = set(data) - COURSE_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown course fields: {', '.join(sorted(unknown))}")
    created = course is None
    if created:
        entitlements.require("courses")
    course = course or Course()
    with audit.track(course):
        if "service" in data:
            course.service = data.pop("service")
            course.currency = course.service.currency
            course.subject_id = course.subject_id or course.service.subject_id
            course.level_id = course.level_id or course.service.level_id
        if created and course.service_id is None:
            raise _invalid("service", _("Choose the service sessions are scheduled as."))
        if created and data.get("price") is None:
            raise _invalid("price", _("Give the price."))
        _money(course, data)
        for key, value in data.items():
            setattr(course, key, value)
        if course.year_groups:
            course.year_groups = [str(y).strip()[:40] for y in course.year_groups if str(y).strip()]
        _check_course(course)
        course.save()
    if created:
        audit.record_create(course)
    return course


@transaction.atomic
def set_course_archived(course: Course, archived: bool) -> Course:
    with audit.track(course, action="archive" if archived else "restore"):
        course.archived_at = now() if archived else None
        course.save(update_fields=["archived_at", "updated_at"])
    return course


# --- classes and sessions (T02) -----------------------------------------------------------------


def _check_class(group_class: GroupClass) -> None:
    course, term = group_class.course, group_class.term
    if group_class.start_date < term.start_date or group_class.end_date > term.end_date:
        raise _invalid("start_date", _("The class must run inside its term."))
    if group_class.end_date < group_class.start_date:
        raise _invalid("end_date", _("The class ends before it starts."))
    if group_class.capacity < 1:
        raise _invalid("capacity", _("A class needs at least one place."))
    if group_class.capacity > course.service.max_students:
        raise _invalid(
            "capacity",
            _("%(service)s takes at most %(n)s students; raise it in the catalogue first.")
            % {"service": course.service.name, "n": course.service.max_students},
        )
    room = group_class.room
    if room is not None and room.capacity and group_class.capacity > room.capacity:
        raise _invalid(
            "capacity", _("%(room)s holds %(n)s people.") % {"room": room.name, "n": room.capacity}
        )
    if group_class.min_size > group_class.capacity:
        raise _invalid("min_size", _("The minimum is more than the class holds."))
    if group_class.teacher_pay_mode != GroupClass.TeacherPay.SERVICE:
        _check_teacher_pay(group_class)


def _check_teacher_pay(group_class: GroupClass) -> None:
    config = group_class.teacher_pay or {}
    mode = group_class.teacher_pay_mode
    try:
        if mode in (GroupClass.TeacherPay.PER_SESSION, GroupClass.TeacherPay.FIXED):
            if Money(Decimal(str(config.get("amount"))), group_class.course.currency).is_negative():
                raise ValueError
        elif mode == GroupClass.TeacherPay.HEADCOUNT:
            tiers = config.get("tiers") or []
            if not tiers:
                raise ValueError
            for tier in tiers:
                if (
                    int(tier["from"]) < 0
                    or Money(Decimal(str(tier["amount"])), "GBP").is_negative()
                ):
                    raise ValueError
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise _invalid("teacher_pay", _("Give the teacher's pay for this rule.")) from exc


def _teacher_rows(
    group_class: GroupClass, lesson: Any, *, headcount: int, sessions: int, index: int
) -> list[dict[str, Any]]:
    service = group_class.course.service
    per_hour = service.pay_unit == Service.PayUnit.PER_HOUR
    rows = []
    for teacher in group_class.teachers.select_related("tutor"):
        amount = (
            teacher.pay_per_session
            if teacher.pay_per_session is not None
            else pricing.teacher_session_pay(
                group_class.teacher_pay_mode,
                group_class.teacher_pay or {},
                group_class.course.currency,
                headcount=headcount,
                sessions=sessions,
                index=index,
            )
        )
        rate = (
            pricing.rate_for(amount, per_hour=per_hour, minutes=lesson.duration_minutes)
            if amount is not None
            else None
        )
        rows.append({"tutor": teacher.tutor, "pay_rate_override": rate})
    return rows


def _charge_override(group_class: GroupClass, enrolment: Enrolment, lesson: Any) -> Money:
    """What the lesson charges this student: pay-as-you-go courses charge each session
    (the enrolment's price, as a rate for the service's unit); every other model bills the
    fee instead, so the session itself costs nothing (E10 charges nothing at zero)."""
    course = group_class.course
    zero = Money.zero(course.currency)
    if course.pricing_model != Course.PricingModel.PER_SESSION:
        return zero
    if enrolment.status == Enrolment.Status.TRIAL:
        return zero
    per_hour = course.service.pricing_unit == Service.PricingUnit.PER_HOUR
    return pricing.rate_for(enrolment.fee, per_hour=per_hour, minutes=lesson.duration_minutes)


def _session_attendees(session: ClassSession) -> list[dict[str, Any]]:
    group_class = session.group_class
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for enrolment in selectors.attending_on(group_class, session.date).select_related("student"):
        rows.append(
            {
                "student": enrolment.student,
                "client_id": enrolment.client_id,
                "charge_rate_override": _charge_override(group_class, enrolment, session.lesson),
            }
        )
        seen.add(str(enrolment.student_id))
    for booking in selectors.makeups_for(session):
        if str(booking.student_id) in seen:
            continue
        rows.append(
            {
                "student": booking.student,
                "client_id": booking.client_id,
                "charge_rate_override": Money.zero(group_class.course.currency),
            }
        )
    return rows


def sync_class_roster(
    group_class: GroupClass, *, sessions: list[ClassSession] | None = None
) -> int:
    """Make every future, planned session's attendees and teachers match the class
    (enrolments covering the session's date plus makeup bookings). Past, delivered and
    invoiced sessions never change. Returns the sessions changed."""
    from tutortrack.scheduling import services as scheduling

    ordered = list(
        group_class.sessions.exclude(lesson__status="cancelled")
        .order_by("date", "number")
        .values_list("pk", flat=True)
    )
    index = {pk: i for i, pk in enumerate(ordered)}
    targets = (
        sessions
        if sessions is not None
        else list(
            group_class.sessions.select_related("lesson").filter(
                lesson__status="planned", lesson__lock_state="unlocked", lesson__start__gte=now()
            )
        )
    )
    changed = 0
    for session in targets:
        lesson = session.lesson
        if lesson.status != "planned" or lesson.is_locked or lesson.start < now():
            continue
        attendees = _session_attendees(session)
        tutors = _teacher_rows(
            group_class,
            lesson,
            headcount=len(attendees),
            sessions=len(ordered),
            index=index.get(session.pk, 0),
        )
        if scheduling.sync_group_roster(lesson, attendees=attendees, tutors=tutors):
            changed += 1
    return changed


def sync_sessions(group_class: GroupClass) -> int:
    """Link the class's series lessons as sessions (numbered by date) and sync rosters."""
    from tutortrack.scheduling.models import Lesson
    from tutortrack.scheduling.recurrence import local_date_of

    if group_class.series_id is None:
        return 0
    linked = set(group_class.sessions.values_list("lesson_id", flat=True))
    for lesson in Lesson.objects.filter(series_id=group_class.series_id).order_by("start"):
        if lesson.pk not in linked:
            ClassSession.objects.create(
                group_class=group_class,
                lesson=lesson,
                date=lesson.occurrence_date or local_date_of(lesson.start, lesson.timezone),
            )
    for number, session in enumerate(group_class.sessions.order_by("date", "created_at"), 1):
        if session.number != number:
            ClassSession.objects.filter(pk=session.pk).update(number=number)
    return sync_class_roster(group_class)


def rebuild_sessions(group_class: GroupClass, **schedule: Any) -> int:
    """Re-plan future sessions (new breaks, times or days); delivered ones stay."""
    from tutortrack.scheduling import services as scheduling
    from tutortrack.scheduling.models import LessonSeries

    if group_class.series_id is None:
        return 0
    series = LessonSeries.objects.get(pk=group_class.series_id)
    changes = {"skip_holidays": True, **schedule}
    scheduling.edit_series(series, scope="all", allow_empty_roster=True, **changes)
    scheduling.extend_series(series, until=group_class.end_date)
    return sync_sessions(group_class)


def _place_fields(data: dict[str, Any]) -> dict[str, Any]:
    room = data.get("room")
    if room is not None:
        data["location"] = room.location
        data["online"] = False
    return data


@transaction.atomic
def create_class(
    *,
    course: Course,
    term: Term,
    name: str,
    start_time: time,
    duration_minutes: int,
    rrule: str = "FREQ=WEEKLY",
    start_date: date | None = None,
    end_date: date | None = None,
    capacity: int | None = None,
    teachers: list[dict[str, Any]] | None = None,
    conflict_mode: str = "skip",
    user: Any = None,
    **fields: Any,
) -> tuple[GroupClass, list[str]]:
    """A class and its sessions (lessons), one per occurrence of ``rrule`` from the start
    to the end date, skipping holidays and term breaks. Returns the class and the dates
    skipped because a teacher or the room was busy."""
    from tutortrack.scheduling import recurrence
    from tutortrack.scheduling import services as scheduling

    if course.archived_at is not None:
        raise _invalid("course", _("This course is archived."))
    allowed = {
        "location",
        "room",
        "online",
        "min_size",
        "waitlist_enabled",
        "min_age",
        "max_age",
        "year_groups",
        "teacher_pay_mode",
        "teacher_pay",
        "is_public",
        "status",
        "next_class",
        "timezone",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise BusinessRuleViolation(f"Unknown class fields: {', '.join(sorted(unknown))}")
    fields = _place_fields(fields)
    group_class = GroupClass(
        course=course,
        term=term,
        branch_id=term.branch_id,
        name=name[:150],
        rrule=recurrence.clean_rrule(rrule),
        start_date=start_date or term.start_date,
        end_date=end_date or term.end_date,
        start_time=start_time,
        duration_minutes=duration_minutes,
        timezone=fields.pop("timezone", "") or str(term.branch.timezone),
        capacity=capacity or course.default_capacity,
        **fields,
    )
    if group_class.status not in (GroupClass.Status.DRAFT, GroupClass.Status.OPEN):
        raise _invalid("status", _("New classes start as a draft or open."))
    _check_class(group_class)
    group_class.save()
    _set_teachers(group_class, teachers or [])
    audit.record_create(group_class)
    result = scheduling.create_series(
        rrule=group_class.rrule,
        start_date=group_class.start_date,
        start_time=start_time,
        duration_minutes=duration_minutes,
        service=course.service,
        timezone=group_class.timezone,
        attendees=[],
        tutors=[{"tutor": t.tutor} for t in group_class.teachers.select_related("tutor")],
        until=group_class.end_date,
        skip_holidays=True,
        location=group_class.location,
        online=group_class.online,
        room=group_class.room,
        branch=term.branch,
        title=f"{course.name} \N{EN DASH} {group_class.name}"[:200],
        conflict_mode=conflict_mode,
        notify=False,
        allow_empty_roster=True,
        extra_template={"group_class": str(group_class.pk)},
    )
    scheduling.extend_series(result.series, until=group_class.end_date)
    group_class.series = result.series
    group_class.save(update_fields=["series", "updated_at"])
    sync_sessions(group_class)
    return group_class, [day.isoformat() for day, _c in result.skipped]


def _set_teachers(group_class: GroupClass, rows: list[dict[str, Any]]) -> bool:
    from tutortrack.people.assignability import check_assignable

    wanted = {str(r["tutor"].pk): r for r in rows}
    current = {str(t.tutor_id): t for t in group_class.teachers.all()}
    changed = False
    for tutor_id, old in current.items():
        if tutor_id not in wanted:
            old.delete()
            changed = True
    for tutor_id, row in wanted.items():
        pay = row.get("pay_per_session")
        if pay is not None and pay.currency != group_class.course.currency:
            raise _invalid("teachers", _("Use the course currency for teacher pay."))
        role = row.get("role") or ClassTeacher.Role.LEAD
        teacher = current.get(tutor_id)
        if teacher is None:
            check_assignable(row["tutor"], "teachers")
            teacher = ClassTeacher(group_class=group_class, tutor=row["tutor"])
            changed = True
        elif teacher.role == role and teacher.pay_per_session == pay:
            continue
        teacher.role = role
        teacher.currency = group_class.course.currency
        teacher.pay_per_session = pay.round_to_minor() if pay is not None else None
        teacher.save()
        changed = True
    return changed


CLASS_FIELDS = {
    "name",
    "capacity",
    "min_size",
    "waitlist_enabled",
    "min_age",
    "max_age",
    "year_groups",
    "teacher_pay_mode",
    "teacher_pay",
    "is_public",
    "next_class",
    "location",
    "room",
    "online",
    "start_time",
    "duration_minutes",
    "rrule",
    "teachers",
}


@transaction.atomic
def update_class(group_class: GroupClass, *, user: Any = None, **changes: Any) -> GroupClass:
    """Change a class. New times, days or places re-plan its future sessions; a bigger
    class offers the new places to its waitlist."""
    from tutortrack.scheduling import recurrence

    unknown = set(changes) - CLASS_FIELDS
    if unknown:
        raise BusinessRuleViolation(f"Unknown class fields: {', '.join(sorted(unknown))}")
    group_class = GroupClass.objects.select_for_update().get(pk=group_class.pk)
    if group_class.status in (GroupClass.Status.CANCELLED, GroupClass.Status.COMPLETED):
        raise BusinessRuleViolation(_("This class has finished."))
    teachers = changes.pop("teachers", None)
    if "rrule" in changes:
        changes["rrule"] = recurrence.clean_rrule(changes["rrule"])
    schedule: dict[str, Any] = {
        k: changes[k]
        for k in ("start_time", "duration_minutes", "rrule")
        if k in changes and changes[k] != getattr(group_class, k)
    }
    if "room" in changes:
        changes = _place_fields(changes)
    place: dict[str, Any] = {k: changes[k] for k in ("location", "room", "online") if k in changes}
    old_capacity = group_class.capacity
    with audit.track(group_class):
        for key, value in changes.items():
            setattr(group_class, key, value)
        _check_class(group_class)
        if group_class.capacity < selectors.active_count(group_class):
            raise _invalid("capacity", _("More students are enrolled than that."))
        group_class.save()
    teachers_changed = teachers is not None and _set_teachers(group_class, teachers)
    if (schedule or place) and group_class.series_id:
        from tutortrack.scheduling import services as scheduling
        from tutortrack.scheduling.models import LessonSeries

        series = LessonSeries.objects.get(pk=group_class.series_id)
        edits: dict[str, Any] = dict(schedule)
        edits.update({k: v for k, v in place.items() if k in ("location", "online")})
        if edits:
            scheduling.edit_series(series, scope="all", allow_empty_roster=True, **edits)
        if "room" in place:
            series.template = {
                **series.template,
                "room": str(place["room"].pk) if place["room"] else None,
            }
            series.save(update_fields=["template", "updated_at"])
        scheduling.extend_series(series, until=group_class.end_date)
        sync_sessions(group_class)
    elif teachers_changed or "teacher_pay_mode" in changes or "teacher_pay" in changes:
        sync_class_roster(group_class)
    if group_class.capacity > old_capacity:
        _update_fullness(group_class)
        places_freed(group_class)
    elif group_class.capacity < old_capacity:
        _update_fullness(group_class)
    return group_class


@transaction.atomic
def open_class(group_class: GroupClass, *, user: Any = None) -> GroupClass:
    group_class = GroupClass.objects.select_for_update().get(pk=group_class.pk)
    if group_class.status != GroupClass.Status.DRAFT:
        raise BusinessRuleViolation(_("Only draft classes can be opened."))
    with audit.track(group_class, action="open"):
        group_class.status = GroupClass.Status.OPEN
        group_class.save(update_fields=["status", "updated_at"])
    _update_fullness(group_class)
    places_freed(group_class)
    return group_class


@transaction.atomic
def cancel_class(group_class: GroupClass, *, reason: str = "", user: Any = None) -> GroupClass:
    """Cancel the class: its future sessions are cancelled, every student is withdrawn
    with unused sessions credited, and its waitlist is closed."""
    from tutortrack.leads import services as leads
    from tutortrack.scheduling import services as scheduling
    from tutortrack.scheduling.models import LessonSeries

    group_class = GroupClass.objects.select_for_update().get(pk=group_class.pk)
    if group_class.status in (GroupClass.Status.CANCELLED, GroupClass.Status.COMPLETED):
        raise BusinessRuleViolation(_("This class has already finished."))
    today = local_today(group_class)
    withdrawn = 0
    for enrolment in group_class.enrolments.filter(status__in=Enrolment.ACTIVE):
        if enrolment.status == Enrolment.Status.PENDING_PAYMENT:
            release_enrolment(enrolment.pk, reason="class_cancelled")
        else:
            withdraw(
                enrolment,
                effective=max(today, enrolment.start_date),
                reason=reason or _("The class was cancelled."),
                refund=True,
                user=user,
                fill=False,
            )
        withdrawn += 1
    with audit.track(group_class, action="cancel"):
        group_class.status = GroupClass.Status.CANCELLED
        group_class.cancelled_at = now()
        group_class.cancel_reason = reason[:300]
        group_class.save()
    if group_class.series_id:
        scheduling.end_series(
            LessonSeries.objects.get(pk=group_class.series_id),
            after=today - timedelta(days=1),
            reason=reason or _("Class cancelled"),
        )
    for entry in selectors.waiting(group_class).filter(status__in=["waiting", "offered"]):
        leads.remove_from_waitlist(entry)
    publish(
        events.ClassCancelled(
            subject_id=group_class.pk,
            course_id=str(group_class.course_id),
            reason=reason,
            enrolments_withdrawn=withdrawn,
        ),
        branch_id=group_class.branch_id,
    )
    return group_class


def _update_fullness(group_class: GroupClass) -> None:
    """Open ⇄ full as places are taken and freed (``class.full`` when it fills)."""
    taken = selectors.taken_places(group_class)
    if group_class.status == GroupClass.Status.OPEN and taken >= group_class.capacity:
        GroupClass.objects.filter(pk=group_class.pk).update(status=GroupClass.Status.FULL)
        group_class.status = GroupClass.Status.FULL
        publish(
            events.ClassFull(
                subject_id=group_class.pk,
                course_id=str(group_class.course_id),
                capacity=group_class.capacity,
            ),
            branch_id=group_class.branch_id,
        )
    elif group_class.status == GroupClass.Status.FULL and taken < group_class.capacity:
        GroupClass.objects.filter(pk=group_class.pk).update(status=GroupClass.Status.OPEN)
        group_class.status = GroupClass.Status.OPEN


def _check_minimum(group_class: GroupClass) -> None:
    if not group_class.min_size:
        return
    count = selectors.active_count(group_class)
    if count < group_class.min_size:
        publish(
            events.ClassBelowMinimum(
                subject_id=group_class.pk,
                course_id=str(group_class.course_id),
                enrolled=count,
                min_size=group_class.min_size,
            ),
            branch_id=group_class.branch_id,
        )


def places_freed(group_class: GroupClass) -> None:
    """Tell the class a place may be free (its waitlist is offered places by a handler)."""
    if selectors.waiting(group_class).filter(status="waiting").exists():
        publish(
            events.ClassPlacesFreed(
                subject_id=group_class.pk, course_id=str(group_class.course_id)
            ),
            branch_id=group_class.branch_id,
        )


def session_lesson_completed(lesson_id: Any) -> None:
    """A session was delivered: the class is running; when every session is done the
    class and its enrolments are completed."""
    session = ClassSession.objects.select_related("group_class").filter(lesson_id=lesson_id).first()
    if session is None:
        return
    group_class = session.group_class
    if group_class.status in (GroupClass.Status.OPEN, GroupClass.Status.FULL):
        GroupClass.objects.filter(pk=group_class.pk).update(status=GroupClass.Status.RUNNING)
        group_class.status = GroupClass.Status.RUNNING
    if group_class.status != GroupClass.Status.RUNNING:
        return
    if group_class.sessions.filter(lesson__status="planned").exists():
        return
    with audit.track(group_class, action="complete"):
        group_class.status = GroupClass.Status.COMPLETED
        group_class.save(update_fields=["status", "updated_at"])
    for enrolment in group_class.enrolments.filter(status__in=Enrolment.ATTENDING):
        with audit.track(enrolment, action="complete"):
            enrolment.status = Enrolment.Status.COMPLETED
            enrolment.save(update_fields=["status", "updated_at"])
        publish(
            events.EnrolmentCompleted(
                subject_id=enrolment.pk,
                class_id=str(group_class.pk),
                student_id=str(enrolment.student_id),
                client_id=str(enrolment.client_id),
            ),
            branch_id=enrolment.branch_id,
        )


# --- enrolment: eligibility and price (T03, T04) ------------------------------------------------


def age_on(born: date, day: date) -> int:
    return day.year - born.year - ((day.month, day.day) < (born.month, born.day))


def eligibility_problems(
    group_class: GroupClass,
    *,
    date_of_birth: date | None,
    year_group: str,
) -> list[str]:
    problems = []
    low, high = selectors.age_range(group_class)
    if low is not None or high is not None:
        if date_of_birth is None:
            problems.append(_("We need the student's date of birth for this class."))
        else:
            age = age_on(date_of_birth, group_class.start_date)
            if low is not None and age < low:
                problems.append(_("This class is for ages %(n)s and up.") % {"n": low})
            if high is not None and age > high:
                problems.append(_("This class is for ages up to %(n)s.") % {"n": high})
    years = selectors.year_groups(group_class)
    if years and (year_group or "").strip().lower() not in {y.strip().lower() for y in years}:
        problems.append(_("This class is for %(years)s.") % {"years": ", ".join(years)})
    return problems


def _discounts(course: Course, today: date) -> list[pricing.CourseDiscount]:
    kinds = [
        DiscountRule.Kind.SIBLING,
        DiscountRule.Kind.MULTI_CLASS,
        DiscountRule.Kind.CLIENT,
        DiscountRule.Kind.SCHOLARSHIP,
    ]
    rules = (
        DiscountRule.objects.filter(active=True, kind__in=kinds)
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    )
    out = []
    for rule in rules:
        if rule.services and str(course.service_id) not in [str(s) for s in rule.services]:
            continue
        fixed = (
            Money(rule.fixed_amount_amount, rule.currency)
            if rule.currency and rule.fixed_amount_amount is not None
            else None
        )
        out.append(
            pricing.CourseDiscount(
                name=rule.name,
                kind=rule.kind,
                percent=rule.percent,
                fixed_amount=fixed,
                priority=rule.priority,
                stackable=rule.stackable,
                threshold=(
                    rule.min_classes or 2
                    if rule.kind == DiscountRule.Kind.MULTI_CLASS
                    else rule.sibling_from
                ),
                client_id=str(rule.client_id) if rule.client_id else None,
                student_id=str(rule.student_id) if rule.student_id else None,
            )
        )
    return out


def _facts(
    group_class: GroupClass, student: Student | None, client: Client | None
) -> pricing.Facts:
    if student is None:
        return pricing.Facts(client_id=str(client.pk) if client else "")
    term_enrolments = Enrolment.objects.filter(
        group_class__term=group_class.term, status__in=Enrolment.ACTIVE
    ).exclude(group_class=group_class)
    mine = term_enrolments.filter(student=student).values("group_class").distinct().count()
    # Children count in the order they first enrolled this term (first child = 1).
    order: list[str] = []
    for student_id in (
        Enrolment.objects.filter(
            group_class__term=group_class.term,
            status__in=Enrolment.ACTIVE,
            client_id=student.client_id,
        )
        .order_by("created_at")
        .values_list("student_id", flat=True)
    ):
        if str(student_id) not in order:
            order.append(str(student_id))
    position = order.index(str(student.pk)) + 1 if str(student.pk) in order else len(order) + 1
    return pricing.Facts(
        sibling_position=position,
        classes_this_term=mine + 1,
        client_id=str(student.client_id),
        student_id=str(student.pk),
    )


def units(group_class: GroupClass, joining: date) -> tuple[int, int, str]:
    """(total units, units from ``joining``, basis) for proration (setting)."""
    basis = str(_setting("proration_basis"))
    if basis == "weeks":
        total, remaining = pricing.week_units(
            group_class.start_date,
            group_class.end_date,
            selectors.breaks_of(group_class.term),
            joining,
        )
    else:
        total, remaining = pricing.session_units(selectors.session_dates(group_class), joining)
    return total, remaining, basis


def default_start(group_class: GroupClass) -> date:
    return max(local_today(group_class), group_class.start_date)


def registration_key(student: Student, group_class: GroupClass) -> str:
    return f"registration:{student.pk}:{group_class.term.academic_year_id}"


def _registration_due(student: Student | None, group_class: GroupClass) -> bool:
    from tutortrack.billing.models import Charge

    course = group_class.course
    if course.registration_fee is None or not course.registration_fee.is_positive():
        return False
    if student is None:
        return True
    return (
        not Charge.objects.filter(source_key__startswith=registration_key(student, group_class))
        .exclude(status=Charge.Status.VOID)
        .exists()
    )


def quote(
    group_class: GroupClass,
    *,
    student: Student | None = None,
    client: Client | None = None,
    start_date: date | None = None,
    trial: bool = False,
    with_fees: bool = True,
) -> dict[str, Any]:
    """The price of a place (FR-20-7): list price, sibling/multi-class discounts, the
    prorated fee for a mid-term join, one-off fees and what is due at enrolment."""
    course = group_class.course
    start = start_date or default_start(group_class)
    zero = Money.zero(course.currency).round_to_minor()
    q = pricing.quote(
        course.price,
        _discounts(course, local_today(group_class)),
        _facts(group_class, student, client),
    )
    total = remaining = 0
    basis = ""
    fee_due = q.price
    if course.pricing_model in FEE_MODELS and start > group_class.start_date:
        total, remaining, basis = units(group_class, start)
        if _setting("prorate_mid_term_joins"):
            fee_due = pricing.prorate(q.price, total=total, remaining=remaining)
    if trial:
        fee_due = zero
    if course.pricing_model in (Course.PricingModel.PER_TERM, Course.PricingModel.FULL_COURSE):
        upfront = fee_due
    elif course.pricing_model == Course.PricingModel.INSTALMENTS:
        upfront = pricing.instalments(fee_due, course.instalments, start)[0][1]
    elif course.pricing_model == Course.PricingModel.PER_MONTH:
        upfront = fee_due
    else:
        upfront = zero
    registration = (
        course.registration_fee
        if with_fees and not trial and _registration_due(student, group_class)
        else None
    ) or zero
    materials = (course.materials_fee if with_fees and not trial else None) or zero
    due_now = upfront + registration + materials
    deposit = (
        min(course.deposit, due_now)
        if course.deposit is not None and course.deposit.is_positive()
        else None
    )
    return {
        **q.as_dict(),
        "pricing_model": course.pricing_model,
        "start_date": start.isoformat(),
        "fee_due": fee_due.to_dict(),
        "units": {"basis": basis, "total": total, "remaining": remaining},
        "instalments": course.instalments,
        "registration_fee": registration.to_dict(),
        "materials_fee": materials.to_dict(),
        "due_now": due_now.to_dict(),
        "deposit": deposit.to_dict() if deposit is not None else None,
    }


def _m(value: dict[str, str] | None, currency: str) -> Money:
    if not value:
        return Money.zero(currency)
    return Money(Decimal(str(value["amount"])), value.get("currency") or currency)


def fee_key(enrolment: Enrolment) -> str:
    return f"enrolment:{enrolment.pk}:fee"


# --- enrolment: writes (T03) --------------------------------------------------------------------


def _lock_class(group_class: GroupClass) -> GroupClass:
    return (
        GroupClass.objects.select_for_update()
        .select_related("course__service", "term__academic_year")
        .get(pk=group_class.pk)
    )


@transaction.atomic
def enrol(
    group_class: GroupClass,
    student: Student,
    *,
    start_date: date | None = None,
    trial: bool = False,
    source: str = Enrolment.Source.STAFF,
    payment: str = Enrolment.Payment.NONE,
    override_capacity: bool = False,
    check_eligibility: bool = True,
    accept_terms: bool = False,
    waitlist_entry_id: Any = None,
    with_fees: bool = True,
    user: Any = None,
) -> Enrolment:
    """Enrol a student (FR-20-4). The class row is locked, so two families can't take the
    last place at once. Online enrolment with payment holds the place (``pending_payment``)
    until ``EnrolmentPaymentWorkflow`` sees the payment; otherwise the student joins every
    session from ``start_date`` and the fees are billed (E10)."""
    from tutortrack.billing.selectors import booking_block

    group_class = _lock_class(group_class)
    staff = source == Enrolment.Source.STAFF
    allowed = (GroupClass.Status.DRAFT, *GroupClass.ENROLLABLE) if staff else GroupClass.ENROLLABLE
    if group_class.status not in allowed:
        raise BusinessRuleViolation(_("This class isn't taking enrolments."))
    if student.archived_at is not None:
        raise _invalid("student", _("%(name)s is archived.") % {"name": student.full_name})
    if Enrolment.objects.filter(
        group_class=group_class, student=student, status__in=Enrolment.ACTIVE
    ).exists():
        raise _invalid(
            "student", _("%(name)s is already in this class.") % {"name": student.full_name}
        )
    start = start_date or default_start(group_class)
    if start > group_class.end_date:
        raise _invalid("start_date", _("This class has finished."))
    if start < group_class.start_date:
        start = group_class.start_date
    if check_eligibility:
        problems = eligibility_problems(
            group_class, date_of_birth=student.date_of_birth, year_group=student.year_group
        )
        if problems:
            raise NotEligible(problems[0], extra={"code": "not_eligible", "problems": problems})
    if not staff and booking_block(student.client_id) == "hard":
        raise BusinessRuleViolation(
            _("Online enrolment isn't available for your account at the moment. Please contact us.")
        )
    if not override_capacity and (
        selectors.taken_places(group_class, exclude_entry=waitlist_entry_id) >= group_class.capacity
    ):
        raise ClassFull(
            _("%(name)s is full.") % {"name": group_class.name},
            extra={"code": "class_full", "waitlist": group_class.waitlist_enabled},
        )
    terms_text = str(_setting("enrolment_terms") or "").strip()
    if not staff and terms_text and not accept_terms:
        raise _invalid("accept_terms", _("Please accept the terms to enrol."))
    price = quote(group_class, student=student, start_date=start, trial=trial, with_fees=with_fees)
    course = group_class.course
    due_now = _m(price["due_now"], course.currency)
    if payment == Enrolment.Payment.DEPOSIT and price.get("deposit"):
        due_now = _m(price["deposit"], course.currency)
    pending = payment != Enrolment.Payment.NONE and due_now.is_positive() and not trial
    enrolment = Enrolment(
        group_class=group_class,
        student=student,
        client_id=student.client_id,
        branch_id=group_class.branch_id,
        status=(
            Enrolment.Status.PENDING_PAYMENT
            if pending
            else Enrolment.Status.TRIAL
            if trial
            else Enrolment.Status.ENROLLED
        ),
        source=source,
        start_date=start,
        currency=course.currency,
        price_snapshot=price,
        payment=payment if pending else Enrolment.Payment.NONE,
        terms_accepted_at=now() if accept_terms else None,
        waitlist_entry_id=waitlist_entry_id,
        created_by_user=user if getattr(user, "is_authenticated", False) else None,
    )
    enrolment.fee = _m(price["price"], course.currency)
    enrolment.save()
    audit.record_create(enrolment)
    if pending:
        from tutortrack.payments import services as payments

        request = payments.request_booking_payment(
            client=student.client,
            amount=due_now,
            description=_("Enrolment: %(course)s, %(cls)s (%(student)s)")
            % {"course": course.name, "cls": group_class.name, "student": student.full_name},
            user=enrolment.created_by_user,
        )
        enrolment.payment_request_id = request["payment_request_id"]
        enrolment.hold_expires_at = now() + timedelta(minutes=int(_setting("payment_hold_minutes")))
        enrolment.pay_url = str(request["pay_url"])  # type: ignore[attr-defined]
        from .processes import payment_workflow_id

        enrolment.workflow_id = payment_workflow_id(enrolment.organisation_id, enrolment.pk)
        enrolment.save(
            update_fields=["payment_request_id", "hold_expires_at", "workflow_id", "updated_at"]
        )
    else:
        enrolment.pay_url = ""  # type: ignore[attr-defined]
        _activate(enrolment, user=user)
    publish(
        events.EnrolmentCreated(
            subject_id=enrolment.pk,
            class_id=str(group_class.pk),
            student_id=str(student.pk),
            client_id=str(enrolment.client_id),
            status=enrolment.status,
            source=source,
            start_date=start.isoformat(),
        ),
        branch_id=enrolment.branch_id,
    )
    _update_fullness(group_class)
    return enrolment


def _activate(enrolment: Enrolment, *, user: Any = None) -> None:
    """The student joins the sessions from their start date and is billed."""
    group_class = enrolment.group_class
    sync_class_roster(group_class)
    if enrolment.status == Enrolment.Status.ENROLLED:
        _bill(enrolment, user=user)


def _bill(enrolment: Enrolment, *, user: Any = None) -> None:
    """Fees per the course's pricing model (FR-20-7): a term or course fee (prorated for
    late joiners), monthly instalments, an E10 monthly plan, or nothing up front for pay
    as you go (each session is charged when delivered). Registration (once per student
    and academic year) and materials fees are one-off charges. With fees at enrolment
    they are invoiced together straight away; otherwise they are dated from the start of
    term for the next invoice run."""
    from tutortrack.billing import plans
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import Charge

    if enrolment.billed_at is not None:
        return
    group_class = enrolment.group_class
    course = group_class.course
    snapshot = enrolment.price_snapshot or {}
    currency = course.currency
    fee_due = _m(snapshot.get("fee_due"), currency)
    at_enrolment = _setting("fee_timing") == "at_enrolment"
    today = local_today(group_class)
    day = today if at_enrolment else max(enrolment.start_date, today)
    student, client = enrolment.student, enrolment.client
    label = f"{course.name} \N{EN DASH} {group_class.name} ({student.full_name})"
    created: list[Any] = []
    key = fee_key(enrolment)
    model = course.pricing_model
    if model in (Course.PricingModel.PER_TERM, Course.PricingModel.FULL_COURSE):
        created += billing.charge_fee(
            client=client, student=student, source_key=key, description=label, price=fee_due,
            day=day, tax_rate=course.tax_rate, category="course", user=user,
        )  # fmt: skip
    elif model == Course.PricingModel.INSTALMENTS:
        schedule = pricing.instalments(fee_due, course.instalments, day)
        for number, (when, amount) in enumerate(schedule, 1):
            created += billing.charge_fee(
                client=client,
                student=student,
                source_key=f"{key}:i{number}",
                description=_("%(what)s, instalment %(n)s of %(of)s")
                % {"what": label, "n": number, "of": len(schedule)},
                price=amount,
                day=when,
                tax_rate=course.tax_rate,
                category="course",
                user=user,
            )
        created = [c for c in created if c.date <= day]  # later instalments: their month
    elif model == Course.PricingModel.PER_MONTH and fee_due.is_positive():
        plan = plans.create_plan(
            client=client,
            student=student,
            description=label,
            amount=fee_due,
            interval="monthly",
            start_date=enrolment.start_date,
            end_date=group_class.end_date,
            tax_rate=course.tax_rate,
            user=user,
        )
        enrolment.billing_plan_id = plan.pk
    if (
        snapshot.get("registration_fee")
        and _m(snapshot["registration_fee"], currency).is_positive()
    ):
        created += billing.charge_fee(
            client=client,
            student=student,
            source_key=registration_key(student, group_class),
            description=_("Registration fee (%(student)s)") % {"student": student.full_name},
            price=_m(snapshot["registration_fee"], currency),
            day=day,
            tax_rate=course.tax_rate,
            category="course",
            user=user,
        )
    if snapshot.get("materials_fee") and _m(snapshot["materials_fee"], currency).is_positive():
        created += billing.charge_fee(
            client=client,
            student=student,
            source_key=f"enrolment:{enrolment.pk}:materials",
            description=_("Materials: %(what)s") % {"what": label},
            price=_m(snapshot["materials_fee"], currency),
            day=day,
            tax_rate=course.tax_rate,
            category="course",
            user=user,
        )
    if at_enrolment and created:
        ids = [
            c.pk for c in created if c.status == Charge.Status.UNINVOICED and c.invoice_id is None
        ]
        for draft in billing.build_drafts(Charge.objects.filter(pk__in=ids), skip_small=False):
            billing.issue_invoice(draft, user=user)
    enrolment.billed_at = now()
    enrolment.save(update_fields=["billing_plan_id", "billed_at", "updated_at"])


def payment_state(enrolment_id: Any) -> dict[str, str]:
    """For ``EnrolmentPaymentWorkflow``."""
    enrolment = Enrolment.objects.filter(pk=enrolment_id).first()
    if enrolment is None:
        return {"status": "missing", "expires_at": ""}
    return {
        "status": enrolment.status,
        "expires_at": enrolment.hold_expires_at.isoformat() if enrolment.hold_expires_at else "",
    }


def _request_paid(enrolment: Enrolment) -> bool:
    from tutortrack.billing.models import PaymentRequest

    return bool(
        enrolment.payment_request_id
        and PaymentRequest.objects.filter(
            pk=enrolment.payment_request_id, status=PaymentRequest.Status.PAID
        ).exists()
    )


@transaction.atomic
def confirm_enrolment(enrolment_id: Any, *, user: Any = None) -> str:
    """The place was paid for (activity after ``payment_request.paid``): the student is
    enrolled, joins the sessions and the fees are invoiced (the payment is credit that
    settles them)."""
    enrolment = Enrolment.objects.select_for_update().filter(pk=enrolment_id).first()
    if enrolment is None:
        return "missing"
    if enrolment.status != Enrolment.Status.PENDING_PAYMENT:
        return enrolment.status
    with audit.track(enrolment, action="confirm"):
        enrolment.status = Enrolment.Status.ENROLLED
        enrolment.hold_expires_at = None
        enrolment.save(update_fields=["status", "hold_expires_at", "updated_at"])
    _activate(enrolment, user=user)
    _publish_confirmed(enrolment)
    return enrolment.status


def _publish_confirmed(enrolment: Enrolment) -> None:
    publish(
        events.EnrolmentConfirmed(
            subject_id=enrolment.pk,
            class_id=str(enrolment.group_class_id),
            student_id=str(enrolment.student_id),
            client_id=str(enrolment.client_id),
        ),
        branch_id=enrolment.branch_id,
    )


@transaction.atomic
def release_enrolment(enrolment_id: Any, *, reason: str = "unpaid") -> str:
    """A held place wasn't paid in time (activity) or was cancelled: release it. A payment
    that arrived anyway confirms the place instead."""
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import PaymentRequest

    enrolment = Enrolment.objects.select_for_update().filter(pk=enrolment_id).first()
    if enrolment is None or enrolment.status != Enrolment.Status.PENDING_PAYMENT:
        return enrolment.status if enrolment else "missing"
    if reason == "unpaid" and _request_paid(enrolment):
        return confirm_enrolment(enrolment.pk)  # paid, but the signal was missed
    if enrolment.payment_request_id:
        request = PaymentRequest.objects.filter(pk=enrolment.payment_request_id).first()
        if request is not None and request.status == PaymentRequest.Status.OPEN:
            try:
                with transaction.atomic():
                    billing.cancel_payment_request(request)
            except BusinessRuleViolation:
                pass  # part-paid: the office decides
    with audit.track(enrolment, action="release"):
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.withdrawn_at = now()
        enrolment.withdrawal_reason = reason[:300]
        enrolment.hold_expires_at = None
        enrolment.save()
    publish(
        events.EnrolmentReleased(
            subject_id=enrolment.pk,
            class_id=str(enrolment.group_class_id),
            student_id=str(enrolment.student_id),
            client_id=str(enrolment.client_id),
            reason=reason,
        ),
        branch_id=enrolment.branch_id,
    )
    group_class = enrolment.group_class
    _update_fullness(group_class)
    places_freed(group_class)
    return enrolment.status


@transaction.atomic
def cancel_pending(enrolment: Enrolment, *, user: Any = None) -> Enrolment:
    """The family (or staff) gave up a place held for payment."""
    if enrolment.status != Enrolment.Status.PENDING_PAYMENT:
        raise BusinessRuleViolation(_("Only places waiting for payment can be cancelled here."))
    release_enrolment(enrolment.pk, reason="cancelled")
    enrolment.refresh_from_db()
    return enrolment


@transaction.atomic
def convert_trial(enrolment: Enrolment, *, user: Any = None) -> Enrolment:
    """A trial student stays: they become enrolled and are billed from today."""
    enrolment = Enrolment.objects.select_for_update().get(pk=enrolment.pk)
    if enrolment.status != Enrolment.Status.TRIAL:
        raise BusinessRuleViolation(_("This enrolment isn't a trial."))
    group_class = enrolment.group_class
    start = max(enrolment.start_date, local_today(group_class))
    with audit.track(enrolment, action="convert"):
        enrolment.price_snapshot = quote(group_class, student=enrolment.student, start_date=start)
        enrolment.fee = _m(enrolment.price_snapshot["price"], enrolment.currency)
        enrolment.status = Enrolment.Status.ENROLLED
        enrolment.save()
    _activate(enrolment, user=user)
    _publish_confirmed(enrolment)
    return enrolment


def _settle_leaving(
    enrolment: Enrolment, effective: date, *, refund: bool, reason: str, user: Any
) -> Money:
    """Billing when a student leaves on ``effective`` (their first day away): fees are cut
    to the share of the units they had (credit notes for anything already invoiced); a
    monthly plan ends the day before. Registration and materials fees stay."""
    from tutortrack.billing import plans
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import BillingPlan

    group_class = enrolment.group_class
    course = group_class.course
    zero = Money.zero(course.currency)
    if enrolment.billed_at is None:
        return zero
    model = course.pricing_model
    if model in FEE_MODELS and refund:
        fee_due = _m(enrolment.price_snapshot.get("fee_due"), course.currency)
        _t1, from_start, _b1 = units(group_class, enrolment.start_date)
        _t2, from_effective, _b2 = units(group_class, effective)
        used = max(from_start - from_effective, 0)
        keep = pricing.prorate(fee_due, total=from_start, remaining=used) if from_start else fee_due
        return billing.adjust_fee(
            source_key=fee_key(enrolment),
            keep=keep,
            reason=reason or _("Left the class"),
            client=enrolment.client,
            student=enrolment.student,
            user=user,
        )
    if model == Course.PricingModel.PER_MONTH and enrolment.billing_plan_id:
        plan = BillingPlan.objects.filter(pk=enrolment.billing_plan_id).first()
        if plan is not None and plan.status != BillingPlan.Status.ENDED:
            if effective <= plan.start_date:
                plans.set_plan_status(plan, BillingPlan.Status.ENDED, user=user)
            elif plan.end_date is None or plan.end_date >= effective:
                plans.update_plan(plan, end_date=effective - timedelta(days=1), user=user)
    return zero


@transaction.atomic
def withdraw(
    enrolment: Enrolment,
    *,
    effective: date | None = None,
    reason: str = "",
    refund: bool | None = None,
    user: Any = None,
    fill: bool = True,
) -> Enrolment:
    """The student leaves from ``effective`` (default today): they come off the sessions
    from then, fees follow the refund policy (setting; ``refund`` overrides) and the place
    is offered to the waitlist."""
    enrolment = Enrolment.objects.select_for_update().get(pk=enrolment.pk)
    if enrolment.status == Enrolment.Status.PENDING_PAYMENT:
        release_enrolment(enrolment.pk, reason="withdrawn")
        enrolment.refresh_from_db()
        return enrolment
    if enrolment.status not in Enrolment.ATTENDING:
        raise BusinessRuleViolation(_("This student isn't in the class."))
    group_class = enrolment.group_class
    effective = effective or local_today(group_class)
    if effective < enrolment.start_date:
        effective = enrolment.start_date
    refund = refund if refund is not None else _setting("withdrawal_refund") == "unused_sessions"
    credited = _settle_leaving(enrolment, effective, refund=refund, reason=reason, user=user)
    with audit.track(enrolment, action="withdraw"):
        enrolment.status = Enrolment.Status.WITHDRAWN
        enrolment.end_date = effective - timedelta(days=1)
        enrolment.withdrawn_at = now()
        enrolment.withdrawal_reason = reason[:300]
        enrolment.save()
    sync_class_roster(group_class)
    publish(
        events.EnrolmentWithdrawn(
            subject_id=enrolment.pk,
            class_id=str(group_class.pk),
            student_id=str(enrolment.student_id),
            client_id=str(enrolment.client_id),
            effective_date=effective.isoformat(),
            reason=reason,
            credited=credited.to_dict() if credited.is_positive() else None,
        ),
        branch_id=enrolment.branch_id,
    )
    if fill:
        _update_fullness(group_class)
        _check_minimum(group_class)
        places_freed(group_class)
    return enrolment


@transaction.atomic
def transfer(
    enrolment: Enrolment,
    to_class: GroupClass,
    *,
    effective: date | None = None,
    reason: str = "",
    override_capacity: bool = False,
    user: Any = None,
) -> EnrolmentTransfer:
    """Move a student to another class from ``effective``: the old fee is cut to the
    sessions they had (credited) and the new class charges its prorated fee, so families
    pay only the difference; one-off fees aren't charged again."""
    enrolment = Enrolment.objects.select_for_update().get(pk=enrolment.pk)
    if enrolment.status not in Enrolment.ATTENDING:
        raise BusinessRuleViolation(_("Only enrolled students can be transferred."))
    if to_class.pk == enrolment.group_class_id:
        raise _invalid("to_class", _("Choose a different class."))
    for gc in sorted([enrolment.group_class, to_class], key=lambda c: str(c.pk)):
        _lock_class(gc)
    from_class = enrolment.group_class
    start = effective or max(local_today(to_class), to_class.start_date)
    trial = enrolment.status == Enrolment.Status.TRIAL
    new = enrol(
        to_class,
        enrolment.student,
        start_date=start,
        trial=trial,
        source=Enrolment.Source.TRANSFER,
        override_capacity=override_capacity,
        check_eligibility=False,
        with_fees=to_class.course_id != from_class.course_id,
        user=user,
    )
    leaving = max(start, enrolment.start_date)
    credited = _settle_leaving(
        enrolment, leaving, refund=True, reason=reason or _("Transferred"), user=user
    )
    with audit.track(enrolment, action="transfer"):
        enrolment.status = Enrolment.Status.TRANSFERRED
        enrolment.end_date = leaving - timedelta(days=1)
        enrolment.withdrawn_at = now()
        enrolment.withdrawal_reason = reason[:300]
        enrolment.save()
    record = EnrolmentTransfer.objects.create(
        from_enrolment=enrolment,
        to_enrolment=new,
        effective_date=start,
        reason=reason[:300],
        adjustment={
            "credited": credited.to_dict(),
            "charged": new.price_snapshot.get("fee_due"),
        },
        requested_by=user if getattr(user, "is_authenticated", False) else None,
    )
    audit.record_create(record)
    sync_class_roster(from_class)
    publish(
        events.EnrolmentTransferred(
            subject_id=enrolment.pk,
            class_id=str(from_class.pk),
            student_id=str(enrolment.student_id),
            client_id=str(enrolment.client_id),
            to_class_id=str(to_class.pk),
            to_enrolment_id=str(new.pk),
            effective_date=start.isoformat(),
        ),
        branch_id=enrolment.branch_id,
    )
    _update_fullness(from_class)
    _check_minimum(from_class)
    places_freed(from_class)
    return record


# --- waitlist (T06) -----------------------------------------------------------------------------


@transaction.atomic
def join_waitlist(group_class: GroupClass, student: Student, *, notes: str = "") -> Any:
    from tutortrack.leads import services as leads

    if not group_class.waitlist_enabled:
        raise BusinessRuleViolation(_("This class doesn't keep a waitlist."))
    if group_class.status not in (GroupClass.Status.DRAFT, *GroupClass.ENROLLABLE):
        raise BusinessRuleViolation(_("This class isn't taking enrolments."))
    if Enrolment.objects.filter(
        group_class=group_class, student=student, status__in=Enrolment.ACTIVE
    ).exists():
        raise _invalid(
            "student", _("%(name)s is already in this class.") % {"name": student.full_name}
        )
    entry = leads.add_to_waitlist(
        student=student,
        subject=group_class.course.name,
        service=group_class.course.service,
        notes=notes,
        group_class_id=group_class.pk,
    )
    return entry


def _offer_details(group_class: GroupClass) -> str:
    start = group_class.start_time.strftime("%H:%M")
    return f"{group_class.course.name}: {group_class.name} ({start}, {group_class.term.name})"


@transaction.atomic
def fill_vacancies(group_class_id: Any) -> int:
    """Offer free places to the class's waitlist, oldest first (FR-20-5); each offer is
    time-limited by E17's ``WaitlistOfferWorkflow``. Returns the offers made."""
    from tutortrack.leads import services as leads

    group_class = (
        GroupClass.objects.select_for_update()
        .select_related("course", "term")
        .filter(pk=group_class_id)
        .first()
    )
    if (
        group_class is None
        or not group_class.waitlist_enabled
        or not _setting("waitlist_auto_offer")
        or group_class.status not in GroupClass.ENROLLABLE
        or local_today(group_class) > group_class.end_date
    ):
        return 0
    free = group_class.capacity - selectors.taken_places(group_class)
    offered = 0
    for entry in selectors.waiting(group_class).filter(status="waiting")[: max(free, 0)]:
        leads.offer_place(
            entry, details=_offer_details(group_class), hours=int(_setting("waitlist_offer_hours"))
        )
        offered += 1
    return offered


@transaction.atomic
def enrol_from_waitlist(entry_id: Any) -> Enrolment | None:
    """A family accepted a class place offered from the waitlist: enrol (or hold the
    place for payment, by the online payment setting)."""
    from tutortrack.leads.models import WaitlistEntry

    entry = WaitlistEntry.objects.select_related("student").filter(pk=entry_id).first()
    if entry is None or not entry.group_class_id or entry.status != WaitlistEntry.Status.ACCEPTED:
        return None
    if Enrolment.objects.filter(waitlist_entry_id=entry.pk).exists():
        return None
    group_class = GroupClass.objects.filter(pk=entry.group_class_id).first()
    if group_class is None:
        return None
    payment = str(_setting("online_payment"))
    try:
        with transaction.atomic():
            return enrol(
                group_class,
                entry.student,
                source=Enrolment.Source.WAITLIST,
                payment=payment if payment != "none" else Enrolment.Payment.NONE,
                waitlist_entry_id=entry.pk,
                check_eligibility=False,
                accept_terms=True,
            )
    except BusinessRuleViolation:
        return None  # e.g. the class was cancelled meanwhile; staff see the entry


# --- registers and makeups (T07) ----------------------------------------------------------------


@transaction.atomic
def mark_register(
    session: ClassSession, rows: list[dict[str, Any]], *, user: Any = None
) -> ClassSession:
    """Take the register (FR-20-6): one outcome per student (E09 attendance, so the
    cancellation policy, charges and tutor pay follow), with optional absence reasons.
    A planned session is completed; a completed one has its attendance corrected."""
    from tutortrack.delivery import services as delivery
    from tutortrack.scheduling.models import Lesson

    lesson = Lesson.objects.get(pk=session.lesson_id)
    by_student = {str(a.student_id): a for a in lesson.attendees.all()}
    attendance = []
    reasons = dict(session.absence_reasons or {})
    for row in rows:
        attendee = by_student.get(str(row["student"]))
        if attendee is None:
            raise _invalid("rows", _("That student isn't in this session."))
        attendance.append(
            delivery.AttendanceRow(attendee.pk, row["outcome"], row.get("late_minutes"))
        )
        reason = str(row.get("absence_reason") or "").strip()[:200]
        if reason and row["outcome"] not in ("present", "late"):
            reasons[str(row["student"])] = reason
        else:
            reasons.pop(str(row["student"]), None)
    if lesson.status == Lesson.Status.PLANNED:
        delivery.complete_lesson(lesson, user=user, attendance=attendance)
    elif lesson.status == Lesson.Status.COMPLETED:
        delivery.record_attendance(lesson, attendance, user=user)
    else:
        raise BusinessRuleViolation(_("This session was cancelled."))
    session.absence_reasons = reasons
    session.save(update_fields=["absence_reasons", "updated_at"])
    audit.record(session, "register", {"rows": [None, str(len(rows))]})
    return session


@transaction.atomic
def book_makeup(
    session: ClassSession,
    student: Student,
    *,
    credit: Any = None,
    from_session: ClassSession | None = None,
    user: Any = None,
) -> MakeupBooking:
    """A makeup in another class of the same course, if it has room (FR-20-6). Uses the
    student's makeup credit (E09), or issues one for the session they missed."""
    from tutortrack.delivery import services as delivery

    group_class = _lock_class(session.group_class)
    session = ClassSession.objects.select_related("lesson").get(pk=session.pk)
    if session.lesson.status != "planned" or session.lesson.start < now():
        raise _invalid("session", _("Choose a session that hasn't happened yet."))
    if selectors.attending_on(group_class, session.date).filter(student=student).exists():
        raise _invalid("student", _("The student is already in this session."))
    source = from_session
    if credit is not None:
        source_lesson = credit.source_lesson
        source = ClassSession.objects.filter(lesson=source_lesson).first()
    if source is None:
        raise _invalid("from_session", _("Choose the session the student missed."))
    if source.group_class.course_id != group_class.course_id:
        raise _invalid("session", _("Makeups are in a class of the same course."))
    roster = len(_session_attendees(session))
    if roster >= group_class.capacity:
        raise ClassFull(_("That session is full."), extra={"code": "class_full"})
    if credit is None:
        attendee = source.lesson.attendees.filter(student=student).first()
        if attendee is None:
            raise _invalid("from_session", _("The student wasn't in that session."))
        credit = delivery.issue_makeup_credit(
            source.lesson, attendee, days=int(_setting("makeup_credit_days"))
        )
    elif str(credit.student_id) != str(student.pk):
        raise _invalid("credit", _("That credit belongs to another student."))
    booking = MakeupBooking.objects.create(
        session=session,
        student=student,
        client_id=student.client_id,
        from_session=source,
        makeup_credit_id=credit.pk,
    )
    audit.record_create(booking)
    sync_class_roster(group_class, sessions=[session])
    delivery.consume_makeup_credit(credit, session.lesson)
    return booking


@transaction.atomic
def cancel_makeup(booking: MakeupBooking, *, user: Any = None) -> MakeupBooking:
    if booking.status != MakeupBooking.Status.BOOKED:
        raise BusinessRuleViolation(_("This makeup isn't booked."))
    if booking.session.lesson.status != "planned":
        raise BusinessRuleViolation(_("The session has already happened."))
    with audit.track(booking, action="cancel"):
        booking.status = MakeupBooking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])
    sync_class_roster(booking.session.group_class, sessions=[booking.session])
    return booking


# --- term rollover (T08, TW1) -------------------------------------------------------------------


def _token(offer_id: Any) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), f"rollover-offer:{offer_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest[:24]).decode().rstrip("=")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _target(group_class: GroupClass, to_term: Term) -> GroupClass | None:
    if group_class.next_class_id:
        nxt = group_class.next_class
        if nxt is not None and nxt.term_id == to_term.pk and nxt.status != "cancelled":
            return nxt
    return (
        GroupClass.objects.filter(
            term=to_term, course_id=group_class.course_id, name__iexact=group_class.name
        )
        .exclude(status__in=[GroupClass.Status.CANCELLED, GroupClass.Status.COMPLETED])
        .first()
    )


@transaction.atomic
def start_rollover(
    from_term: Term,
    to_term: Term,
    *,
    mode: str = TermRollover.Mode.CONFIRM,
    deadline: datetime,
    user: Any = None,
) -> TermRollover:
    """Ask every family in ``from_term`` to keep their place next term (FR-20-4 roll
    over). Each class continues in its ``next_class`` (or the class of the same course and
    name in ``to_term``). ``TermRolloverWorkflow`` sends the requests and reminders and
    finishes at ``deadline``."""
    if from_term.pk == to_term.pk or to_term.start_date <= from_term.start_date:
        raise _invalid("to_term", _("Choose a later term."))
    if deadline <= now():
        raise _invalid("deadline", _("Choose a deadline in the future."))
    if mode not in TermRollover.Mode.values:
        raise _invalid("mode", _("Choose how families answer."))
    if TermRollover.objects.filter(from_term=from_term, status="running").exists():
        raise BusinessRuleViolation(_("A rollover for this term is already running."))
    rollover = TermRollover.objects.create(
        from_term=from_term,
        to_term=to_term,
        mode=mode,
        deadline=deadline,
        started_by=user if getattr(user, "is_authenticated", False) else None,
    )
    skipped = 0
    for enrolment in Enrolment.objects.filter(
        group_class__term=from_term,
        status__in=[Enrolment.Status.ENROLLED, Enrolment.Status.COMPLETED],
    ).select_related("group_class"):
        target = _target(enrolment.group_class, to_term)
        if (
            target is None
            or Enrolment.objects.filter(
                group_class=target, student_id=enrolment.student_id, status__in=Enrolment.ACTIVE
            ).exists()
        ):
            skipped += 1
            continue
        offer = RolloverOffer.objects.create(
            rollover=rollover,
            enrolment=enrolment,
            to_class=target,
            student_id=enrolment.student_id,
            client_id=enrolment.client_id,
        )
        offer.token_hash = _hash(_token(offer.pk))
        offer.save(update_fields=["token_hash", "updated_at"])
    from .processes import rollover_workflow_id

    rollover.workflow_id = rollover_workflow_id(rollover.organisation_id, rollover.pk)
    rollover.stats = {"offers": rollover.offers.count(), "skipped": skipped}
    rollover.save(update_fields=["workflow_id", "stats", "updated_at"])
    audit.record_create(rollover)
    publish(
        events.TermRolloverStarted(
            subject_id=rollover.pk,
            from_term_id=str(from_term.pk),
            to_term_id=str(to_term.pk),
            offers=rollover.stats["offers"],
            deadline=deadline.isoformat(),
        ),
        branch_id=from_term.branch_id,
    )
    return rollover


def rollover_state(rollover_id: Any) -> dict[str, Any]:
    rollover = TermRollover.objects.filter(pk=rollover_id).first()
    if rollover is None:
        return {"status": "missing", "deadline": "", "pending": 0}
    return {
        "status": rollover.status,
        "deadline": rollover.deadline.isoformat(),
        "pending": rollover.offers.filter(status=RolloverOffer.Status.PENDING).count(),
    }


def send_rollover_requests(rollover_id: Any, *, reminder: bool = False) -> int:
    """Email each family a confirm/opt-out link (activity); reminders go to families who
    haven't answered. Idempotent per offer and round (comms dedupes on the key)."""
    from tutortrack.comms import services as comms

    rollover = TermRollover.objects.filter(pk=rollover_id, status="running").first()
    if rollover is None:
        return 0
    sent = 0
    round_key = "reminder" if reminder else "invite"
    for offer in rollover.offers.filter(status=RolloverOffer.Status.PENDING):
        comms.notify(
            "term_rollover_invite",
            (offer.pk, _token(offer.pk), reminder),
            key=f"rollover:{offer.pk}:{round_key}",
        )
        if reminder:
            RolloverOffer.objects.filter(pk=offer.pk).update(reminded_at=now())
        sent += 1
    return sent


def offer_for_token(token: str) -> RolloverOffer:
    offer = (
        RolloverOffer.objects.select_related("rollover", "to_class__course", "student")
        .filter(token_hash=_hash(token))
        .first()
    )
    if offer is None:
        raise NotFound()
    return offer


@transaction.atomic
def respond_rollover(offer: RolloverOffer, *, confirm: bool, user: Any = None) -> RolloverOffer:
    offer = RolloverOffer.objects.select_for_update().select_related("rollover").get(pk=offer.pk)
    if offer.rollover.status != TermRollover.Status.RUNNING or offer.rollover.deadline <= now():
        raise BusinessRuleViolation(
            _("Re-enrolment for this term has closed. Please contact us."), extra={"code": "closed"}
        )
    if offer.status not in (
        RolloverOffer.Status.PENDING,
        RolloverOffer.Status.CONFIRMED,
        RolloverOffer.Status.DECLINED,
    ):
        raise BusinessRuleViolation(_("This place has already been settled."))
    with audit.track(offer, action="confirm" if confirm else "decline"):
        offer.status = RolloverOffer.Status.CONFIRMED if confirm else RolloverOffer.Status.DECLINED
        offer.responded_at = now()
        offer.save()
    publish(
        events.RolloverResponded(
            subject_id=offer.rollover_id, offer_id=str(offer.pk), confirmed=confirm
        )
    )
    return offer


@transaction.atomic
def finalise_rollover(rollover_id: Any) -> dict[str, int]:
    """The deadline passed (activity): enrol confirmed students (and, when places roll
    over unless families opt out, those who didn't answer), billing next term's fees;
    release the other places and offer them to the classes' waitlists."""
    rollover = TermRollover.objects.select_for_update().filter(pk=rollover_id).first()
    if rollover is None or rollover.status != TermRollover.Status.RUNNING:
        return dict(rollover.stats.get("result", {})) if rollover else {}
    keep = [RolloverOffer.Status.CONFIRMED]
    if rollover.mode == TermRollover.Mode.OPT_OUT:
        keep.append(RolloverOffer.Status.PENDING)
    enrolled = released = failed = 0
    targets: set[Any] = set()
    for offer in rollover.offers.select_related("to_class", "student").order_by("created_at"):
        targets.add(offer.to_class_id)
        if offer.status in keep:
            try:
                with transaction.atomic():
                    new = enrol(
                        offer.to_class,
                        offer.student,
                        source=Enrolment.Source.ROLLOVER,
                        start_date=offer.to_class.start_date,
                        check_eligibility=False,
                    )
                offer.status = RolloverOffer.Status.ENROLLED
                offer.new_enrolment = new
                enrolled += 1
            except BusinessRuleViolation as exc:
                offer.status = RolloverOffer.Status.FAILED
                offer.note = str(exc)[:300]
                failed += 1
        elif offer.status in (RolloverOffer.Status.PENDING, RolloverOffer.Status.DECLINED):
            offer.status = RolloverOffer.Status.RELEASED
            released += 1
        offer.save()
    result = {"enrolled": enrolled, "released": released, "failed": failed}
    with audit.track(rollover, action="finalise"):
        rollover.status = TermRollover.Status.FINALISED
        rollover.finalised_at = now()
        rollover.stats = {**rollover.stats, "result": result}
        rollover.save()
    publish(
        events.TermRolloverFinalised(subject_id=rollover.pk, enrolled=enrolled, released=released),
        branch_id=rollover.from_term.branch_id,
    )
    for class_id in targets:
        group_class = GroupClass.objects.filter(pk=class_id).first()
        if group_class is not None:
            places_freed(group_class)
    return result


@transaction.atomic
def finish_rollover_now(rollover: TermRollover, *, user: Any = None) -> TermRollover:
    from tutortrack.core.workflows import signal

    if rollover.status != TermRollover.Status.RUNNING:
        raise BusinessRuleViolation(_("This rollover has finished."))
    audit.record(rollover, "finish_now")
    signal(rollover.workflow_id, "finalise")
    return rollover


@transaction.atomic
def cancel_rollover(rollover: TermRollover, *, user: Any = None) -> TermRollover:
    from tutortrack.core.workflows import signal

    rollover = TermRollover.objects.select_for_update().get(pk=rollover.pk)
    if rollover.status != TermRollover.Status.RUNNING:
        raise BusinessRuleViolation(_("This rollover has finished."))
    with audit.track(rollover, action="cancel"):
        rollover.status = TermRollover.Status.CANCELLED
        rollover.save(update_fields=["status", "updated_at"])
    signal(rollover.workflow_id, "cancel")
    return rollover


# --- online enrolment (T09) ---------------------------------------------------------------------


@transaction.atomic
def public_enrol(
    group_class: GroupClass,
    *,
    contact: dict[str, Any],
    student: dict[str, Any],
    accept_terms: bool,
    payment: str | None = None,
    consents: list[str] | None = None,
) -> tuple[Enrolment, str]:
    """Enrol from the website catalogue (FR-20-8): eligibility is checked before a new
    family is created; the place is then taken under the class lock and, when payment is
    due at enrolment, held until it is paid. Returns the enrolment and a status token."""
    import secrets

    from tutortrack.people import services as people

    problems = eligibility_problems(
        group_class,
        date_of_birth=student.get("date_of_birth"),
        year_group=str(student.get("year_group") or ""),
    )
    if problems:
        raise NotEligible(problems[0], extra={"code": "not_eligible", "problems": problems})
    _client, person, created = people.quick_add_family(
        contact={
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
        },
        students=[
            {
                k: v
                for k, v in {
                    "first_name": student.get("first_name", ""),
                    "last_name": student.get("last_name") or contact.get("last_name", ""),
                    "date_of_birth": student.get("date_of_birth"),
                    "year_group": str(student.get("year_group") or "")[:40],
                }.items()
                if v not in (None, "")
            }
        ],
    )
    chosen = payment if payment is not None else str(_setting("online_payment"))
    enrolment = enrol(
        group_class,
        created[0],
        source=Enrolment.Source.PUBLIC,
        payment=chosen,
        accept_terms=accept_terms,
        check_eligibility=False,
    )
    token = secrets.token_urlsafe(24)
    enrolment.token_hash = _hash(token)
    enrolment.contact = {
        k: str(v)[:200]
        for k, v in contact.items()
        if k in ("first_name", "last_name", "email", "phone")
    }
    enrolment.save(update_fields=["token_hash", "contact", "updated_at"])
    capture_public_consent(
        group_class, person, created, accept_terms=accept_terms, consents=consents
    )
    return enrolment, token


def capture_public_consent(
    group_class: GroupClass,
    contact: Any,
    students: list[Any],
    *,
    accept_terms: bool,
    consents: list[str] | None = None,
) -> None:
    """G6 (FR-29-3): the enrolment terms and any consents ticked on the public enrolment
    (or waitlist) form become E29 consent records: ``terms`` for the parent, and each other
    key for whoever it applies to (photos and video for the child, given by the parent)."""
    from tutortrack.privacy.capture import record_ticked

    keys = (["terms"] if accept_terms else []) + list(consents or [])
    if not keys or contact is None:
        return
    record_ticked(
        people={
            "people.contact": [contact.pk],
            "people.student": [s.pk for s in students],
        },
        keys=keys,
        method="form",
        source=f"enrolment:{group_class.pk}",
        given_by_name=contact.full_name,
    )


def enrolment_for_token(token: str) -> Enrolment:
    enrolment = (
        Enrolment.objects.select_related("group_class__course", "student")
        .filter(token_hash=_hash(token))
        .first()
    )
    if enrolment is None or not token:
        raise NotFound()
    return enrolment


def pay_url(enrolment: Enrolment) -> str:
    """The pay page of a place held for payment."""
    from tutortrack.billing.models import PaymentRequest
    from tutortrack.payments.services import tenant_url

    if enrolment.status != Enrolment.Status.PENDING_PAYMENT or not enrolment.payment_request_id:
        return ""
    request = PaymentRequest.objects.filter(pk=enrolment.payment_request_id).first()
    return tenant_url(f"/pay/{request.pay_token}") if request and request.pay_token else ""
