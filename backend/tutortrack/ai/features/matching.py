"""FR-31-6 Matching explanations: why a tutor ranks where they do, from the E19 score
breakdown (recomputed here so the explanation is grounded in the same engine), and a
suggested introduction message for the family."""

from __future__ import annotations

import json
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm

from .. import engine, prompts
from ..redaction import Redactor

# Breakdown values that are personal or commercial and add nothing to an explanation.
HIDDEN_FACTORS = {"margin"}


def explain(
    user: Any, *, tutor_id: Any, job_id: Any = None, criteria: dict[str, Any] | None = None
) -> dict[str, Any]:
    from tutortrack.matching import engine as matching
    from tutortrack.matching.selectors import visible_jobs

    if not has_perm(user, "matching.search"):
        raise PermissionDenied()
    job = None
    if job_id:
        job = visible_jobs(user).filter(pk=job_id).first()
        if job is None:
            raise BusinessRuleViolation(_("Job not found."))
    search = (
        matching.criteria_from_input(criteria or {}, job)
        if criteria
        else (matching.criteria_for_job(job) if job is not None else None)
    )
    if search is None:
        raise BusinessRuleViolation(_("Choose a job or give the search criteria."))
    include = has_perm(user, "matching.include_restricted")
    matches = matching.search(search, include_restricted=include, limit=1, only=[str(tutor_id)])
    if not matches:
        raise BusinessRuleViolation(_("This tutor doesn't meet the search's requirements."))
    match = matches[0]
    redactor = Redactor()
    tutor = match.tutor
    redactor.person(
        tutor.full_name, kind="TUTOR", first_name=tutor.first_name, last_name=tutor.last_name
    )
    breakdown = {k: v for k, v in match.breakdown.items() if k not in HIDDEN_FACTORS}
    content = "\n".join(
        [
            f"Tutor: {tutor.full_name} ({tutor.headline or 'no headline'})",
            f"Request: {search.subject_name or 'any subject'}, mode {search.mode}, "
            f"area {search.area or '-'}",
            f"Overall score: {match.score} out of 100",
            f"Distance: {match.distance_km if match.distance_km is not None else 'unknown'} km",
            f"Restricted: {'yes - ' + '; '.join(match.reasons) if match.restricted else 'no'}",
            "Score breakdown (factor: weight, score 0-1, value, known):",
            json.dumps(breakdown, sort_keys=True, default=str),
        ]
    )
    result = engine.run(prompts.MATCHING, user=user, content=content, redactor=redactor)
    data = result.data or {}
    return {
        "request": str(result.log.pk),
        "score": str(match.score),
        "explanation": str(data.get("explanation") or ""),
        "intro_message": str(data.get("intro_message") or ""),
    }
