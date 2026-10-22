"""Retention policies and the purge (E29-T07, FR-29-5).

Categories are defined in code by the apps that own the data (``RetentionCategory`` in
``<app>/privacy.py``); each organisation has a ``RetentionPolicy`` per category with its
period. ``RetentionPurgeWorkflow`` (a nightly Temporal Schedule per organisation, see
``processes.py``) first reports what is due (dry run), then purges or anonymises in
batches and tells the admins. Legal holds are always skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from . import erasure, notifications, registry
from .events import RetentionRunCompleted
from .models import ErasureRecord, RetentionPolicy, RetentionRun
from .registry import RetentionCategory

logger = structlog.get_logger(__name__)

BATCH = 100
COUNT_LIMIT = 100_000


def ensure_policies() -> list[RetentionPolicy]:
    """One policy per registered category (idempotent; new categories get their default)."""
    existing = {p.category: p for p in RetentionPolicy.objects.all()}
    for category in registry.retention_categories():
        if category.key not in existing:
            existing[category.key] = RetentionPolicy.objects.create(
                category=category.key, period_days=category.default_days
            )
    return [existing[c.key] for c in registry.retention_categories() if c.key in existing]


@transaction.atomic
def update_policy(
    policy: RetentionPolicy, *, period_days: int | None = None, enabled: bool | None = None
) -> RetentionPolicy:
    category = registry.retention_category(policy.category)
    if category is None:
        raise BusinessRuleViolation(_("Unknown retention category."))
    minimum = {"audit_logs": 365 * 7, "erased_financial": 1, "unclaimed_public_uploads": 1}.get(
        policy.category, 30
    )
    if period_days is not None and period_days < minimum:
        message = _("Keep this for at least %(days)s days.") % {"days": minimum}
        raise BusinessRuleViolation(message, extra={"errors": {"period_days": [message]}})
    with audit.track(policy):
        if period_days is not None:
            policy.period_days = period_days
        if enabled is not None:
            policy.enabled = enabled
        policy.save()
    return policy


def cutoff_for(policy: RetentionPolicy) -> datetime:
    return now() - timedelta(days=policy.period_days)


def _policies() -> list[tuple[RetentionPolicy, RetentionCategory]]:
    out = []
    for policy in ensure_policies():
        category = registry.retention_category(policy.category)
        if category is not None and policy.enabled:
            out.append((policy, category))
    return out


def due_count(policy: RetentionPolicy, category: RetentionCategory) -> int:
    cutoff = cutoff_for(policy)
    if category.find is not None:
        return len(category.find(cutoff, COUNT_LIMIT))
    if category.purge is not None:
        return category.purge(cutoff, True, COUNT_LIMIT)
    return 0


# --- runs ---------------------------------------------------------------------------------------


@transaction.atomic
def start_run(
    *, dry_run: bool, trigger: str = "schedule", user: Any = None, workflow_id: str = ""
) -> RetentionRun:
    run = RetentionRun.objects.create(
        dry_run=dry_run,
        trigger=trigger,
        started_at=now(),
        requested_by=user,
        workflow_id=workflow_id,
    )
    audit.record_create(run)
    return run


@transaction.atomic
def dry_run_report(run: RetentionRun) -> dict[str, Any]:
    run = RetentionRun.objects.select_for_update().get(pk=run.pk)
    if run.report:
        return dict(run.report)
    report = {
        policy.category: {"due": due_count(policy, category), "done": 0, "days": policy.period_days}
        for policy, category in _policies()
    }
    run.report = report
    run.save(update_fields=["report", "updated_at"])
    return report


def purge_batch(run: RetentionRun, category_key: str, limit: int = BATCH) -> int:
    """Purge or anonymise up to ``limit`` items of one category; returns how many."""
    policy = RetentionPolicy.objects.filter(category=category_key, enabled=True).first()
    category = registry.retention_category(category_key)
    if policy is None or category is None:
        return 0
    cutoff = cutoff_for(policy)
    done = 0
    if category.find is not None:
        for subject_type, subject_id in category.find(cutoff, limit):
            try:
                erasure.erase_now(subject_type, subject_id, reason=ErasureRecord.Reason.RETENTION)
                done += 1
            except erasure.ErasureBlocked:
                logger.info("privacy.retention_held", category=category_key)
    elif category.purge is not None:
        with transaction.atomic():
            done = category.purge(cutoff, False, limit)
    if done:
        with transaction.atomic():
            run = RetentionRun.objects.select_for_update().get(pk=run.pk)
            entry = dict(run.report.get(category_key, {"due": 0, "done": 0}))
            entry["done"] = int(entry.get("done", 0)) + done
            run.report = {**run.report, category_key: entry}
            run.save(update_fields=["report", "updated_at"])
    return done


@transaction.atomic
def finish_run(run: RetentionRun, *, status: str = RetentionRun.Status.COMPLETED) -> RetentionRun:
    run = RetentionRun.objects.select_for_update().get(pk=run.pk)
    if run.finished_at is not None:
        return run
    run.status = status
    run.finished_at = now()
    run.save(update_fields=["status", "finished_at", "updated_at"])
    due = sum(int(v.get("due", 0)) for v in run.report.values())
    done = sum(int(v.get("done", 0)) for v in run.report.values())
    audit.record(run, "complete", {"due": due, "done": done, "dry_run": run.dry_run})
    publish(RetentionRunCompleted(subject_id=run.pk, dry_run=run.dry_run, due=due, done=done))
    if due or done:
        title = (
            _("Retention report: %(n)s items are past their retention period") % {"n": due}
            if run.dry_run
            else _("Retention purge: %(n)s items purged or anonymised") % {"n": done}
        )
        from .selectors import retention_area_label

        body = "\n".join(
            f"{retention_area_label(k)}: {v.get('done' if not run.dry_run else 'due', 0)}"
            for k, v in sorted(run.report.items())
        )
        notifications.send(
            "privacy_retention_report",
            (title, body, notifications.admin_link("/privacy/retention")),
            key=f"run:{run.pk}",
        )
    return run


def due_categories(run: RetentionRun) -> list[str]:
    return [k for k, v in run.report.items() if int(v.get("due", 0)) > 0]


# --- built-in categories ------------------------------------------------------------------------


def _purge_audit(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """Audit entries older than the period. The table is append-only for the application
    role, so the delete runs on the platform connection, limited to the organisation in
    context and opted in with ``tutortrack.audit_purge`` (core migration 0002)."""
    from django.db import connections

    from tutortrack.core.context import require_organisation_id
    from tutortrack.core.db import PLATFORM_DB_ALIAS
    from tutortrack.core.models import AuditEntry

    if dry_run:
        return AuditEntry.objects.filter(created_at__lt=cutoff).count()
    org_id = require_organisation_id()
    with (
        transaction.atomic(using=PLATFORM_DB_ALIAS),
        connections[PLATFORM_DB_ALIAS].cursor() as cursor,
    ):
        cursor.execute("SET LOCAL tutortrack.audit_purge = 'on'")
        cursor.execute(
            "DELETE FROM core_auditentry WHERE id IN (SELECT id FROM core_auditentry "
            "WHERE organisation_id = %s AND created_at < %s ORDER BY created_at LIMIT %s)",
            [str(org_id), cutoff, limit],
        )
        return int(cursor.rowcount)


def _purge_erased_financial(cutoff: datetime, dry_run: bool, limit: int) -> int:
    """Erased people's bill-payer details on financial records, once the financial
    retention period (``privacy.financial_retention_years``) has passed."""
    qs = ErasureRecord.objects.filter(
        status=ErasureRecord.Status.COMPLETED,
        financial_erased_at__isnull=True,
        financial_retained_until__lt=now(),
    )
    if dry_run:
        return qs.count()
    records = list(qs.order_by("financial_retained_until")[:limit])
    for record in records:
        erasure.erase_financial(record)
    return len(records)


registry.register_retention(
    RetentionCategory(
        key="audit_logs",
        label=gettext_lazy("Audit log entries"),
        default_days=365 * 7 + 2,
        purge=_purge_audit,
        order=900,
    )
)
registry.register_retention(
    RetentionCategory(
        key="erased_financial",
        label=gettext_lazy(
            "Bill-payer details on erased people's financial records (after the financial "
            "retention period)"
        ),
        default_days=1,
        purge=_purge_erased_financial,
        order=800,
    )
)
