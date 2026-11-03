"""The "Family chooses" pathway step (E34 FR-34-1, T02): staff share the job's shortlist with
the family (FR-19-5); choosing the pathway's tutor ticks the step, choosing another tutor
turns the pathway down. The family's consent joins this page in T03."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.pathways.pathway_steps import FAMILY, StepType, register_step_type

from .models import ShortlistShare


def _clean(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    if record_type != "job":
        raise BusinessRuleViolation(_("A family step needs a pathway about a job."))
    return {}


def _choice(step: Any) -> ShortlistShare | None:
    shares = ShortlistShare.objects.filter(
        job_id=step.run.subject_id, status=ShortlistShare.Status.CHOSEN
    )
    if step.opened_at is not None:
        shares = shares.filter(chosen_at__gte=step.opened_at)
    return shares.order_by("-chosen_at").first()


def _check(step: Any) -> bool | str:
    chosen = _choice(step)
    if chosen is None:
        return False
    return True if chosen.chosen_tutor_id == step.run.tutor_id else "rejected"


def _view(step: Any) -> dict[str, Any]:
    shared = ShortlistShare.objects.filter(
        job_id=step.run.subject_id, status=ShortlistShare.Status.ACTIVE
    ).exists()
    return {"job_id": step.run.subject_id, "shared": shared}


register_step_type(
    StepType(
        key="family_chooses",
        label=gettext_lazy("Family chooses"),
        assignees=(FAMILY,),
        clean=_clean,
        check=_check,
        view=_view,
    )
)
