"""The "Show a check" pathway step (E34 FR-34-1, T02): a check of one requirement type, or
all the tutor's required checks, in date. The tutor sends the document as an E18 compliance
record; verifying the record (here or on the tutor's checks) finishes the step. Checks from
the passport come with T09."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.pathways.pathway_steps import PARTICIPANT, Completion, StepType, register_step_type

from . import compliance
from .models import ComplianceRecord, RequirementType


def _requirement(key: str) -> RequirementType | None:
    compliance.ensure_requirement_types()
    return RequirementType.objects.filter(key=key, active=True).first()


def _clean(config: dict[str, Any], record_type: str) -> dict[str, Any]:
    key = config.get("requirement") or ""
    if not isinstance(key, str):
        raise BusinessRuleViolation(_("Choose a check."))
    if key and _requirement(key) is None:
        raise BusinessRuleViolation(_("Choose one of your checks."))
    return {"requirement": key}


def _record(step: Any) -> ComplianceRecord | None:
    requirement = _requirement(step.config["requirement"])
    tutor = step.run.tutor
    if requirement is None or tutor is None:
        return None
    return ComplianceRecord.objects.filter(tutor=tutor, requirement=requirement).first()


def _check(step: Any) -> bool:
    tutor = step.run.tutor
    if tutor is None:
        return False
    if not step.config["requirement"]:
        return not compliance.problems(tutor)
    return compliance.is_valid(_record(step), compliance.today())


def _date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BusinessRuleViolation(
            _("Check the form."), extra={"errors": {field: [_("Enter a date.")]}}
        ) from None


def _complete(c: Completion) -> dict[str, Any]:
    from tutortrack.core.models import StoredFile

    key = c.step.config["requirement"]
    requirement = _requirement(key) if key else None
    tutor = c.step.run.tutor
    if requirement is None or tutor is None:
        raise BusinessRuleViolation(_("Add your checks on the Checks page; this step then ticks."))
    ids = [str(i) for i in c.payload.get("files") or []]
    files = list(
        StoredFile.objects.filter(
            pk__in=ids, uploaded_by=c.user, status=StoredFile.Status.UPLOADED
        ).exclude(scan_status=StoredFile.ScanStatus.INFECTED)
    )
    if len(files) != len(set(ids)):
        raise BusinessRuleViolation(_("Upload the files again: some weren't found."))
    record = compliance.submit(
        tutor,
        requirement,
        number=str(c.payload.get("number") or ""),
        issue_date=_date(c.payload.get("issue_date"), "issue_date"),
        expiry_date=_date(c.payload.get("expiry_date"), "expiry_date"),
        files=files or None,
    )
    return {"record_id": str(record.pk)}


def _accept(step: Any, user: Any) -> None:
    record = _record(step)
    if record is not None and record.status != ComplianceRecord.Status.VERIFIED:
        compliance.verify(record, user=user)


def _send_back(step: Any, user: Any, reason: str) -> None:
    record = _record(step)
    if record is not None and record.status == ComplianceRecord.Status.SUBMITTED:
        compliance.reject(record, user=user, reason=reason)


def _view(step: Any) -> dict[str, Any]:
    key = step.config["requirement"]
    tutor = step.run.tutor
    if not key:
        missing = compliance.problems(tutor) if tutor else []
        names = dict(RequirementType.objects.filter(key__in=missing).values_list("key", "name"))
        return {"requirement": "", "missing": [names.get(k, k) for k in missing]}
    requirement = _requirement(key)
    record = _record(step)
    return {
        "requirement": key,
        "name": requirement.name if requirement else key,
        "has_number": bool(requirement and requirement.has_number),
        "has_expiry": bool(requirement and requirement.has_expiry),
        "record_status": record.status if record else "missing",
    }


register_step_type(
    StepType(
        key="show_check",
        label=gettext_lazy("Show a check"),
        assignees=(PARTICIPANT,),
        clean=_clean,
        complete=_complete,
        review=lambda config: bool(config.get("requirement")),
        check=_check,
        view=_view,
        accept=_accept,
        send_back=_send_back,
    )
)
