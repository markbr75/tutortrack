"""Job writes (E07). Every mutation is audited and emits a domain event."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.catalogue.models import Level, Service, Subject
from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.money import Money
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.crm.custom_fields import clean_custom_fields
from tutortrack.people.models import Client, Student, TutorProfile

from . import events, lessons
from .models import Job, JobStatusHistory, JobStudent, JobTutor

S = Job.Status
TRANSITIONS: dict[str, set[str]] = {
    S.DRAFT: {S.SEEKING_TUTOR, S.ACTIVE, S.CANCELLED},
    S.SEEKING_TUTOR: {S.DRAFT, S.ACTIVE, S.CANCELLED},
    S.ACTIVE: {S.SEEKING_TUTOR, S.PAUSED, S.COMPLETED, S.CANCELLED},
    S.PAUSED: {S.ACTIVE, S.COMPLETED, S.CANCELLED},
    S.COMPLETED: {S.ACTIVE},  # reopen
    S.CANCELLED: set(),
}
CURRENT = (JobTutor.Status.OFFERED, JobTutor.Status.ACTIVE)
EDITABLE = {
    "name", "bill_to", "subject", "level", "charge_rate", "billing_method", "package_template",
    "po_number", "default_duration_minutes", "location", "online", "meeting_provider",
    "default_schedule", "start_date", "expected_end_date", "lessons_per_week",
    "expected_total_hours", "goals", "notes_internal", "notes_for_tutor", "notes_for_client",
    "account_manager", "hours_cap", "hours_cap_period", "policy_overrides", "custom_fields",
    "branch",
}  # fmt: skip


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def _check_rate(field: str, value: Money | None, currency: str) -> None:
    if value is None:
        return
    if value.currency != currency:
        raise _invalid(field, _("Use %(currency)s, the job's currency.") % {"currency": currency})
    if value.is_negative():
        raise _invalid(field, _("Rates can't be negative."))


def _validate(job: Job) -> None:
    if job.client.archived_at is not None:
        raise _invalid("client", _("The client is archived."))
    if job.bill_to_id is not None:
        if job.bill_to_id == job.client_id:
            job.bill_to = None
        elif job.bill_to is not None and job.bill_to.archived_at is not None:
            raise _invalid("bill_to", _("The paying client is archived."))
    if job.level is not None and job.subject is not None and job.level.subject_id != job.subject_id:
        raise _invalid("level", _("Choose a level of the job's subject."))
    if job.location is not None and job.location.archived_at is not None:
        raise _invalid("location", _("This location is archived."))
    if job.start_date and job.expected_end_date and job.expected_end_date < job.start_date:
        raise _invalid("expected_end_date", _("The end date is before the start date."))
    if job.hours_cap is not None and job.hours_cap <= 0:
        raise _invalid("hours_cap", _("The cap must be more than zero hours."))
    _check_rate("charge_rate", job.charge_rate, job.currency)
    job.default_schedule = _clean_schedule(job.default_schedule)


def _clean_schedule(value: Any) -> list[dict[str, Any]]:
    """``[{"weekday": 0-6 (Monday=0), "time": "HH:MM", "duration_minutes"?: int}]``."""
    if not value:
        return []
    if not isinstance(value, list) or len(value) > 14:
        raise _invalid("default_schedule", _("Give up to 14 weekly slots."))
    out = []
    for slot in value:
        try:
            weekday = int(slot["weekday"])
            hh, mm = str(slot["time"]).split(":")
            hour, minute = int(hh), int(mm)
            duration = int(slot.get("duration_minutes") or 0) or None
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid("default_schedule", _("Each slot needs a weekday and a time.")) from exc
        if not (0 <= weekday <= 6 and 0 <= hour <= 23 and 0 <= minute <= 59):
            raise _invalid("default_schedule", _("Each slot needs a weekday and a time."))
        slot_out: dict[str, Any] = {"weekday": weekday, "time": f"{hour:02d}:{minute:02d}"}
        if duration:
            slot_out["duration_minutes"] = duration
        out.append(slot_out)
    return sorted(out, key=lambda s: (s["weekday"], s["time"]))


def default_name(
    service: Service, subject: Subject | None, level: Level | None, students: list[Student]
) -> str:
    label = " ".join(
        p for p in ((level.name if level else ""), (subject.name if subject else "")) if p
    )
    names = ", ".join(s.full_name for s in students[:3]) + ("…" if len(students) > 3 else "")
    return f"{label or service.name} \u2013 {names}"[:200]  # en dash, as in the spec


def _record_status(job: Job, old: str, new: str, reason: str = "") -> None:
    JobStatusHistory.objects.create(job=job, from_status=old, to_status=new, reason=reason[:300])


# --- creation -----------------------------------------------------------------------------------


@transaction.atomic
def create_job(
    *,
    client: Client,
    service: Service,
    students: Iterable[dict[str, Any]],
    tutors: Iterable[dict[str, Any]] = (),
    status: str = S.DRAFT,
    custom_fields: dict[str, Any] | None = None,
    **fields: Any,
) -> Job:
    unknown = set(fields) - EDITABLE
    if unknown:
        raise BusinessRuleViolation(f"Unknown job fields: {', '.join(sorted(unknown))}")
    if not service.active:
        raise _invalid("service", _("This service is inactive."))
    student_rows = list(students)
    if not student_rows:
        raise _invalid("students", _("Add at least one student."))
    charge_rate: Money | None = fields.pop("charge_rate", None)
    subject = fields.pop("subject", None)
    level = fields.pop("level", None)
    if subject is None and level is None:
        subject, level = service.subject, service.level
    elif subject is None and level is not None:
        subject = level.subject
    job = Job(
        client=client,
        service=service,
        branch=fields.pop("branch", None) or client.branch,
        subject=subject,
        level=level,
        currency=charge_rate.currency if charge_rate else service.currency,
        default_duration_minutes=fields.pop("default_duration_minutes", None)
        or service.default_duration_minutes,
        **{k: v for k, v in fields.items() if k != "name"},
    )
    job.charge_rate = charge_rate
    job.custom_fields = clean_custom_fields("jobs.job", custom_fields, None, creating=True)
    _validate(job)
    job.reference = next_number("job", prefix="JOB-")
    job.name = "pending"
    job.save()
    for row in student_rows:
        add_student(job, **row, _initial=True)
    job.name = (fields.get("name") or "").strip() or default_name(
        service,
        job.subject,
        job.level,
        [js.student for js in job.students.select_related("student")],
    )
    job.save(update_fields=["name"])
    _record_status(job, "", job.status)
    audit.record_create(job)
    publish(
        events.JobCreated(
            subject_id=job.pk, reference=job.reference, client_id=str(client.pk), status=job.status
        ),
        branch_id=job.branch_id,
    )
    for row in tutors:
        add_tutor(job, **row)
    if status != job.status:
        change_status(job, status)
    return job


@transaction.atomic
def update_job(job: Job, **changes: Any) -> Job:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise BusinessRuleViolation(f"Unknown job fields: {', '.join(sorted(unknown))}")
    if job.status == S.CANCELLED:
        raise BusinessRuleViolation(_("Cancelled jobs can't be changed."))
    if "custom_fields" in changes:
        changes["custom_fields"] = clean_custom_fields(
            "jobs.job", changes["custom_fields"], job.custom_fields, creating=False
        )
    changed = [k for k, v in changes.items() if getattr(job, k) != v]
    with audit.track(job):
        for k, v in changes.items():
            setattr(job, k, v)
        _validate(job)
        job.save()
    if changed:
        publish(
            events.JobUpdated(subject_id=job.pk, fields=sorted(changed)), branch_id=job.branch_id
        )
    return job


@transaction.atomic
def duplicate_job(job: Job, *, start_date: date | None = None) -> Job:
    """Copy a job (e.g. for a new academic year) as a draft with the same students and tutors."""
    copy = create_job(
        client=job.client,
        service=job.service,
        students=[
            {"student": js.student, "charge_rate_override": js.charge_rate_override}
            for js in job.students.filter(active_to__isnull=True).select_related("student")
        ],
        tutors=[
            {
                "tutor": jt.tutor,
                "role": jt.role,
                "pay_rate_override": jt.pay_rate_override,
                "offer": True,
            }
            for jt in job.tutors.filter(status=JobTutor.Status.ACTIVE).select_related("tutor")
        ],
        **{
            k: getattr(job, k)
            for k in EDITABLE - {"custom_fields", "start_date", "expected_end_date", "name"}
        },
        name=job.name,
        start_date=start_date,
        custom_fields=job.custom_fields,
    )
    audit.record(copy, "duplicate", {"source": [None, job.reference]})
    return copy


# --- students -----------------------------------------------------------------------------------


@transaction.atomic
def add_student(
    job: Job,
    *,
    student: Student,
    charge_rate_override: Money | None = None,
    active_from: date | None = None,
    _initial: bool = False,
) -> JobStudent:
    if student.client_id != job.client_id:
        raise _invalid("students", _("Students must belong to the job's client."))
    if student.archived_at is not None:
        raise _invalid("students", _("%(name)s is archived.") % {"name": student.full_name})
    current = job.students.filter(active_to__isnull=True)
    if current.filter(student=student).exists():
        raise _invalid(
            "students", _("%(name)s is already on this job.") % {"name": student.full_name}
        )
    if current.count() >= job.service.max_students:
        raise _invalid(
            "students",
            _("%(service)s takes at most %(n)s students.")
            % {"service": job.service.name, "n": job.service.max_students},
        )
    _check_rate("charge_rate_override", charge_rate_override, job.currency)
    link = JobStudent(job=job, student=student, currency=job.currency, active_from=active_from)
    link.charge_rate_override = charge_rate_override
    JobStudent.objects.filter(job=job, student=student).delete()  # re-adding after leaving
    link.save()
    if not _initial:
        audit.record(job, "add_student", {"student": [None, str(student.pk)]})
        publish(events.JobUpdated(subject_id=job.pk, fields=["students"]), branch_id=job.branch_id)
    return link


@transaction.atomic
def end_student(link: JobStudent, *, active_to: date | None = None) -> JobStudent:
    job = link.job
    if job.students.filter(active_to__isnull=True).exclude(pk=link.pk).count() == 0:
        raise _invalid("students", _("A job needs at least one student; complete it instead."))
    with audit.track(link, action="end"):
        link.active_to = active_to or now().date()
        link.save(update_fields=["active_to", "updated_at"])
    publish(events.JobUpdated(subject_id=job.pk, fields=["students"]), branch_id=job.branch_id)
    return link


@transaction.atomic
def set_student_rate(link: JobStudent, rate: Money | None) -> JobStudent:
    _check_rate("charge_rate_override", rate, link.job.currency)
    with audit.track(link):
        link.charge_rate_override = rate
        link.save()
    publish(events.JobUpdated(subject_id=link.job_id, fields=["charge_rate"]))
    return link


# --- tutors -------------------------------------------------------------------------------------


def _check_tutor(job: Job, tutor: TutorProfile) -> None:
    from tutortrack.people.assignability import check_assignable

    check_assignable(tutor, "tutor")
    branches = set(tutor.branches.values_list("pk", flat=True))
    if branches and job.branch_id not in branches:
        raise _invalid(
            "tutor", _("%(name)s doesn't work in this branch.") % {"name": tutor.full_name}
        )


@transaction.atomic
def add_tutor(
    job: Job,
    *,
    tutor: TutorProfile,
    role: str = JobTutor.Role.LEAD,
    pay_rate_override: Money | None = None,
    start_date: date | None = None,
    offer: bool = False,
) -> JobTutor:
    """Assign a tutor, or offer the job to them when ``offer`` (they accept or decline)."""
    if job.status in {S.COMPLETED, S.CANCELLED}:
        raise BusinessRuleViolation(_("The job is closed."))
    _check_tutor(job, tutor)
    if job.tutors.filter(tutor=tutor, status__in=CURRENT).exists():
        raise _invalid("tutor", _("%(name)s is already on this job.") % {"name": tutor.full_name})
    _check_rate("pay_rate_override", pay_rate_override, job.currency)
    link = JobTutor(
        job=job,
        tutor=tutor,
        role=role,
        currency=job.currency,
        start_date=start_date,
        status=JobTutor.Status.OFFERED if offer else JobTutor.Status.ACTIVE,
    )
    link.pay_rate_override = pay_rate_override
    link.save()
    audit.record_create(link)
    publish(
        events.JobTutorAssigned(
            subject_id=job.pk, tutor_id=str(tutor.pk), role=role, offered=offer
        ),
        branch_id=job.branch_id,
    )
    if not offer and job.status == S.SEEKING_TUTOR:
        change_status(job, S.ACTIVE, reason=_("Tutor assigned"))
    return link


@transaction.atomic
def respond_to_offer(link: JobTutor, *, accept: bool) -> JobTutor:
    if link.status != JobTutor.Status.OFFERED:
        raise BusinessRuleViolation(_("This offer has already been answered."))
    with audit.track(link, action="accept" if accept else "decline"):
        link.status = JobTutor.Status.ACTIVE if accept else JobTutor.Status.DECLINED
        link.responded_at = now()
        link.save(update_fields=["status", "responded_at", "updated_at"])
    job = link.job
    if accept and job.status == S.SEEKING_TUTOR:
        change_status(job, S.ACTIVE, reason=_("Tutor accepted"))
    return link


@transaction.atomic
def remove_tutor(link: JobTutor, *, end_date: date | None = None, reason: str = "") -> JobTutor:
    if link.status not in CURRENT:
        raise BusinessRuleViolation(_("This tutor is no longer on the job."))
    with audit.track(link, action="remove"):
        link.status = JobTutor.Status.ENDED
        link.end_date = end_date or now().date()
        link.save(update_fields=["status", "end_date", "updated_at"])
    job = link.job
    publish(
        events.JobTutorRemoved(
            subject_id=job.pk, tutor_id=str(link.tutor_id), end_date=link.end_date.isoformat()
        ),
        branch_id=job.branch_id,
    )
    if job.status == S.ACTIVE and not job.tutors.filter(status=JobTutor.Status.ACTIVE).exists():
        change_status(job, S.SEEKING_TUTOR, reason=reason or _("No tutor left on the job"))
    return link


@dataclass
class Replacement:
    preview: lessons.ReplacementPreview
    new_link: JobTutor | None = None


@transaction.atomic
def replace_tutor(
    link: JobTutor,
    *,
    new_tutor: TutorProfile,
    effective_date: date,
    pay_rate_override: Money | None = None,
    dry_run: bool = False,
) -> Replacement:
    """Hand the job to another tutor from ``effective_date``. ``dry_run`` only previews the
    future lessons that would move (and any clashes for the new tutor)."""
    job = link.job
    if link.status != JobTutor.Status.ACTIVE:
        raise BusinessRuleViolation(_("Only an active tutor can be replaced."))
    if new_tutor.pk == link.tutor_id:
        raise _invalid("tutor", _("Choose a different tutor."))
    _check_tutor(job, new_tutor)
    preview = lessons.ReplacementPreview(
        lessons.provider().future_lessons(job, link.tutor, effective_date, new_tutor)
    )
    if dry_run:
        return Replacement(preview)
    old_tutor_id = str(link.tutor_id)
    with audit.track(link, action="replace"):
        link.status = JobTutor.Status.ENDED
        link.end_date = effective_date - timedelta(days=1)
        link.save(update_fields=["status", "end_date", "updated_at"])
    _check_rate("pay_rate_override", pay_rate_override, job.currency)
    new_link = JobTutor(
        job=job, tutor=new_tutor, role=link.role, currency=job.currency, start_date=effective_date
    )
    new_link.pay_rate_override = pay_rate_override
    new_link.save()
    audit.record_create(new_link)
    publish(
        events.JobTutorReplaced(
            subject_id=job.pk,
            old_tutor_id=old_tutor_id,
            new_tutor_id=str(new_tutor.pk),
            effective_date=effective_date.isoformat(),
        ),
        branch_id=job.branch_id,
    )
    return Replacement(preview, new_link)


@transaction.atomic
def set_tutor_rate(link: JobTutor, rate: Money | None) -> JobTutor:
    _check_rate("pay_rate_override", rate, link.job.currency)
    with audit.track(link):
        link.pay_rate_override = rate
        link.save()
    publish(events.JobUpdated(subject_id=link.job_id, fields=["pay_rate"]))
    return link


# --- status -------------------------------------------------------------------------------------


@transaction.atomic
def change_status(job: Job, status: str, *, reason: str = "", future_lessons: str = "keep") -> Job:
    """Move a job through its lifecycle (FR-07-4). Pausing, completing and cancelling ask E08
    what to do with future lessons (``keep`` or ``cancel``); completing/cancelling cancels
    them always."""
    old = job.status
    if status == old:
        return job
    if status not in TRANSITIONS.get(old, set()):
        raise BusinessRuleViolation(
            _("A %(old)s job can't become %(new)s.")
            % {"old": job.get_status_display().lower(), "new": S(status).label.lower()}
        )
    if status == S.ACTIVE and not job.tutors.filter(status=JobTutor.Status.ACTIVE).exists():
        raise _invalid("status", _("Assign a tutor before activating the job."))
    if status in {S.COMPLETED, S.CANCELLED}:
        future_lessons = "cancel"
        job.tutors.filter(status=JobTutor.Status.OFFERED).update(
            status=JobTutor.Status.DECLINED, responded_at=now()
        )
    with audit.track(job, action="status"):
        job.status = status
        job.status_changed_at = now()
        job.save(update_fields=["status", "status_changed_at", "updated_at"])
    _record_status(job, old, status, reason)
    publish(
        events.JobStatusChanged(
            subject_id=job.pk,
            from_status=old,
            to_status=status,
            reason=reason,
            future_lessons=future_lessons if future_lessons in {"keep", "cancel"} else "keep",
        ),
        branch_id=job.branch_id,
    )
    return job


# --- hours cap (FR-07-5) ------------------------------------------------------------------------


@dataclass
class HoursCheck:
    level: str  # "ok" | "warning" | "blocked" | "none"
    used: Decimal
    cap: Decimal | None
    period_start: date | None = None
    period_end: date | None = None


def cap_period(job: Job, on: date) -> tuple[date | None, date | None]:
    if job.hours_cap_period == Job.CapPeriod.WEEK:
        start = on - timedelta(days=on.weekday())
        return start, start + timedelta(days=6)
    if job.hours_cap_period == Job.CapPeriod.MONTH:
        last = calendar.monthrange(on.year, on.month)[1]
        return on.replace(day=1), on.replace(day=last)
    return None, None


def check_hours(
    job: Job, *, extra_hours: Decimal = Decimal(0), on: date | None = None
) -> HoursCheck:
    """Whether adding ``extra_hours`` on ``on`` stays within the job's cap: warn at 80%,
    block at 100% (or only warn, per the ``jobs.block_at_hours_cap`` setting)."""
    from tutortrack.tenancy.settings_service import get_setting

    if job.hours_cap is None:
        return HoursCheck("none", Decimal(0), None)
    start, end = cap_period(job, on or now().date())
    used = lessons.provider().hours_scheduled(job, start, end) + extra_hours
    level = "ok"
    if used > job.hours_cap:
        level = "blocked" if get_setting("jobs.block_at_hours_cap") else "warning"
    elif used >= job.hours_cap * Decimal("0.8"):
        level = "warning"
    return HoursCheck(level, used, job.hours_cap, start, end)


def notify_hours(job: Job, check: HoursCheck) -> None:
    """Emit ``job.hours_cap_reached`` (once per period and level) for E13 notifications."""
    if check.level not in {"warning", "blocked"} or check.cap is None:
        return
    level = "reached" if check.used >= check.cap else "warning"
    publish(
        events.JobHoursCapReached(
            subject_id=job.pk, used_hours=str(check.used), cap_hours=str(check.cap), level=level
        ),
        dedupe_key=f"job-cap:{job.pk}:{check.period_start}:{level}",
    )


# --- quick setup (FR-07-2) ----------------------------------------------------------------------


@transaction.atomic
def quick_setup(
    *,
    student: Student,
    service: Service,
    tutor: TutorProfile | None = None,
    charge_rate: Money | None = None,
    pay_rate: Money | None = None,
    schedule: list[dict[str, Any]] | None = None,
    start_date: date | None = None,
    default_duration_minutes: int | None = None,
    **fields: Any,
) -> Job:
    """ "Set up lessons" from a student: the job is active with a tutor, otherwise seeking one.
    The weekly schedule is saved on the job; E08 creates the lesson series from it."""
    return create_job(
        client=student.client,
        service=service,
        students=[{"student": student}],
        tutors=[{"tutor": tutor, "pay_rate_override": pay_rate}] if tutor else [],
        status=S.ACTIVE if tutor else S.SEEKING_TUTOR,
        charge_rate=charge_rate,
        default_schedule=schedule or [],
        start_date=start_date or now().date(),
        default_duration_minutes=default_duration_minutes,
        **fields,
    )
