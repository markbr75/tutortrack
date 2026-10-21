"""Compliance (E18 FR-18-6/8): requirement types, records and their verification, and the
restriction rule: a tutor missing a mandatory blocking requirement (missing, rejected or
expired) is ``restricted`` and can't be given new work; pay can be held too.

Validity: a verified record is valid until (not including) its expiry date, so a check that
"expires today" restricts the tutor today.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import catalogue, events
from .models import ComplianceRecord, RequirementType, TutorComplianceState


def today() -> date:
    from zoneinfo import ZoneInfo

    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return now().astimezone(ZoneInfo(org.timezone)).date()


def ensure_requirement_types() -> list[RequirementType]:
    """The organisation's country defaults plus the common ones, created on first use."""
    existing = list(RequirementType.objects.all())
    if existing:
        return existing
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    country = Organisation.objects.get(pk=require_organisation_id()).country
    with transaction.atomic():
        for spec in [*catalogue.REQUIREMENTS.get(country, []), *catalogue.COMMON]:
            RequirementType.objects.get_or_create(
                key=spec["key"], defaults={k: v for k, v in spec.items() if k != "key"}
            )
    return list(RequirementType.objects.all())


def applicable(tutor: TutorProfile) -> list[RequirementType]:
    out = []
    for requirement in ensure_requirement_types():
        if not requirement.active:
            continue
        rules = requirement.applies_to or {}
        kinds = rules.get("employment_types")
        if kinds and tutor.employment_type not in kinds:
            continue
        if rules.get("in_person_only") and not tutor.delivers_in_person:
            continue
        out.append(requirement)
    return out


def record_for(tutor: TutorProfile, requirement: RequirementType) -> ComplianceRecord:
    record, _created = ComplianceRecord.objects.get_or_create(tutor=tutor, requirement=requirement)
    return record


def is_valid(record: ComplianceRecord | None, on: date) -> bool:
    if record is None or record.status != ComplianceRecord.Status.VERIFIED:
        return False
    return record.expiry_date is None or record.expiry_date > on


def problems(tutor: TutorProfile, on: date | None = None) -> list[str]:
    on = on or today()
    records = {r.requirement_id: r for r in ComplianceRecord.objects.filter(tutor=tutor)}
    return [
        req.key
        for req in applicable(tutor)
        if req.mandatory and req.blocking and not is_valid(records.get(req.pk), on)
    ]


@transaction.atomic
def submit(
    tutor: TutorProfile,
    requirement: RequirementType,
    *,
    number: str = "",
    issue_date: date | None = None,
    expiry_date: date | None = None,
    files: list[Any] | None = None,
    notes: str = "",
) -> ComplianceRecord:
    """The tutor (or staff) provides the document and details; staff verify it next."""
    if requirement.has_number and not number.strip():
        raise BusinessRuleViolation(
            _("Enter the reference number."), extra={"errors": {"number": [_("Required.")]}}
        )
    if expiry_date is None and requirement.renewal_months and issue_date is not None:
        from dateutil.relativedelta import relativedelta

        expiry_date = issue_date + relativedelta(months=requirement.renewal_months)
    if requirement.has_expiry and expiry_date is None:
        raise BusinessRuleViolation(
            _("Enter the expiry date."), extra={"errors": {"expiry_date": [_("Required.")]}}
        )
    record = ComplianceRecord.objects.select_for_update().get(pk=record_for(tutor, requirement).pk)
    with audit.track(record, action="submit"):
        record.status = ComplianceRecord.Status.SUBMITTED
        record.number = number.strip()[:100]
        record.issue_date = issue_date
        record.expiry_date = expiry_date
        record.notes = notes[:2000]
        record.rejection_reason = ""
        record.verified_by = None
        record.verified_at = None
        record.save()
    if files is not None:
        from tutortrack.core.storage.services import attach

        for stored in files:
            attach(stored, record)
        record.files.set(files)
    publish(
        events.ComplianceSubmitted(
            subject_id=record.pk, tutor_id=str(tutor.pk), requirement=requirement.key
        )
    )
    from tutortrack.comms import services as comms

    comms.notify(
        "staff_compliance_submitted",
        (
            _("%(name)s sent %(what)s") % {"name": tutor.full_name, "what": requirement.name},
            _("Check and verify it."),
            f"/tutors/{tutor.pk}",
        ),
        key=f"compliance:{record.pk}:{now():%Y%m%d%H%M}",
    )
    return record


def _check_verifier(user: Any, record: ComplianceRecord) -> None:
    if not has_perm(user, "compliance.verify"):
        raise PermissionDenied()
    membership = record.tutor.membership
    if membership is not None and membership.user_id == getattr(user, "pk", None):
        raise PermissionDenied(_("You can't verify your own documents."))


@transaction.atomic
def verify(record: ComplianceRecord, *, user: Any) -> ComplianceRecord:
    record = (
        ComplianceRecord.objects.select_for_update(of=("self",))
        .select_related("requirement", "tutor__membership")
        .get(pk=record.pk)
    )
    _check_verifier(user, record)
    if record.status not in (ComplianceRecord.Status.SUBMITTED, ComplianceRecord.Status.REJECTED):
        raise BusinessRuleViolation(_("Nothing to verify yet."))
    if record.expiry_date is not None and record.expiry_date <= today():
        raise BusinessRuleViolation(_("This has already expired."))
    with audit.track(record, action="verify"):
        record.status = ComplianceRecord.Status.VERIFIED
        record.verified_by = user
        record.verified_at = now()
        record.save()
    publish(
        events.ComplianceVerified(
            subject_id=record.pk,
            tutor_id=str(record.tutor_id),
            requirement=record.requirement.key,
            expiry_date=record.expiry_date.isoformat() if record.expiry_date else None,
        )
    )
    evaluate(record.tutor)
    return record


@transaction.atomic
def reject(record: ComplianceRecord, *, user: Any, reason: str) -> ComplianceRecord:
    record = (
        ComplianceRecord.objects.select_for_update(of=("self",))
        .select_related("requirement", "tutor__membership")
        .get(pk=record.pk)
    )
    _check_verifier(user, record)
    if not reason.strip():
        raise BusinessRuleViolation(_("Say why."), extra={"errors": {"reason": [_("Required.")]}})
    with audit.track(record, action="reject"):
        record.status = ComplianceRecord.Status.REJECTED
        record.rejection_reason = reason.strip()[:500]
        record.save()
    publish(
        events.ComplianceRejected(
            subject_id=record.pk,
            tutor_id=str(record.tutor_id),
            requirement=record.requirement.key,
            reason=record.rejection_reason,
        )
    )
    evaluate(record.tutor)
    return record


@transaction.atomic
def evaluate(tutor: TutorProfile, on: date | None = None) -> list[str]:
    """Restrict an active tutor with compliance problems; lift a compliance restriction once
    everything is valid again. Manual restrictions are left alone."""
    from tutortrack.payroll.services import reevaluate_tutor
    from tutortrack.people.services import change_tutor_status

    tutor = TutorProfile.objects.select_for_update().get(pk=tutor.pk)
    found = problems(tutor, on)
    state, _created = TutorComplianceState.objects.select_for_update().get_or_create(tutor=tutor)
    state.problems = found
    state.checked_at = now()
    if found and tutor.status == TutorProfile.Status.ACTIVE:
        change_tutor_status(tutor, TutorProfile.Status.RESTRICTED)
        state.restricted_by_compliance = True
        publish(events.TutorRestricted(subject_id=tutor.pk, problems=found))
    elif not found and state.restricted_by_compliance:
        if tutor.status == TutorProfile.Status.RESTRICTED:
            change_tutor_status(tutor, TutorProfile.Status.ACTIVE)
            publish(events.TutorUnrestricted(subject_id=tutor.pk))
        state.restricted_by_compliance = False
    state.save()
    reevaluate_tutor(tutor)
    return found


def compliance_hold(item: Any) -> bool:
    """Payroll hold rule (E12): pay waits while compliance restricts the tutor."""
    if not get_setting("compliance.hold_pay"):
        return False
    return TutorComplianceState.objects.filter(
        tutor_id=item.tutor_id, restricted_by_compliance=True
    ).exists()


@transaction.atomic
def expire(record_id: Any, on: date | None = None) -> bool:
    on = on or today()
    record = (
        ComplianceRecord.objects.select_for_update(of=("self",))
        .select_related("requirement", "tutor")
        .filter(pk=record_id)
        .first()
    )
    if record is None or record.status != ComplianceRecord.Status.VERIFIED:
        return False
    if record.expiry_date is None or record.expiry_date > on:
        return False
    record.status = ComplianceRecord.Status.EXPIRED
    record.save(update_fields=["status", "updated_at"])
    publish(
        events.ComplianceExpired(
            subject_id=record.pk, tutor_id=str(record.tutor_id), requirement=record.requirement.key
        )
    )
    evaluate(record.tutor, on)
    return True


def remind(record_id: Any, days: int, expiry: str) -> bool:
    """A reminder ``days`` before expiry, to the tutor and compliance staff."""
    from tutortrack.comms import services as comms

    record = (
        ComplianceRecord.objects.select_related("requirement", "tutor__membership")
        .filter(pk=record_id)
        .first()
    )
    if record is None or record.status != ComplianceRecord.Status.VERIFIED:
        return False
    if not record.expiry_date or record.expiry_date.isoformat() != expiry:
        return False  # renewed since
    with transaction.atomic():
        publish(
            events.ComplianceExpiring(
                subject_id=record.pk,
                tutor_id=str(record.tutor_id),
                requirement=record.requirement.key,
                days=days,
            ),
            dedupe_key=f"expiring:{record.pk}:{expiry}:{days}",
        )
    comms.notify("compliance_reminder", (record.pk, days), key=f"{expiry}:{days}")
    comms.notify(
        "staff_compliance_expiring",
        (
            _("%(what)s for %(name)s expires in %(days)s days")
            % {"what": record.requirement.name, "name": record.tutor.full_name, "days": days},
            _("Ask for the renewal."),
            f"/tutors/{record.tutor_id}",
        ),
        key=f"expiring:{record.pk}:{expiry}:{days}",
    )
    return True


def sweep(on: date | None = None) -> int:
    """Nightly safety net: expire overdue records (the workflow normally does it at the
    expiry date) and re-check active tutors, e.g. after a new requirement was added."""
    on = on or today()
    expired = 0
    for pk in ComplianceRecord.objects.filter(
        status=ComplianceRecord.Status.VERIFIED, expiry_date__lte=on
    ).values_list("pk", flat=True):
        expired += int(expire(pk, on))
    for tutor in TutorProfile.objects.filter(status=TutorProfile.Status.ACTIVE):
        evaluate(tutor, on)
    return expired


GAPS = ("missing", "rejected", "expired")
DASHBOARD_STATUSES = ("onboarding", "active", "restricted")


def dashboard(
    *,
    tutor_status: str = "",
    requirement: str = "",
    cell_status: str = "",
    gaps_only: bool = False,
    tutor_ids: list[Any] | None = None,
) -> dict[str, Any]:
    """Tutors x requirements with each cell's status (FR-18-8). Filters (G5a): the tutor's
    status, one requirement (key), a cell status, only tutors with gaps (missing, rejected
    or expired)."""
    requirements = [r for r in ensure_requirement_types() if r.active]
    statuses = [tutor_status] if tutor_status in DASHBOARD_STATUSES else DASHBOARD_STATUSES
    qs = TutorProfile.objects.filter(status__in=statuses)
    if tutor_ids is not None:
        qs = qs.filter(pk__in=tutor_ids)
    tutors = list(qs.order_by("last_name", "first_name"))
    board = _matrix(requirements, tutors)
    wanted = [r.key for r in requirements if not requirement or r.key == requirement]
    if requirement:
        board["requirements"] = [r for r in requirements if r.key == requirement]

    def keep(row: dict[str, Any]) -> bool:
        cells = [row["cells"][k]["status"] for k in wanted]
        if cell_status and cell_status not in cells:
            return False
        return not gaps_only or any(c in GAPS for c in cells)

    board["rows"] = [r for r in board["rows"] if keep(r)]
    return board


def export_rows(board: dict[str, Any]) -> list[list[str]]:
    """The dashboard as CSV rows (FR-18-8 export): one row per tutor, a status and expiry
    column per requirement."""
    labels = {
        "missing": _("Missing"),
        "submitted": _("Waiting for verification"),
        "verified": _("Verified"),
        "rejected": _("Rejected"),
        "expired": _("Expired"),
        "n/a": _("Not needed"),
    }
    header = [_("Tutor"), _("Email"), _("Tutor status")]
    for req in board["requirements"]:
        header += [str(req.name), _("%(name)s expiry") % {"name": req.name}]
    rows = [header]
    for row in board["rows"]:
        tutor = row["tutor"]
        line = [tutor.full_name, tutor.email, row["status"]]
        for req in board["requirements"]:
            cell = row["cells"][req.key]
            line += [
                str(labels.get(cell["status"], cell["status"])),
                cell["expiry_date"].isoformat() if cell["expiry_date"] else "",
            ]
        rows.append(line)
    return rows


def request_missing(
    *, tutor_ids: list[Any] | None = None, requirements: list[str] | None = None, user: Any = None
) -> list[dict[str, Any]]:
    """Bulk "request missing documents" (FR-18-8): tell each tutor (all with gaps, or the
    chosen ones) which documents are missing, rejected or expired. At most one request per
    tutor per day for the same documents."""
    from tutortrack.comms import services as comms

    board = dashboard(tutor_ids=tutor_ids, gaps_only=True)
    wanted = set(requirements or [])
    names = {r.key: r.name for r in board["requirements"]}
    sent: list[dict[str, Any]] = []
    for row in board["rows"]:
        tutor = row["tutor"]
        gaps = [
            key
            for key, cell in row["cells"].items()
            if cell["status"] in GAPS and (not wanted or key in wanted)
        ]
        if not gaps:
            continue
        with transaction.atomic():
            publish(
                events.ComplianceDocumentsRequested(subject_id=tutor.pk, requirements=gaps),
                dedupe_key=f"docs-requested:{tutor.pk}:{today():%Y%m%d}:{','.join(sorted(gaps))}",
            )
            audit.record(tutor, "compliance_documents_requested", {"requirements": [None, gaps]})
        comms.notify(
            "compliance_documents_requested",
            (tutor.pk, [str(names[k]) for k in gaps]),
            key=f"docs:{tutor.pk}:{today():%Y%m%d}:{','.join(sorted(gaps))}",
        )
        sent.append({"tutor": tutor.pk, "requirements": gaps})
    return sent


def _matrix(requirements: list[RequirementType], tutors: list[TutorProfile]) -> dict[str, Any]:
    records = {
        (r.tutor_id, r.requirement_id): r for r in ComplianceRecord.objects.filter(tutor__in=tutors)
    }
    on = today()
    rows = []
    for tutor in tutors:
        applies = {r.pk for r in applicable(tutor)}
        cells = {}
        for req in requirements:
            if req.pk not in applies:
                cells[req.key] = {"status": "n/a", "expiry_date": None}
                continue
            record = records.get((tutor.pk, req.pk))
            status = record.status if record else "missing"
            if record and status == "verified" and not is_valid(record, on):
                status = "expired"
            cells[req.key] = {
                "status": status,
                "expiry_date": record.expiry_date if record else None,
            }
        rows.append({"tutor": tutor, "status": tutor.status, "cells": cells})
    return {"requirements": requirements, "rows": rows}
