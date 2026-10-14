"""Online background checks (E18-T11, FR-18-7): start a check at a provider from the tutor
record, track it (``BackgroundCheckWorkflow``: provider webhooks signal ``updated``, with
polling as the fallback), and attach the result to the tutor's compliance record.

* A clear result submits the compliance record with the certificate number and issue
  date and, with ``compliance.checks_auto_verify`` (on by default), verifies it as the
  provider; anything else leaves it submitted for a person to review (and notifies
  ``compliance.verify`` holders).
* DBS Update Service checks are re-run on a timer; new information rejects the record
  (the tutor is restricted if the requirement blocks) and tells staff.
* Results, certificate numbers and report links are encrypted. ``details`` (the only
  way to read them) needs ``compliance.checks.results`` and is audited.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id, tenant_context
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.integrations import routes
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import Credentials
from tutortrack.people.models import TutorProfile
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.settings_service import get_setting

from . import checks, compliance, events
from .models import BackgroundCheck, ComplianceRecord, RequirementType

logger = structlog.get_logger(__name__)
Status = BackgroundCheck.Status
OPEN = (Status.REQUESTED, Status.INVITED, Status.IN_PROGRESS)
TERMINAL = (Status.COMPLETED, Status.CANCELLED, Status.EXPIRED, Status.FAILED)


def connection(provider: str) -> IntegrationConnection | None:
    return (
        IntegrationConnection.objects.filter(provider=provider, user__isnull=True)
        .exclude(status=IntegrationConnection.Status.DISCONNECTED)
        .first()
    )


def _credentials(provider: str) -> Credentials:
    from tutortrack.integrations import services as integrations

    if not checks.info(provider).connection:
        return Credentials()
    conn = connection(provider)
    if conn is None:
        if not checks.live():
            return Credentials(account_id="fake")  # development and tests
        raise checks.CheckError(
            _("Connect %(provider)s first.") % {"provider": checks.info(provider).label}
        )
    return integrations.credentials(conn)


def available() -> list[dict[str, Any]]:
    """Providers for the organisation's country, with whether each is ready to use."""
    org = Organisation.objects.get(pk=require_organisation_id())
    out = []
    for key, provider in checks.PROVIDERS.items():
        ready = not provider.connection or not checks.live() or connection(key) is not None
        out.append(
            {
                "key": key,
                "title": str(provider.label),
                "countries": list(provider.countries),
                "recommended": org.country in provider.countries,
                "packages": [{"key": k, "label": str(v)} for k, v in provider.packages],
                "connected": ready,
                "needs_connection": provider.connection,
                "manual": provider.manual,
            }
        )
    return out


def _requirement(provider: str, requirement: RequirementType | None) -> RequirementType | None:
    if requirement is not None:
        return requirement
    compliance.ensure_requirement_types()
    keys = checks.info(provider).requirement_keys
    return RequirementType.objects.filter(key__in=keys, active=True).first()


def _candidate(check: BackgroundCheck) -> checks.Candidate:
    tutor = check.tutor
    org = Organisation.objects.get(pk=check.organisation_id)
    requester = check.requested_by
    return checks.Candidate(
        ref=str(check.pk),
        first_name=tutor.first_name,
        last_name=tutor.last_name,
        email=tutor.email,
        phone=tutor.phone,
        date_of_birth=tutor.date_of_birth.isoformat() if tutor.date_of_birth else "",
        country=org.country,
        certificate_number=check.certificate_number,
        work_location=check.state_code,
        organisation_name=org.legal_name or org.name,
        requester_first_name=getattr(requester, "first_name", "") or "",
        requester_last_name=getattr(requester, "last_name", "") or "",
    )


def _event_base(check: BackgroundCheck) -> dict[str, Any]:
    return {"subject_id": check.pk, "tutor_id": str(check.tutor_id), "provider": check.provider}


@transaction.atomic
def request_check(
    tutor: TutorProfile,
    *,
    provider: str,
    user: Any,
    consent: bool,
    package: str = "",
    requirement: RequirementType | None = None,
    certificate_number: str = "",
    state_code: str = "",
) -> BackgroundCheck:
    """Start a check (the workflow initiates it at the provider after commit)."""
    from tutortrack.core.workflows import start

    from .check_processes import BackgroundCheckInput, BackgroundCheckWorkflow, check_workflow_id

    try:
        info = checks.info(provider)
    except checks.CheckError as exc:
        raise BusinessRuleViolation(str(exc), extra={"errors": {"provider": [str(exc)]}}) from exc
    if not consent:
        message = _("Confirm the tutor has agreed to the check.")
        raise BusinessRuleViolation(message, extra={"errors": {"consent": [message]}})
    if info.packages and package and package not in dict(info.packages):
        raise BusinessRuleViolation(
            _("Unknown check type."), extra={"errors": {"package": [_("Unknown check type.")]}}
        )
    if info.connection and checks.live() and connection(provider) is None:
        message = _("Connect %(provider)s first.") % {"provider": info.label}
        raise BusinessRuleViolation(message, extra={"errors": {"provider": [message]}})
    if BackgroundCheck.objects.filter(tutor=tutor, provider=provider, status__in=OPEN).exists():
        raise BusinessRuleViolation(_("A check with this provider is already under way."))
    requirement = _requirement(provider, requirement)
    if provider == "dbs_update":
        record = (
            ComplianceRecord.objects.filter(tutor=tutor, requirement=requirement).first()
            if requirement
            else None
        )
        certificate_number = certificate_number or (record.number if record else "")
        if not certificate_number.strip() or tutor.date_of_birth is None:
            message = _("A status check needs the DBS certificate number and the date of birth.")
            raise BusinessRuleViolation(
                message, extra={"errors": {"certificate_number": [message]}}
            )
    check = BackgroundCheck.objects.create(
        tutor=tutor,
        provider=provider,
        package=package or (info.packages[0][0] if info.packages else ""),
        requirement=requirement,
        certificate_number=certificate_number.strip()[:40],
        state_code=state_code.strip().upper()[:3],
        requested_by=user if getattr(user, "is_authenticated", False) else None,
        consent_at=now(),
    )
    audit.record_create(check)
    publish(events.BackgroundCheckRequested(**_event_base(check)))
    org_id = require_organisation_id()
    start(
        BackgroundCheckWorkflow,
        BackgroundCheckInput(organisation_id=str(org_id), check_id=str(check.pk)),
        id=check_workflow_id(org_id, check.pk),
        subject=("background_check", str(check.pk)),
    )
    return check


def settings_for(check_id: Any) -> dict[str, Any]:
    check = BackgroundCheck.objects.get(pk=check_id)
    info = checks.info(check.provider)
    recheck = int(get_setting("compliance.dbs_update_recheck_days")) if info.recheck_days else 0
    return {
        "poll_hours": info.poll_hours,
        "invite_days": int(get_setting("compliance.check_invite_days")),
        "recheck_days": recheck,
        "manual": info.manual,
    }


@transaction.atomic
def initiate(check_id: Any) -> str:
    check = BackgroundCheck.objects.select_for_update().select_related("tutor").get(pk=check_id)
    if check.status != Status.REQUESTED:
        return check.status  # idempotent on activity retry
    try:
        started = checks.client(check.provider).initiate(
            _credentials(check.provider), _candidate(check), check.package
        )
    except checks.CheckError as exc:
        with audit.track(check, action="failed"):
            check.status = Status.FAILED
            check.error = str(exc)[:500]
            check.save()
        publish(events.BackgroundCheckFailed(**_event_base(check), status=check.status))
        return check.status
    with audit.track(check, action="initiated"):
        check.external_id = started.external_id[:120]
        check.candidate_ref = started.candidate_ref[:120]
        check.invite_url = started.invite_url
        check.status = {"completed": Status.IN_PROGRESS, "in_progress": Status.IN_PROGRESS}.get(
            started.status, Status.INVITED
        )
        check.save()
    for ref in (check.external_id, check.candidate_ref):
        if ref:
            routes.remember(check.provider, ref)
    if started.status == "completed":
        return poll(check.pk)
    return check.status


def _apply(check: BackgroundCheck, state: checks.CheckState) -> str:
    check.last_checked_at = now()
    check.checks_run += 1
    if state.status in ("invited", "in_progress") and check.status in OPEN:
        check.status = Status.INVITED if state.status == "invited" else Status.IN_PROGRESS
        check.save(update_fields=["status", "last_checked_at", "checks_run", "updated_at"])
        return check.status
    if state.status in ("cancelled", "expired"):
        check.status = Status.CANCELLED if state.status == "cancelled" else Status.EXPIRED
        check.save()
        publish(events.BackgroundCheckFailed(**_event_base(check), status=check.status))
        return check.status
    if state.status != "completed":
        check.save(update_fields=["last_checked_at", "checks_run", "updated_at"])
        return check.status
    with audit.track(check, action="completed"):
        check.status = Status.COMPLETED
        check.result = state.result or BackgroundCheck.Result.UNABLE
        check.completed_at = now()
        check.certificate_number = state.certificate_number or check.certificate_number
        check.certificate_issue_date = state.issue_date or check.certificate_issue_date
        check.report_url = state.report_url
        check.result_details = json.dumps(state.summary, default=str)
        check.invite_url = ""
        check.save()
    publish(events.BackgroundCheckCompleted(**_event_base(check), result=check.result))
    _attach(check)
    return check.status


def _attach(check: BackgroundCheck) -> None:
    """Put the result on the tutor's compliance record (FR-18-7 "attach results")."""
    requirement = check.requirement
    if requirement is None:
        return
    try:
        with transaction.atomic():
            record = compliance.submit(
                check.tutor,
                requirement,
                number=check.certificate_number or check.external_id,
                issue_date=check.certificate_issue_date or compliance.today(),
                expiry_date=check.certificate_expiry_date,
                notes=_("From %(provider)s check %(ref)s.")
                % {"provider": checks.info(check.provider).label, "ref": check.external_id},
            )
    except BusinessRuleViolation:
        _notify_staff(check, _("Add the check's details to the compliance record"))
        return
    BackgroundCheck.objects.filter(pk=check.pk).update(record=record)
    if check.result == BackgroundCheck.Result.CLEAR and get_setting(
        "compliance.checks_auto_verify"
    ):
        _verify_by_provider(record, check)


def _verify_by_provider(record: ComplianceRecord, check: BackgroundCheck) -> None:
    record = (
        ComplianceRecord.objects.select_for_update().select_related("requirement").get(pk=record.pk)
    )
    if record.expiry_date is not None and record.expiry_date <= compliance.today():
        return  # an expired certificate still needs a person
    with audit.track(record, action="verify"):
        record.status = ComplianceRecord.Status.VERIFIED
        record.verified_by = None
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
    compliance.evaluate(record.tutor)


@transaction.atomic
def poll(check_id: Any) -> str:
    """Ask the provider where the check is (webhook signal or polling timer)."""
    check = BackgroundCheck.objects.select_for_update().select_related("tutor").get(pk=check_id)
    if check.status in TERMINAL:
        return check.status
    if checks.info(check.provider).manual:
        return check.status  # staff record the outcome (review)
    try:
        state = checks.client(check.provider).fetch(
            _credentials(check.provider), check.external_id, _candidate(check)
        )
    except checks.CheckError as exc:
        logger.info("recruitment.check_poll_failed", check=str(check.pk), error=str(exc)[:200])
        return check.status
    return _apply(check, state)


@transaction.atomic
def recheck(check_id: Any) -> str:
    """Re-run a DBS Update Service status check; new information rejects the record."""
    check = BackgroundCheck.objects.select_for_update().select_related("tutor").get(pk=check_id)
    if check.status != Status.COMPLETED:
        return check.status
    try:
        state = checks.client(check.provider).fetch(
            _credentials(check.provider), check.external_id, _candidate(check)
        )
    except checks.CheckError:
        return "unavailable"
    check.last_checked_at = now()
    check.checks_run += 1
    check.result_details = json.dumps(state.summary, default=str)
    previous = check.result
    check.result = state.result or check.result
    check.save()
    if check.result == BackgroundCheck.Result.CLEAR or check.result == previous:
        return check.result
    publish(events.BackgroundCheckCompleted(**_event_base(check), result=check.result))
    if check.record_id:
        record = (
            ComplianceRecord.objects.select_for_update()
            .select_related("requirement")
            .get(pk=check.record_id)
        )
        with audit.track(record, action="reject"):
            record.status = ComplianceRecord.Status.REJECTED
            record.rejection_reason = _(
                "The DBS Update Service reports new information: ask for a new check."
            )
            record.save()
        publish(
            events.ComplianceRejected(
                subject_id=record.pk,
                tutor_id=str(record.tutor_id),
                requirement=record.requirement.key,
                reason=record.rejection_reason,
            )
        )
        compliance.evaluate(record.tutor)
    _notify_staff(check, _("New information on a DBS certificate"))
    return check.result


def _notify_staff(check: BackgroundCheck, title: str) -> None:
    from tutortrack.comms import services as comms

    comms.notify(
        "staff_compliance_submitted",
        (f"{title}: {check.tutor.full_name}", _("Review the check."), f"/tutors/{check.tutor_id}"),
        key=f"bgcheck:{check.pk}:{check.checks_run}",
    )


@transaction.atomic
def expire(check_id: Any) -> str:
    check = BackgroundCheck.objects.select_for_update().get(pk=check_id)
    if check.status not in OPEN:
        return check.status
    try:
        checks.client(check.provider).cancel(_credentials(check.provider), check.external_id)
    except checks.CheckError:
        logger.info("recruitment.check_cancel_failed", check=str(check.pk))
    with audit.track(check, action="expired"):
        check.status = Status.EXPIRED
        check.invite_url = ""
        check.save()
    publish(events.BackgroundCheckFailed(**_event_base(check), status=check.status))
    return check.status


def _signal(check: BackgroundCheck, name: str) -> None:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal_now

    from .check_processes import check_workflow_id

    wid = check_workflow_id(check.organisation_id, check.pk)

    def send() -> None:
        if WorkflowLink.objects.filter(workflow_id=wid, status="running").exists():
            signal_now(wid, name)

    transaction.on_commit(send)


@transaction.atomic
def cancel(check: BackgroundCheck, *, user: Any) -> BackgroundCheck:
    check = BackgroundCheck.objects.select_for_update().get(pk=check.pk)
    if check.status not in OPEN:
        raise BusinessRuleViolation(_("This check has already finished."))
    try:
        checks.client(check.provider).cancel(_credentials(check.provider), check.external_id)
    except checks.CheckError as exc:
        logger.info("recruitment.check_cancel_failed", check=str(check.pk), error=str(exc)[:200])
    with audit.track(check, action="cancel"):
        check.status = Status.CANCELLED
        check.invite_url = ""
        check.save()
    publish(events.BackgroundCheckFailed(**_event_base(check), status=check.status))
    _signal(check, "cancel")
    return check


@transaction.atomic
def record_outcome(
    check: BackgroundCheck,
    *,
    user: Any,
    result: str,
    certificate_number: str = "",
    expiry_date: Any = None,
    note: str = "",
) -> BackgroundCheck:
    """Staff record the outcome of a manual check (AU WWCC verification page) or confirm
    a "needs review" result after reading the report."""
    if not has_perm(user, "compliance.verify"):
        raise PermissionDenied()
    check = BackgroundCheck.objects.select_for_update().select_related("tutor").get(pk=check.pk)
    if result not in (
        BackgroundCheck.Result.CLEAR,
        BackgroundCheck.Result.CONSIDER,
        BackgroundCheck.Result.UNABLE,
    ):
        raise BusinessRuleViolation(_("Choose an outcome."))
    if check.status in OPEN and checks.info(check.provider).manual:
        check.certificate_expiry_date = expiry_date
        _apply(
            check,
            checks.CheckState(
                status="completed",
                result=result,
                certificate_number=certificate_number.strip(),
                summary={"recorded_by": str(user.pk), "note": note[:300]},
            ),
        )
        check.refresh_from_db()
    elif check.status == Status.COMPLETED:
        with audit.track(check, action="review"):
            check.result = result
            check.save()
    else:
        raise BusinessRuleViolation(_("There is no outcome to record yet."))
    with audit.track(check, action="reviewed"):
        check.reviewed_by = user
        check.reviewed_at = now()
        check.save()
    if check.record_id and result == BackgroundCheck.Result.CLEAR:
        record = ComplianceRecord.objects.get(pk=check.record_id)
        if record.status != ComplianceRecord.Status.VERIFIED:
            compliance.verify(record, user=user)
    _signal(check, "updated")
    return check


def details(check: BackgroundCheck, *, user: Any) -> dict[str, Any]:
    """The encrypted parts of a check (results, certificate, report link): audited."""
    if not has_perm(user, "compliance.checks.results"):
        raise PermissionDenied()
    audit.record_read(check, reason="background_check_result")
    try:
        summary = json.loads(check.result_details) if check.result_details else {}
    except ValueError:
        summary = {}
    return {
        "certificate_number": check.certificate_number,
        "report_url": check.report_url,
        "summary": summary,
        "purged": check.details_purged_at is not None,
    }


# --- webhooks ------------------------------------------------------------------------------------


def handle_webhook(provider: str, body: bytes, headers: dict[str, str]) -> bool:
    """Checkr webhooks: routed by the candidate id, then verified with the organisation's
    API key (HMAC). A valid event signals ``updated``; the workflow fetches the state."""
    if provider != "checkr":
        return False
    try:
        event: dict[str, Any] = json.loads(body or b"{}")
    except ValueError:
        return False
    obj = (event.get("data") or {}).get("object") or {}
    refs = [str(obj.get("candidate_id") or ""), str(obj.get("id") or "")]
    organisation_id = next(
        (o for o in (routes.organisation_for(provider, r) for r in refs if r) if o), None
    )
    if organisation_id is None:
        return False
    from .checks.checkr import verify_signature

    with tenant_context(organisation_id):
        conn = connection(provider)
        secret = conn.secret if conn is not None else ""
        if not verify_signature(secret, body, headers.get("X-Checkr-Signature", "")):
            return False
        check = (
            BackgroundCheck.objects.filter(provider=provider, status__in=OPEN)
            .filter(candidate_ref__in=[r for r in refs if r])
            .first()
            or BackgroundCheck.objects.filter(provider=provider, external_id__in=refs).first()
        )
        if check is not None:
            with transaction.atomic():
                _signal(check, "updated")
    return True


# --- retention (E29) -----------------------------------------------------------------------------


def purge_details(cutoff: Any, dry_run: bool, limit: int) -> int:
    """Clear results, certificate numbers and report links of checks finished before the
    cut-off; the check itself (provider, dates, outcome) stays as evidence."""
    from tutortrack.privacy.selectors import held_ids

    held = held_ids("people.tutor")
    qs = (
        BackgroundCheck.objects.filter(updated_at__lt=cutoff, details_purged_at__isnull=True)
        .filter(status__in=TERMINAL)
        .exclude(tutor_id__in=list(held))
    )
    ids = list(qs.values_list("pk", flat=True)[:limit])
    if dry_run:
        return len(ids)
    return BackgroundCheck.objects.filter(pk__in=ids).update(
        result_details="",
        report_url="",
        invite_url="",
        certificate_number="",
        details_purged_at=now(),
    )
