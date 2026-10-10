"""Whether a tutor can be given new work (E18 FR-18-6).

Restricted tutors (e.g. an expired DBS) can't be assigned to jobs or lessons. Someone
holding ``compliance.override_restriction`` can still do it with a reason: views wrap the
call in ``override_from_request(request)`` (``?compliance_override=<reason>``), which is
audited.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied

_override: ContextVar[str] = ContextVar("compliance_override", default="")


@contextmanager
def compliance_override(reason: str) -> Iterator[None]:
    token = _override.set(reason)
    try:
        yield
    finally:
        _override.reset(token)


def override_from_request(request: Any) -> Any:
    from tutortrack.core.permissions import has_perm

    reason = str(request.query_params.get("compliance_override", "")).strip()
    if not reason:
        return nullcontext()
    if not has_perm(request.user, "compliance.override_restriction"):
        raise PermissionDenied(_("You can't override compliance restrictions."))
    return compliance_override(reason[:300])


def check_assignable(tutor: Any, field: str = "tutor") -> None:
    from tutortrack.core import audit

    from .models import TutorProfile

    if tutor.status == TutorProfile.Status.RESTRICTED:
        reason = _override.get()
        if reason:
            audit.record(tutor, "compliance_override", {"reason": [None, reason]})
            return
        message = _("%(name)s isn't compliant (missing or expired checks).") % {
            "name": tutor.full_name
        }
        raise BusinessRuleViolation(
            message, extra={"code": "tutor_not_compliant", "errors": {field: [message]}}
        )
    if tutor.status not in {TutorProfile.Status.ACTIVE, TutorProfile.Status.ONBOARDING}:
        message = _("%(name)s isn't available for work (%(status)s).") % {
            "name": tutor.full_name, "status": tutor.get_status_display(),
        }  # fmt: skip
        raise BusinessRuleViolation(message, extra={"errors": {field: [message]}})
