"""The "Trial lesson" pathway step (E34 FR-34-1, T02): TutorTrack ticks it when a lesson on
the job with the pathway's tutor is completed (staff book and mark it as usual)."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.pathways.pathway_steps import SYSTEM, StepType, register_step_type

from .models import Lesson


def _clean(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    if record_type != "job":
        raise BusinessRuleViolation(_("A trial lesson step needs a pathway about a job."))
    return {}


def _check(step: Any) -> bool:
    run = step.run
    return Lesson.objects.filter(
        job_id=run.subject_id, status=Lesson.Status.COMPLETED, tutors__tutor_id=run.tutor_id
    ).exists()


register_step_type(
    StepType(
        key="trial_lesson",
        label=gettext_lazy("Trial lesson"),
        assignees=(SYSTEM,),
        clean=_clean,
        check=_check,
        view=lambda step: {"job_id": step.run.subject_id},
    )
)
