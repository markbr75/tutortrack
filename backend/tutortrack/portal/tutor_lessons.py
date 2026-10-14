"""Tutor app: planning lessons, the previous report and a student's lesson history (G4,
FR-16-2/3/4).

* **Create** (``scheduling.lesson.create``, the Tutor role gets it with the
  ``tutor_access.create_lessons`` toggle): a lesson on one of the tutor's own active jobs,
  with the tutor as its only tutor, through ``scheduling.services.create_lesson``.
* **Move** (``scheduling.lesson.reschedule``, on by default for tutors): their own
  planned lesson, through ``scheduling.services.update_lesson`` (notifications and
  re-pricing as for the office). Without the permission the app asks through the
  existing reschedule-request API (``/lessons/{id}/reschedule-requests``).
* **Conflict feedback:** ``check`` dry-runs the E08 conflict engine for the proposed time
  (the tutor, the job's students, the place); hard conflicts also stop create and move
  (422 with the conflicts). Tutors can't override conflicts.
* **Reads** are limited by ``scope_queryset`` (``own`` for tutors): the lessons they teach
  and the reports they wrote.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, NotFound, PermissionDenied
from tutortrack.core.permissions import has_perm, scope_queryset
from tutortrack.people.models import TutorProfile

HISTORY_LIMIT = 200


def _jobs(tutor: TutorProfile) -> Any:
    from tutortrack.jobs.models import Job, JobTutor

    links = JobTutor.objects.filter(tutor=tutor, status=JobTutor.Status.ACTIVE)
    return Job.objects.filter(
        pk__in=links.values("job_id"), status__in=[Job.Status.ACTIVE, Job.Status.SEEKING_TUTOR]
    )


def bookable_jobs(tutor: TutorProfile) -> list[dict[str, Any]]:
    """The tutor's active jobs a new lesson can be booked on."""
    out = []
    for job in (
        _jobs(tutor).select_related("service", "location").prefetch_related("students__student")
    ):
        students = [s.student for s in job.students.all() if s.active_to is None]
        out.append(
            {
                "id": str(job.pk),
                "name": job.name,
                "service": job.service.name,
                "duration_minutes": job.service.default_duration_minutes,
                "online": bool(job.online),
                "location": job.location.name if job.location else "",
                "students": [{"id": str(s.pk), "name": s.full_name} for s in students],
            }
        )
    return sorted(out, key=lambda row: row["name"])


def _job(tutor: TutorProfile, job_id: Any) -> Any:
    job = _jobs(tutor).select_related("service", "branch").filter(pk=job_id).first()
    if job is None:
        raise NotFound(_("That job isn't one of yours."))
    return job


def _own_lesson(user: Any, lesson_id: Any) -> Any:
    from tutortrack.scheduling.models import Lesson

    visible = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.view")
    lesson = visible.filter(pk=lesson_id).prefetch_related("attendees__student").first()
    if lesson is None:
        raise NotFound()
    return lesson


def check(
    user: Any,
    tutor: TutorProfile,
    *,
    start: datetime,
    end: datetime,
    job_id: Any = None,
    lesson_id: Any = None,
) -> list[dict[str, Any]]:
    """The conflicts a lesson at ``start``-``end`` would have (nothing is saved)."""
    from tutortrack.scheduling import conflicts

    if lesson_id:
        lesson = _own_lesson(user, lesson_id)
        students = [a.student for a in lesson.attendees.all()]
        found = conflicts.check(
            start=start,
            end=end,
            tz=lesson.timezone,
            tutors=[tutor],
            students=students,
            exclude_lesson_ids=[lesson.pk],
            location=lesson.location,
            online=lesson.online,
            job=lesson.job,
            room=lesson.room,
        )
    else:
        if not job_id:
            raise BusinessRuleViolation(_("Choose a job."))
        job = _job(tutor, job_id)
        students = [s.student for s in job.students.filter(active_to__isnull=True)]
        tz = str(job.branch.timezone) if job.branch_id else _org_tz()
        found = conflicts.check(
            start=start,
            end=end,
            tz=tz,
            tutors=[tutor],
            students=students,
            location=job.location,
            online=bool(job.online),
            job=job,
        )
    return [c.as_dict() for c in found]


def _org_tz() -> str:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return str(Organisation.objects.get(pk=require_organisation_id()).timezone)


def create(
    user: Any,
    tutor: TutorProfile,
    *,
    job_id: Any,
    start: datetime,
    end: datetime,
    notes_for_tutor: str = "",
) -> Any:
    from tutortrack.scheduling import services as scheduling
    from tutortrack.scheduling.models import Lesson

    if not has_perm(user, "scheduling.lesson.create"):
        raise PermissionDenied(_("Your organisation hasn't turned on lesson booking for tutors."))
    job = _job(tutor, job_id)
    fields: dict[str, Any] = {}
    if notes_for_tutor:
        fields["notes_for_tutor"] = notes_for_tutor
    return scheduling.create_lesson(
        start=start,
        end=end,
        job=job,
        tutors=[{"tutor": tutor}],
        created_via=Lesson.CreatedVia.TUTOR,
        override_conflicts=False,
        **fields,
    )


def move(user: Any, *, lesson_id: Any, start: datetime, end: datetime, reason: str = "") -> Any:
    from tutortrack.scheduling import services as scheduling
    from tutortrack.scheduling.models import Lesson

    lesson = _own_lesson(user, lesson_id)
    if not has_perm(user, "scheduling.lesson.reschedule", lesson):
        raise PermissionDenied(_("Ask the office to move this lesson (send a request)."))
    if lesson.status != Lesson.Status.PLANNED:
        raise BusinessRuleViolation(_("Only planned lessons can be moved."))
    return scheduling.update_lesson(
        lesson, start=start, end=end, reason=reason, notify=True, override_conflicts=False
    )


# --- reads ----------------------------------------------------------------------------------------


def _answers(report: Any) -> list[dict[str, Any]]:
    from tutortrack.delivery import templates

    fields = report.template_version.fields or []
    answers = templates.visible_answers(fields, report.answers or {}, "staff")
    out = []
    for field in fields:
        value = answers.get(field["key"])
        if value in (None, "", [], {}):
            continue
        out.append(
            {"key": field["key"], "label": field.get("label") or field["key"], "value": value}
        )
    return out


def previous_report(user: Any, lesson_id: Any) -> dict[str, Any] | None:
    """The latest written report the user may read for a student on this lesson, from an
    earlier lesson (FR-16-3)."""
    from tutortrack.delivery.models import LessonReport

    lesson = _own_lesson(user, lesson_id)
    students = [a.student_id for a in lesson.attendees.all()]
    if not students:
        return None
    visible = scope_queryset(user, LessonReport.objects.all(), "delivery.report.view")
    report = (
        visible.filter(
            lesson__attendees__student_id__in=students,
            lesson__start__lt=lesson.start,
            status__in=[LessonReport.Status.SUBMITTED, LessonReport.Status.APPROVED],
        )
        .exclude(lesson=lesson)
        .select_related("lesson", "template_version", "tutor")
        .order_by("-lesson__start")
        .first()
    )
    if report is None:
        return None
    return {
        "id": str(report.pk),
        "lesson_id": str(report.lesson_id),
        "lesson_title": report.lesson.title,
        "lesson_start": report.lesson.start,
        "tutor": report.tutor.full_name,
        "status": report.status,
        "answers": _answers(report),
    }


def student_history(user: Any, tutor: TutorProfile, student_id: Any) -> dict[str, Any]:
    """Every lesson of the student the tutor may see, newest first, with the student's
    attendance and the tutor's report (FR-16-4)."""
    from tutortrack.delivery.models import LessonReport
    from tutortrack.people.models import Student
    from tutortrack.scheduling.models import Lesson, LessonAttendee

    student = Student.objects.filter(pk=student_id).first()
    if student is None:
        raise NotFound()
    visible = scope_queryset(user, Lesson.objects.all(), "scheduling.lesson.view")
    lessons = list(
        visible.filter(attendees__student=student)
        .distinct()
        .order_by("-start")
        .select_related("service")[:HISTORY_LIMIT]
    )
    on_job = _jobs(tutor).filter(students__student=student).exists()
    if not lessons and not on_job:
        raise NotFound()
    outcomes = dict(
        LessonAttendee.objects.filter(
            lesson__in=[x.pk for x in lessons], student=student
        ).values_list("lesson_id", "outcome")
    )
    readable = scope_queryset(user, LessonReport.objects.all(), "delivery.report.view")
    reports = {
        r.lesson_id: r
        for r in readable.filter(lesson__in=[x.pk for x in lessons]).only(
            "pk", "lesson_id", "status"
        )
    }
    rows = []
    for lesson in lessons:
        report = reports.get(lesson.pk)
        rows.append(
            {
                "id": str(lesson.pk),
                "title": lesson.title,
                "service": lesson.service.name,
                "start": lesson.start,
                "end": lesson.end,
                "status": lesson.status,
                "outcome": outcomes.get(lesson.pk, "") or "",
                "report_id": str(report.pk) if report else None,
                "report_status": report.status if report else "",
            }
        )
    attended = [r for r in rows if r["outcome"]]
    present = [r for r in attended if r["outcome"] in {"present", "late"}]
    return {
        "student": {
            "id": str(student.pk),
            "name": student.full_name,
            "year_group": student.year_group,
        },
        "lessons": rows,
        "attendance_percent": round(100 * len(present) / len(attended)) if attended else None,
    }
