"""The erasure / anonymisation engine (E29-T06, FR-29-4).

An erasure is planned once (``plan``: resolve the person across the apps, check legal
holds, give every erased record a token label such as "Erased Student #12") and then runs
in idempotent steps, so ``ErasureWorkflow`` can retry any of them:

1. ``run_provider`` per registered provider (``<app>/privacy.py``): each app anonymises or
   deletes its own records. Financial records are never deleted: invoice lines keep their
   amounts with the student's name replaced, and the bill payer's details stay on invoices
   until ``privacy.financial_retention_years`` have passed (then the ``erased_financial``
   retention category anonymises them too);
2. ``erase_files``: the documents the providers released are deleted from storage;
3. ``revoke_logins``: memberships, sessions and tokens for the person end;
4. ``finish``: the audit summary; the personal search terms are dropped.

``erase_now`` runs every step inline (retention purges, tests).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import StoredFile
from tutortrack.core.sequences import next_value
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import registry
from .events import DataSubjectErased
from .models import DataSubjectRequest, ErasureRecord
from .registry import ErasureContext, Person
from .selectors import holds_for

logger = structlog.get_logger(__name__)


class ErasureBlocked(BusinessRuleViolation):
    problem_type = "erasure-blocked"
    title = "A legal hold blocks this erasure"


def retention_years() -> int:
    return int(get_setting("privacy.financial_retention_years") or 6)


def financial_cutoff() -> datetime:
    """Financial records dated on or after this are still inside the retention period."""
    return now() - timedelta(days=365 * retention_years() + retention_years() // 4)


def _kind_label(subject_type: str) -> str:
    kinds = {
        "people.student": _("Student"),
        "people.contact": _("Contact"),
        "people.client": _("Client"),
        "people.tutor": _("Tutor"),
        "identity.user": _("User"),
        "recruitment.application": _("Applicant"),
        "growth.affiliate": _("Affiliate"),
    }
    return str(kinds.get(subject_type, _("Person")))


def erased_label(subject_type: str) -> str:
    """A token that replaces a name: "Erased Student #1234" (numbered per organisation)."""
    number = next_value("privacy.erasure")
    return _("Erased %(kind)s #%(number)s") % {
        "kind": _kind_label(subject_type),
        "number": number,
    }


def _person(record: ErasureRecord) -> Person:
    terms = json.loads(record.scrub_terms) if record.scrub_terms else {}
    person = Person.restore(
        record.subject_type, record.subject_id, record.subjects.get("ids", {}), terms
    )
    person.context = {t: set(v) for t, v in record.subjects.get("context", {}).items()}
    person.label = record.labels.get(f"{record.subject_type}:{record.subject_id}", "")
    return person


def context_for(
    record: ErasureRecord, person: Person, *, include_financial: bool
) -> ErasureContext:
    ctx = ErasureContext(
        labels=dict(record.labels),
        financial_cutoff=financial_cutoff(),
        include_financial=include_financial,
    )
    ctx.prepare_scrub(person, person.label or _("Erased person"))
    return ctx


# --- planning -----------------------------------------------------------------------------------


def preview(subject_type: str, subject_id: str) -> dict[str, Any]:
    """What an erasure would cover, without changing anything (shown before approval)."""
    person = registry.resolve(subject_type, subject_id)
    holds = holds_for(person)
    return {
        "subjects": {t: len(ids) for t, ids in person.snapshot().items()},
        "holds": [{"id": str(h.pk), "reason": h.reason} for h in holds],
        "providers": [p.key for p in registry.providers() if p.erase is not None],
        "financial_retention_years": retention_years(),
    }


@transaction.atomic
def plan(
    subject_type: str,
    subject_id: str,
    *,
    reason: str = ErasureRecord.Reason.REQUEST,
    request: DataSubjectRequest | None = None,
) -> ErasureRecord:
    """Create (or return the existing) erasure record for a request or subject."""
    if request is not None:
        existing = ErasureRecord.objects.filter(request=request).first()
        if existing is not None:
            return existing
    person = registry.resolve(subject_type, subject_id)
    labels = {
        f"{t}:{i}": erased_label(t) for t, i in person.all_refs() if t in registry.KIND_LABELS
    }
    record = ErasureRecord.objects.create(
        request=request,
        reason=reason,
        subject_type=subject_type,
        subject_id=str(subject_id),
        subjects={
            "ids": person.snapshot(),
            "context": {t: sorted(ids) for t, ids in person.context.items() if ids},
        },
        labels=labels,
        scrub_terms=json.dumps(person.terms()),
    )
    audit.record(
        record,
        "plan",
        {"subjects": {t: len(v) for t, v in person.snapshot().items()}, "reason": reason},
        object_repr=labels.get(f"{subject_type}:{subject_id}", str(record)),
    )
    return record


def check_holds(record: ErasureRecord) -> list[str]:
    """Active legal holds that block this erasure (reasons only)."""
    return [h.reason for h in holds_for(_person(record))]


@transaction.atomic
def block(record: ErasureRecord, reasons: list[str]) -> ErasureRecord:
    record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
    if record.status == ErasureRecord.Status.BLOCKED:
        return record
    record.status = ErasureRecord.Status.BLOCKED
    record.scrub_terms = ""
    record.report = {**record.report, "blocked": reasons}
    record.save(update_fields=["status", "scrub_terms", "report", "updated_at"])
    audit.record(record, "erasure_blocked", {"holds": len(reasons)})
    return record


# --- steps (idempotent) -------------------------------------------------------------------------


def provider_keys() -> list[str]:
    return [p.key for p in registry.providers() if p.erase is not None]


@transaction.atomic
def run_provider(record: ErasureRecord, key: str) -> dict[str, Any]:
    record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
    if key in record.steps_done:
        result: dict[str, Any] = record.report.get(key, {})
        return result
    provider = registry.provider(key)
    if provider.erase is None:
        return {}
    person = _person(record)
    outcome = provider.erase(person, context_for(record, person, include_financial=False))
    record.status = ErasureRecord.Status.ERASING
    record.steps_done = [*record.steps_done, key]
    record.report = {**record.report, key: outcome.as_dict()}
    record.file_ids = sorted({*record.file_ids, *(str(f) for f in outcome.file_ids)})
    record.save(update_fields=["status", "steps_done", "report", "file_ids", "updated_at"])
    return outcome.as_dict()


def delete_stored_file(stored: StoredFile) -> None:
    """Delete the object from storage and blank the record (rows other records point at
    stay, so foreign keys never break)."""
    from botocore.exceptions import BotoCoreError, ClientError

    from tutortrack.core.storage.client import bucket, s3_client

    try:
        s3_client().delete_object(Bucket=bucket(), Key=stored.storage_key)
    except (BotoCoreError, ClientError):
        logger.warning("privacy.file_delete_failed", file_id=str(stored.pk))
    StoredFile.objects.filter(pk=stored.pk).update(
        filename="erased",
        checksum_sha256="",
        status=StoredFile.Status.REJECTED,
        owner_content_type=None,
        owner_object_id="",
        updated_at=now(),
    )


def erase_files(record: ErasureRecord) -> int:
    record = ErasureRecord.objects.get(pk=record.pk)
    if "files" in record.steps_done:
        return 0
    count = 0
    for stored in StoredFile.objects.filter(pk__in=record.file_ids).exclude(filename="erased"):
        delete_stored_file(stored)
        count += 1
    with transaction.atomic():
        record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
        record.steps_done = [*record.steps_done, "files"]
        record.report = {**record.report, "files": {"deleted": count}}
        record.save(update_fields=["steps_done", "report", "updated_at"])
    return count


@transaction.atomic
def revoke_logins(record: ErasureRecord) -> int:
    record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
    if "logins" in record.steps_done:
        return int(record.report.get("logins", {}).get("revoked", 0))
    person = _person(record)
    revoked = sum(p.revoke(person) for p in registry.providers() if p.revoke is not None)
    record.steps_done = [*record.steps_done, "logins"]
    record.report = {**record.report, "logins": {"revoked": revoked}}
    record.save(update_fields=["steps_done", "report", "updated_at"])
    return revoked


@transaction.atomic
def finish(record: ErasureRecord) -> ErasureRecord:
    record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
    if record.status == ErasureRecord.Status.COMPLETED:
        return record
    record.status = ErasureRecord.Status.COMPLETED
    record.completed_at = now()
    record.scrub_terms = ""
    record.financial_retained_until = now() + timedelta(days=365 * retention_years() + 2)
    record.save(
        update_fields=[
            "status",
            "completed_at",
            "scrub_terms",
            "financial_retained_until",
            "updated_at",
        ]
    )
    totals = {k: v for k, v in record.report.items() if isinstance(v, dict) and "anonymised" in v}
    audit.record(
        record,
        "erase",
        {
            "anonymised": sum(v["anonymised"] for v in totals.values()),
            "deleted": sum(v["deleted"] for v in totals.values()),
            "retained": sum(v["retained"] for v in totals.values()),
            "files": record.report.get("files", {}).get("deleted", 0),
        },
        object_repr=record.labels.get(f"{record.subject_type}:{record.subject_id}", ""),
    )
    publish(
        DataSubjectErased(
            subject_id=record.pk,
            person_type=record.subject_type,
            person_id=record.subject_id,
            reason=record.reason,
            request_id=str(record.request_id) if record.request_id else None,
        )
    )
    return record


def erase_financial(record: ErasureRecord) -> dict[str, Any]:
    """After the retention period: anonymise the bill payer's details on financial records
    too (``include_financial``). Run by the ``erased_financial`` retention category."""
    report: dict[str, Any] = {}
    with transaction.atomic():
        record = ErasureRecord.objects.select_for_update().get(pk=record.pk)
        if record.financial_erased_at is not None:
            return {}
        person = _person(record)
        person.label = record.labels.get(f"{record.subject_type}:{record.subject_id}", "")
        ctx = context_for(record, person, include_financial=True)
        for provider in registry.providers():
            if provider.erase is not None:
                report[provider.key] = provider.erase(person, ctx).as_dict()
        record.financial_erased_at = now()
        record.report = {**record.report, "financial": report}
        record.save(update_fields=["financial_erased_at", "report", "updated_at"])
        audit.record(record, "erase_financial", {"providers": len(report)})
    return report


# --- all at once --------------------------------------------------------------------------------


def erase_now(
    subject_type: str,
    subject_id: str,
    *,
    reason: str = ErasureRecord.Reason.REQUEST,
    request: DataSubjectRequest | None = None,
) -> ErasureRecord:
    """Plan and run a whole erasure inline. Raises ``ErasureBlocked`` under a legal hold."""
    record = plan(subject_type, subject_id, reason=reason, request=request)
    reasons = check_holds(record)
    if reasons:
        block(record, reasons)
        raise ErasureBlocked(_("A legal hold applies to this person."))
    for key in provider_keys():
        run_provider(record, key)
    erase_files(record)
    revoke_logins(record)
    return finish(record)
