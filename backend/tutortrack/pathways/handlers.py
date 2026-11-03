"""Where pathways start and move on by themselves (E34 FR-34-1, T02).

- A job-board application starts the posting's Apply pathway; being put on a job (or
  accepting it) starts its Join pathway; leaving it, or the job completing, starts Finish
  and cancels the tutor's Apply and Join on it. Each only when one applies
  (``services.template_for``), and never twice (``services.start_for``).
- Events that can finish a checked step (a check verified, a lesson completed, the family
  choosing a tutor) check the related pathways again.
- New organisations get the ready-made pathways.
"""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.core.events import EventEnvelope, subscribe

from .models import PathwayRun
from .models import PathwayTemplate as T

APPLY, JOIN, FINISH = T.Kind.APPLY, T.Kind.JOIN, T.Kind.FINISH


@subscribe("organisation.created")
def install_builtin_pathways(event: EventEnvelope) -> None:
    from . import services

    services.install_builtins()


@subscribe("job_posting.application_received")
def start_apply(event: EventEnvelope) -> None:
    from tutortrack.matching.models import JobPosting

    from . import services

    posting = JobPosting.objects.filter(pk=event.subject["id"]).first()
    if posting is not None:
        services.start_for(
            APPLY, job_id=posting.job_id, tutor_id=event.data["tutor_id"], posting_id=posting.pk
        )


@subscribe("job.tutor_assigned", "job.tutor_accepted")
def start_join(event: EventEnvelope) -> None:
    from . import services

    if event.data.get("offered"):
        return  # an offer: Join starts when it's accepted
    services.start_for(JOIN, job_id=event.subject["id"], tutor_id=event.data["tutor_id"])


def _leave(job_id: str, tutor_id: str) -> None:
    from . import services

    services.cancel_for(
        (APPLY, JOIN), job_id=job_id, tutor_id=tutor_id, reason=_("The tutor left the job")
    )
    services.start_for(FINISH, job_id=job_id, tutor_id=tutor_id)


@subscribe("job.tutor_removed")
def tutor_left(event: EventEnvelope) -> None:
    _leave(event.subject["id"], event.data["tutor_id"])


@subscribe("job.tutor_replaced")
def tutor_replaced(event: EventEnvelope) -> None:
    from . import services

    _leave(event.subject["id"], event.data["old_tutor_id"])
    services.start_for(JOIN, job_id=event.subject["id"], tutor_id=event.data["new_tutor_id"])


@subscribe("job.status_changed")
def job_closed(event: EventEnvelope) -> None:
    from tutortrack.jobs.models import Job, JobTutor

    from . import services

    to = event.data.get("to_status")
    job_id = event.subject["id"]
    if to == Job.Status.COMPLETED:
        for tutor_id in JobTutor.objects.filter(
            job_id=job_id, status=JobTutor.Status.ACTIVE
        ).values_list("tutor_id", flat=True):  # fmt: skip
            _leave(job_id, str(tutor_id))
    elif to == Job.Status.CANCELLED:
        services.cancel_for((APPLY, JOIN), job_id=job_id, reason=_("The job was cancelled"))


@subscribe("job_posting.filled")
def posting_filled(event: EventEnvelope) -> None:
    from . import services

    chosen = event.data.get("tutor_id")
    job_id = event.data["job_id"]
    for run in PathwayRun.objects.filter(
        template__kind=APPLY, subject_type="job", subject_id=str(job_id),
        status=PathwayRun.Status.RUNNING,
    ).exclude(tutor_id=None):  # fmt: skip
        reason = (
            _("Chosen for the job") if str(run.tutor_id) == chosen
            else _("Another tutor was chosen")
        )  # fmt: skip
        services.cancel_run(run, user=None, reason=reason)


def _recheck(**filters: object) -> None:
    from . import services

    services.recheck(PathwayRun.objects.filter(**filters))


@subscribe("compliance.record_verified", "compliance.expired")
def check_changed(event: EventEnvelope) -> None:
    _recheck(tutor_id=event.data["tutor_id"])


@subscribe("lesson.completed")
def lesson_completed(event: EventEnvelope) -> None:
    if event.data.get("job_id"):
        _recheck(subject_type="job", subject_id=str(event.data["job_id"]))


@subscribe("shortlist.tutor_chosen")
def family_chose(event: EventEnvelope) -> None:
    _recheck(subject_type="job", subject_id=str(event.data["job_id"]))
