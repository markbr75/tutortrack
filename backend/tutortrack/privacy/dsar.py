"""Data subject requests (E29-T05, FR-29-4): intake, identity verification, statutory
deadline, export compilation, redaction, secure delivery and erasure approval.

The process itself is ``DataSubjectRequestWorkflow`` (``processes.py``): staff decisions
here update the request and signal the workflow; the workflow's activities call the
``workflow_*`` functions below.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.sequences import next_number
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import erasure, export, notifications, subjects
from .events import (
    DataRequestClosed,
    DataRequestDelivered,
    DataRequestReceived,
    DataRequestVerified,
)
from .models import DataSubjectRequest, ErasureRecord

Request = DataSubjectRequest
PROCESS = "dsar"
MAX_EXTENSION_DAYS = 60  # UK GDPR: up to two further months for complex requests
REMINDER_DAYS = (7, 2, 0)  # before the deadline; 0 = the deadline itself (overdue)

CHECKS: dict[str, Any] = {
    "identity": gettext_lazy("Identity confirmed (signed-in account, or ID checked)"),
    "matches_records": gettext_lazy("Details match our records"),
    "authority": gettext_lazy("Authority to act confirmed (parent, guardian or representative)"),
}


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


def workflow_id_for(request: Request) -> str:
    from tutortrack.core.workflows import workflow_id

    return workflow_id(PROCESS, request.organisation_id, request.pk)


def _signal(request: Request, name: str) -> None:
    """Signal the running workflow (after commit). Requests logged before the workflow
    started simply pick the change up when it reads the state."""
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal

    wid = workflow_id_for(request)
    if WorkflowLink.objects.filter(workflow_id=wid, status="running").exists():
        signal(wid, name)


def required_checks(request: Request) -> list[str]:
    keys = ["identity", "matches_records"]
    if request.relationship != Request.Relationship.SELF:
        keys.append("authority")
    return keys


def _staff_link(request: Request) -> str:
    return notifications.admin_link(f"/privacy/requests/{request.pk}")


# --- intake -------------------------------------------------------------------------------------


@transaction.atomic
def log_request(
    *,
    kind: str,
    subject_type: str,
    subject_id: str,
    requester_name: str,
    requester_email: str = "",
    relationship: str = Request.Relationship.SELF,
    channel: str = Request.Channel.EMAIL,
    details: str = "",
    received_at: datetime | None = None,
    requester_user: Any = None,
) -> Request:
    """Log a request (staff, or the person in the portal). Starts the deadline clock."""
    if kind not in Request.Kind.values:
        raise _invalid("kind", _("Choose access, portability or erasure."))
    if not subjects.is_valid(subject_type, str(subject_id)):
        raise NotFound(_("Person not found."))
    received = received_at or now()
    if received > now() + timedelta(minutes=5):
        raise _invalid("received_at", _("The date received can't be in the future."))
    days = int(get_setting("privacy.dsar_deadline_days") or 30)
    request = Request.objects.create(
        reference=next_number("privacy.dsar", prefix="DSAR-", padding=5),
        kind=kind,
        channel=channel,
        subject_type=subject_type,
        subject_id=str(subject_id),
        subject_label=subjects.label(subject_type, str(subject_id))[:200],
        requester_user=requester_user,
        requester_name=requester_name[:200],
        requester_email=requester_email.strip().lower(),
        relationship=relationship,
        details=details,
        received_at=received,
        due_at=received + timedelta(days=days),
        checks={},
    )
    if requester_user is not None and relationship == Request.Relationship.SELF:
        # Signed in to the portal: the login is the identity check.
        request.checks = {"identity": True}
        request.save(update_fields=["checks", "updated_at"])
    request.workflow_id = workflow_id_for(request)
    request.save(update_fields=["workflow_id", "updated_at"])
    audit.record(request, "create", {"kind": [None, kind], "channel": [None, channel]})
    publish(
        DataRequestReceived(subject_id=request.pk, kind=kind, due_at=request.due_at.isoformat())
    )
    notifications.send(
        "privacy_dsar_staff",
        (
            _("New data request %(ref)s") % {"ref": request.reference},
            _("Due by %(date)s.") % {"date": notifications.local_date(request.due_at)},
            _staff_link(request),
        ),
        key=f"received:{request.pk}",
    )
    return request


def _locked(request: Request) -> Request:
    return Request.objects.select_for_update().get(pk=request.pk)


def _require_open(request: Request) -> None:
    if not request.is_open:
        raise BusinessRuleViolation(_("This request is closed."))


@transaction.atomic
def update_checks(
    request: Request, checks: dict[str, bool], *, note: str = "", user: Any = None
) -> Request:
    """Tick the identity verification checklist; when every required check is done the
    request is verified and the workflow moves on."""
    request = _locked(request)
    _require_open(request)
    unknown = set(checks) - set(CHECKS)
    if unknown:
        raise _invalid("checks", _("Unknown check: %(key)s") % {"key": sorted(unknown)[0]})
    was_verified = request.verified_at is not None
    with audit.track(request, action="verify"):
        request.checks = {**request.checks, **{k: bool(v) for k, v in checks.items()}}
        if note:
            request.verification_note = note[:500]
        verified = all(request.checks.get(k) for k in required_checks(request))
        if verified and not was_verified:
            request.verified_at = now()
            request.verified_by = user
            if request.status == Request.Status.RECEIVED:
                request.status = Request.Status.IN_PROGRESS
        request.save()
    if request.verified_at is not None and not was_verified:
        publish(DataRequestVerified(subject_id=request.pk, kind=request.kind))
        _signal(request, "identity_verified")
    return request


@transaction.atomic
def extend(request: Request, *, days: int, reason: str) -> Request:
    """Extend the deadline for a complex request (up to two further months in total)."""
    request = _locked(request)
    _require_open(request)
    if not reason.strip():
        raise _invalid("reason", _("Say why the request needs longer."))
    base = int(get_setting("privacy.dsar_deadline_days") or 30)
    new_due = request.due_at + timedelta(days=days)
    if days < 1 or new_due > request.received_at + timedelta(days=base + MAX_EXTENSION_DAYS):
        raise _invalid("days", _("The deadline can be extended by up to two months in total."))
    with audit.track(request, action="extend"):
        request.due_at = new_due
        request.extended_at = now()
        request.extension_reason = reason[:500]
        request.save()
    _signal(request, "deadline_changed")
    return request


@transaction.atomic
def close(request: Request, *, status: str, reason: str = "") -> Request:
    """Reject or cancel (staff), or complete (the workflow)."""
    request = _locked(request)
    if not request.is_open:
        return request
    if status in {Request.Status.REJECTED, Request.Status.CANCELLED} and not reason.strip():
        raise _invalid("reason", _("Give a reason; the requester is told it."))
    with audit.track(request, action=status):
        request.status = status
        request.closed_at = now()
        request.close_reason = reason[:500]
        request.token_hash = ""
        request.save()
    publish(DataRequestClosed(subject_id=request.pk, kind=request.kind, status=status))
    if status in {Request.Status.REJECTED, Request.Status.CANCELLED}:
        notifications.send(
            "privacy_dsar_requester",
            (
                _("Your data request %(ref)s") % {"ref": request.reference},
                _("We have closed your request: %(reason)s") % {"reason": reason},
                "",
                request,
            ),
            key=f"closed:{request.pk}",
        )
        _signal(request, "closed")
    return request


@transaction.atomic
def set_redactions(
    request: Request, redactions: list[dict[str, Any]], *, user: Any = None
) -> Request:
    request = _locked(request)
    if request.kind == Request.Kind.ERASURE or request.status != Request.Status.IN_REVIEW:
        raise BusinessRuleViolation(_("Redactions are set while the export is in review."))
    cleaned = []
    for r in redactions:
        if r.get("file_id"):
            cleaned.append({"file_id": str(r["file_id"]), "reason": str(r.get("reason", ""))[:200]})
        elif r.get("section") and r.get("record_id"):
            item = {"section": str(r["section"]), "record_id": str(r["record_id"])}
            if r.get("field"):
                item["field"] = str(r["field"])
            item["reason"] = str(r.get("reason", ""))[:200]
            cleaned.append(item)
        else:
            raise _invalid("redactions", _("Each redaction needs a section and record, or a file."))
    with audit.track(request, action="redact"):
        request.redactions = cleaned
        request.save()
    return request


@transaction.atomic
def approve_redactions(request: Request, *, user: Any = None) -> Request:
    request = _locked(request)
    if request.kind == Request.Kind.ERASURE or request.status != Request.Status.IN_REVIEW:
        raise BusinessRuleViolation(_("The export isn't waiting for review."))
    with audit.track(request, action="approve_export"):
        request.redactions_approved_at = now()
        request.redactions_approved_by = user
        request.save()
    _signal(request, "redaction_approved")
    return request


@transaction.atomic
def approve_erasure(request: Request, *, user: Any = None) -> Request:
    request = _locked(request)
    if request.kind != Request.Kind.ERASURE or request.status != Request.Status.IN_REVIEW:
        raise BusinessRuleViolation(_("The erasure isn't waiting for approval."))
    preview = erasure.preview(request.subject_type, request.subject_id)
    if preview["holds"]:
        raise BusinessRuleViolation(
            _("A legal hold applies to this person; release it first or reject the request."),
            extra={"code": "legal_hold"},
        )
    with audit.track(request, action="approve_erasure"):
        request.erasure_approved_at = now()
        request.erasure_approved_by = user
        request.save()
    _signal(request, "erasure_approved")
    return request


def preview_export(request: Request) -> dict[str, Any]:
    """The compiled draft for review (logged as a sensitive read)."""
    if request.draft_file is None:
        raise BusinessRuleViolation(_("The export hasn't been compiled yet."))
    audit.record_read(request, "dsar_export_review")
    return export.load_draft(request)


# --- secure delivery ----------------------------------------------------------------------------


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def download(token: str) -> tuple[Request, str]:
    """Resolve a delivery link: returns the request and a short-lived storage URL."""
    from tutortrack.core.storage.client import bucket, presign_client
    from tutortrack.core.storage.services import safe_filename

    request = (
        Request.objects.select_related("package_file").filter(token_hash=_token_hash(token)).first()
        if token
        else None
    )
    if (
        request is None
        or request.package_file is None
        or request.link_expires_at is None
        or request.link_expires_at < now()
    ):
        raise NotFound(_("This link is invalid or has expired."))
    with transaction.atomic():
        Request.objects.filter(pk=request.pk).update(
            downloaded_at=request.downloaded_at or now(),
            download_count=request.download_count + 1,
        )
        audit.record_read(request, "dsar_download")
    url = presign_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket(),
            "Key": request.package_file.storage_key,
            "ResponseContentDisposition": (
                f'attachment; filename="{safe_filename(request.package_file.filename)}"'
            ),
            "ResponseContentType": "application/zip",
        },
        ExpiresIn=300,
    )
    return request, url


# --- workflow steps (activities call these; each is idempotent) --------------------------------


def workflow_state(request_id: str) -> dict[str, Any]:
    request = Request.objects.get(pk=request_id)
    reminders = [
        {"days": d, "at": (request.due_at - timedelta(days=d)).isoformat()}
        for d in REMINDER_DAYS
        if _reminder_key(request, d) not in request.reminders_sent
    ]
    return {
        "status": request.status,
        "kind": request.kind,
        "open": request.is_open,
        "verified": request.verified_at is not None,
        "redactions_approved": request.redactions_approved_at is not None,
        "erasure_approved": request.erasure_approved_at is not None,
        "due_at": request.due_at.isoformat(),
        "reminders": reminders,
        "delivered": request.delivered_at is not None,
        "link_expires_at": request.link_expires_at.isoformat() if request.link_expires_at else "",
    }


def _reminder_key(request: Request, days: int) -> str:
    return f"due:{days}:{request.due_at.date().isoformat()}"


@transaction.atomic
def send_reminder(request_id: str, days: int | None = None) -> str:
    """A deadline reminder (7 days, 2 days, overdue) to the staff handling requests. The
    workflow says which one is due (``days``, by its own clock); without it, the next one
    due by the wall clock is sent. Each is sent once per deadline."""
    request = _locked(Request.objects.get(pk=request_id))
    if not request.is_open:
        return "closed"
    if days is None:
        due = [
            d
            for d in REMINDER_DAYS
            if _reminder_key(request, d) not in request.reminders_sent
            and request.due_at - timedelta(days=d) <= now()
        ]
        if not due:
            return ""
        days = due[0]
    key = _reminder_key(request, days)
    if key in request.reminders_sent:
        return ""
    # Earlier stages that were never sent (the deadline moved, or a long outage) are
    # skipped: only the most urgent reminder goes out.
    request.reminders_sent = [
        *request.reminders_sent,
        *(
            _reminder_key(request, d)
            for d in REMINDER_DAYS
            if d >= days and _reminder_key(request, d) not in request.reminders_sent
        ),
    ]
    request.save(update_fields=["reminders_sent", "updated_at"])
    title = (
        _("Data request %(ref)s is overdue") % {"ref": request.reference}
        if days == 0
        else _("Data request %(ref)s is due in %(days)s days")
        % {"ref": request.reference, "days": days}
    )
    notifications.send(
        "privacy_dsar_staff",
        (
            title,
            _("Status: %(status)s") % {"status": request.get_status_display()},
            _staff_link(request),
        ),
        key=f"{key}:{request.pk}",
    )
    return key


@transaction.atomic
def compile_for_review(request_id: str) -> dict[str, Any]:
    request = _locked(Request.objects.get(pk=request_id))
    if not request.is_open:
        return {"status": request.status}
    if request.kind == Request.Kind.ERASURE:
        preview = erasure.preview(request.subject_type, request.subject_id)
        request.summary = {"erasure": preview}
    elif request.draft_file is None:
        stored = export.compile_draft(request)
        request.draft_file = stored
        request.summary = export.summary_of(export.load_draft(request))
    request.status = Request.Status.IN_REVIEW
    request.save(update_fields=["draft_file", "summary", "status", "updated_at"])
    audit.record(request, "compile", {"summary": request.summary})
    notifications.send(
        "privacy_dsar_staff",
        (
            _("Data request %(ref)s is ready for review") % {"ref": request.reference},
            _("Review the export and any redactions, then approve it.")
            if request.kind != Request.Kind.ERASURE
            else _("Review what will be erased, then approve it."),
            _staff_link(request),
        ),
        key=f"review:{request.pk}",
    )
    return {"status": request.status, "summary": request.summary}


def deliver(request_id: str) -> str:
    """Build the package and email the requester a single-purpose, expiring link."""
    from tutortrack.comms.catalogue import tenant_link

    request = Request.objects.get(pk=request_id)
    if request.delivered_at is not None:
        return request.link_expires_at.isoformat() if request.link_expires_at else ""
    package = export.build_package(request)
    raw = secrets.token_urlsafe(32)
    days = int(get_setting("privacy.dsar_link_days") or 7)
    with transaction.atomic():
        request = _locked(request)
        request.package_file = package
        request.token_hash = _token_hash(raw)
        request.delivered_at = now()
        request.link_expires_at = request.delivered_at + timedelta(days=days)
        request.status = Request.Status.DELIVERED
        request.save()
        audit.record(request, "deliver", {"expires": request.link_expires_at.isoformat()})
        publish(
            DataRequestDelivered(
                subject_id=request.pk, link_expires_at=request.link_expires_at.isoformat()
            )
        )
        notifications.send(
            "privacy_dsar_requester",
            (
                _("Your data is ready (%(ref)s)") % {"ref": request.reference},
                _(
                    "Download a copy of your personal data with the link below. It works until "
                    "%(date)s."
                )
                % {"date": notifications.local_date(request.link_expires_at)},
                tenant_link(f"/api/v1/data-export/{raw}"),
                request,
            ),
            key=f"delivered:{request.pk}",
            immediate=True,
        )
    return request.link_expires_at.isoformat()


def expire_link(request_id: str) -> str:
    """The link expired: delete the package and draft, complete the request."""
    request = Request.objects.select_related("package_file", "draft_file").get(pk=request_id)
    for stored in (request.package_file, request.draft_file):
        if stored is not None and stored.filename != "erased":
            erasure.delete_stored_file(stored)
    with transaction.atomic():
        request = _locked(request)
        request.token_hash = ""
        request.save(update_fields=["token_hash", "updated_at"])
    close(request, status=Request.Status.COMPLETED)
    return Request.Status.COMPLETED


@transaction.atomic
def mark_erasing(request_id: str) -> str:
    request = _locked(Request.objects.get(pk=request_id))
    if request.status == Request.Status.IN_REVIEW:
        request.status = Request.Status.ERASING
        request.save(update_fields=["status", "updated_at"])
    return request.status


def finish_erasure(request_id: str, outcome: str) -> str:
    request = Request.objects.get(pk=request_id)
    status = Request.Status.BLOCKED if outcome == "blocked" else Request.Status.COMPLETED
    close(request, status=status, reason=_("A legal hold applies.") if outcome == "blocked" else "")
    if status == Request.Status.COMPLETED:
        with transaction.atomic():
            notifications.send(
                "privacy_dsar_requester",
                (
                    _("Your data has been erased (%(ref)s)") % {"ref": request.reference},
                    _(
                        "We have erased your personal data. We keep only what the law requires "
                        "(for example invoices), with your details minimised."
                    ),
                    "",
                    request,
                ),
                key=f"erased:{request.pk}",
            )
    return status


def erasure_record(request: Request) -> ErasureRecord | None:
    return ErasureRecord.objects.filter(request=request).first()
