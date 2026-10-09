"""Start ``UnconfirmedLessonWorkflow`` for lessons that have just ended (FR-09-8).

Global, tenant-sharded beat task (every 15 minutes). It only starts processes: the wait,
the nudge and the auto-complete live in the workflow. Starts are idempotent by workflow
id, and lessons that already have a process are skipped without calling Temporal.
"""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task

from tutortrack.core.tasks import TenantTask, fan_out_per_org

LOOKBACK = timedelta(hours=6)  # covers a beat or Temporal outage of a few hours


@shared_task(
    base=TenantTask, name="tutortrack.delivery.tasks.start_unconfirmed_checks", ignore_result=True
)
def start_unconfirmed_checks(*, organisation_id: str) -> int:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.time import now
    from tutortrack.core.workflows import start_now
    from tutortrack.scheduling.models import Lesson

    from .processes import (
        UNCONFIRMED_PROCESS,
        UnconfirmedInput,
        UnconfirmedLessonWorkflow,
        unconfirmed_workflow_id,
    )

    moment = now()
    lessons = Lesson.objects.filter(
        status=Lesson.Status.PLANNED, end__lte=moment, end__gt=moment - LOOKBACK
    ).values_list("pk", "end", "branch_id")
    started_ids = set(
        WorkflowLink.objects.filter(
            process=UNCONFIRMED_PROCESS, subject_id__in=[str(pk) for pk, _e, _b in lessons]
        ).values_list("subject_id", flat=True)
    )
    started = 0
    for pk, end, branch_id in lessons:
        if str(pk) in started_ids:
            continue
        run = start_now(
            UnconfirmedLessonWorkflow,
            UnconfirmedInput(
                organisation_id=organisation_id, lesson_id=str(pk), end=end.isoformat()
            ),
            id=unconfirmed_workflow_id(organisation_id, pk),
            subject=("lesson", str(pk)),
            branch_id=branch_id,
        )
        started += run is not None
    return started


@shared_task(name="tutortrack.delivery.tasks.start_all_unconfirmed_checks", ignore_result=True)
def start_all_unconfirmed_checks() -> int:
    return fan_out_per_org(start_unconfirmed_checks)
