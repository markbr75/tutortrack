"""React to job changes (E07 integration, E08-T10). Handlers are idempotent."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.time import now

from .models import Lesson, LessonSeries, LessonTutor


@subscribe("job.created")
def create_series_from_schedule(event: EventEnvelope) -> None:
    """Quick setup (FR-07-2): turn the job's weekly slots into lesson series."""
    from tutortrack.jobs.models import Job

    from . import services

    job = Job.objects.filter(pk=event.subject["id"]).first()
    if job is not None:
        services.schedule_from_job(job)


@subscribe("job.tutor_replaced")
def move_lessons_to_new_tutor(event: EventEnvelope) -> None:
    """Future unlocked lessons go to the new tutor and their pay is re-resolved."""
    from tutortrack.jobs.models import Job
    from tutortrack.people.models import TutorProfile

    from . import pricing

    job = Job.objects.filter(pk=event.subject["id"]).first()
    new = TutorProfile.objects.filter(pk=event.data["new_tutor_id"]).first()
    if job is None or new is None:
        return
    zone = ZoneInfo(str(job.branch.timezone))
    effective = datetime.combine(
        date.fromisoformat(event.data["effective_date"]), time.min, tzinfo=zone
    )
    links = LessonTutor.objects.filter(
        tutor_id=event.data["old_tutor_id"],
        lesson__job=job,
        lesson__status=Lesson.Status.PLANNED,
        lesson__lock_state=Lesson.Lock.UNLOCKED,
        lesson__start__gte=effective,
    ).select_related("lesson")
    for link in links:
        if LessonTutor.objects.filter(lesson=link.lesson, tutor=new).exists():
            link.delete()
        else:
            link.tutor = new
            link.pay_rate_override = None
            link.save()
        pricing.price_lesson(link.lesson)
    _update_series_tutors(job, event.data["old_tutor_id"], str(new.pk))


def _update_series_tutors(job: object, old: str, new: str) -> None:
    for series in LessonSeries.objects.filter(job=job, status=LessonSeries.Status.ACTIVE):
        tpl = dict(series.template or {})
        tutors = [row for row in tpl.get("tutors", []) if row["tutor"] != old]
        if not any(row["tutor"] == new for row in tutors):
            tutors.append({"tutor": new, "pay_rate_override": None})
        tpl["tutors"] = tutors
        series.template = tpl
        series.save(update_fields=["template", "updated_at"])


@subscribe("job.tutor_assigned")
def fill_unassigned_lessons(event: EventEnvelope) -> None:
    """A job that was seeking a tutor: its future lessons without a tutor get this one."""
    from tutortrack.jobs.models import Job
    from tutortrack.people.models import TutorProfile

    from . import pricing

    if event.data.get("offered"):
        return
    job = Job.objects.filter(pk=event.subject["id"]).first()
    tutor = TutorProfile.objects.filter(pk=event.data["tutor_id"]).first()
    if job is None or tutor is None:
        return
    lessons = job.lessons.filter(
        status=Lesson.Status.PLANNED,
        lock_state=Lesson.Lock.UNLOCKED,
        start__gte=now(),
        tutors__isnull=True,
    )
    for lesson in lessons:
        LessonTutor.objects.get_or_create(
            lesson=lesson, tutor=tutor, defaults={"currency": job.currency}
        )
        pricing.price_lesson(lesson)
    for series in LessonSeries.objects.filter(job=job, status=LessonSeries.Status.ACTIVE):
        tpl = dict(series.template or {})
        if not tpl.get("tutors"):
            tpl["tutors"] = [{"tutor": str(tutor.pk), "pay_rate_override": None}]
            series.template = tpl
            series.save(update_fields=["template", "updated_at"])


@subscribe("job.status_changed")
def follow_job_status(event: EventEnvelope) -> None:
    """Paused (when asked), completed and cancelled jobs cancel their future lessons and
    end their series (FR-07-4)."""
    from tutortrack.jobs.models import Job

    from . import services

    if event.data.get("future_lessons") != "cancel":
        return
    job = Job.objects.filter(pk=event.subject["id"]).first()
    if job is None:
        return
    reason = event.data.get("reason") or f"Job {event.data['to_status']}"
    for lesson in job.lessons.filter(
        status=Lesson.Status.PLANNED, lock_state=Lesson.Lock.UNLOCKED, start__gte=now()
    ):
        services.cancel_lesson(lesson, reason=reason, chargeable=False)
    if event.data["to_status"] in {"completed", "cancelled"}:
        for series in LessonSeries.objects.filter(job=job, status=LessonSeries.Status.ACTIVE):
            services.end_series(series, reason=reason)
