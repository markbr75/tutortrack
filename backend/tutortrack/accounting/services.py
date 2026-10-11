"""Accounting integration writes (E23): the connection's options and mappings, switching
sync on, and the sync engine itself (FR-23-3).

The engine is a reconciliation: ``sync()`` builds the record's document from its current
state, compares its hash with what was last pushed, and creates or updates it in the
ledger under a row lock on the record's ``ExternalRecordLink``. Duplicate, retried or
reordered events are therefore harmless. Provider calls happen inside that lock so two
workflows never create the same contact twice; creates also carry an idempotency key.

Failures are classified (``errors.explain``): retryable ones (rate limits, outages)
re-raise for Temporal to retry with backoff; anything a person must fix (an archived
account, a missing mapping, a locked period) marks the record ``error`` with a readable
message and waits for "retry" or "skip" on the dashboard.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit, entitlements
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now
from tutortrack.integrations import services as integrations
from tutortrack.integrations.models import IntegrationConnection
from tutortrack.integrations.providers import AuthError, ProviderError

from . import builders, events, ratelimit
from .builders import Built, Context, Skip
from .errors import PeriodLocked, PrerequisiteMissing, explain
from .mappings import EXPORT, KINDS
from .models import (
    AccountingConnection,
    AccountMapping,
    ExternalRecordLink,
    SyncLogEntry,
    TaxMapping,
    TrackingMapping,
)
from .providers import PROVIDERS, client_for

logger = structlog.get_logger(__name__)
Status = ExternalRecordLink.Status
Outcome = SyncLogEntry.Outcome
FEATURE = "accounting_integrations"
SKIPPED_BY_USER = "skipped_by_user"


def _invalid(field: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field: [message]}})


# --- connections ----------------------------------------------------------------------------------


def active_connection() -> AccountingConnection | None:
    """The organisation's live, switched-on ledger connection (one at a time)."""
    return (
        AccountingConnection.objects.select_related("connection")
        .filter(
            enabled=True,
            connection__status__in=[
                IntegrationConnection.Status.ACTIVE,
                IntegrationConnection.Status.ERROR,
            ],
        )
        .order_by("-enabled_at")
        .first()
    )


@transaction.atomic
def on_connected(connection_id: Any) -> AccountingConnection:
    """``integration.connected`` for an accounting provider: our side of the connection,
    with the chart of accounts fetched (best effort; the page can refresh it)."""
    connection = IntegrationConnection.objects.get(pk=connection_id)
    conn, created = AccountingConnection.objects.get_or_create(
        connection=connection, defaults={"provider": connection.provider}
    )
    if created:
        audit.record_create(conn)
    try:
        refresh_chart(conn)
    except ProviderError as exc:
        logger.info("accounting.chart_failed", provider=conn.provider, error=str(exc)[:200])
    return conn


def refresh_chart(conn: AccountingConnection) -> AccountingConnection:
    """Fetch the company's details, lock date, accounts, tax codes and tracking."""
    try:
        creds = integrations.credentials(conn.connection)
        client = client_for(conn.provider)
        info = client.info(creds)
        chart = client.chart(creds)
    except ProviderError as exc:
        integrations.record_failure(conn.connection, exc)
        raise
    with transaction.atomic(), audit.track(conn, action="refresh"):
        conn.company_name = info.name[:255]
        conn.base_currency = info.base_currency[:3]
        conn.lock_date = info.lock_date
        conn.chart = {
            "accounts": [a.__dict__ for a in chart.accounts],
            "tax_codes": [t.__dict__ for t in chart.tax_codes],
            "tracking": [
                {"id": c.id, "name": c.name, "options": [list(o) for o in c.options]}
                for c in chart.tracking
            ],
        }
        conn.chart_fetched_at = now()
        conn.save()
    integrations.record_success(conn.connection)
    return conn


OPTION_FIELDS = ("mode", "start_date", "sync_bills", "attach_pdf", "lock_behaviour")


@transaction.atomic
def update_options(conn: AccountingConnection, **values: Any) -> AccountingConnection:
    conn = AccountingConnection.objects.select_for_update().get(pk=conn.pk)
    with audit.track(conn):
        for name in OPTION_FIELDS:
            if name in values:
                setattr(conn, name, values[name])
        conn.save()
    return conn


def _chart_lookup(conn: AccountingConnection | None) -> dict[str, dict[str, Any]]:
    if conn is None:
        return {}
    return {str(a["id"]): a for a in (conn.chart or {}).get("accounts", [])}


@transaction.atomic
def save_mappings(
    provider: str,
    *,
    accounts: list[dict[str, str]] | None = None,
    taxes: list[dict[str, Any]] | None = None,
    tracking: list[dict[str, Any]] | None = None,
    conn: AccountingConnection | None = None,
) -> None:
    """Replace a mapping set (whatever part is given). For ``export`` an account is its
    code; for a provider it must be one of the fetched accounts."""
    if provider not in (*PROVIDERS, EXPORT):
        raise _invalid("provider", _("Unknown mapping set."))
    chart = _chart_lookup(conn)
    if accounts is not None:
        keep: set[tuple[str, str]] = set()
        for row in accounts:
            kind, key, external = row["kind"], row.get("key") or "default", row["external_id"]
            if kind not in KINDS and kind != "purchase_tax":
                raise _invalid("accounts", _("Unknown mapping kind %(kind)s.") % {"kind": kind})
            if not external:
                continue
            found = chart.get(external, {})
            if provider != EXPORT and chart and kind != "purchase_tax" and not found:
                raise _invalid("accounts", _("That account isn't in the ledger; refresh it."))
            code = str(found.get("code", "")) if provider != EXPORT else external
            mapping, created = AccountMapping.objects.get_or_create(
                provider=provider, kind=kind, key=key, defaults={"external_id": external}
            )
            with audit.track(mapping):
                mapping.external_id = external
                mapping.code = code
                mapping.name = str(found.get("name", ""))[:200]
                mapping.save()
            if created:
                audit.record_create(mapping)
            keep.add((kind, key))
        for mapping in AccountMapping.objects.filter(provider=provider):
            if (mapping.kind, mapping.key) not in keep:
                audit.record(mapping, "delete")
                mapping.delete()
    if taxes is not None:
        keep_taxes: set[str] = set()
        for row in taxes:
            rate = row.get("tax_rate") or None
            if not row.get("external_id"):
                continue
            mapping = TaxMapping.objects.filter(provider=provider, tax_rate_id=rate).first()
            if mapping is None:
                mapping = TaxMapping(provider=provider, tax_rate_id=rate)
            with audit.track(mapping):
                mapping.external_id = str(row["external_id"])
                mapping.name = str(row.get("name", ""))[:200]
                mapping.save()
            keep_taxes.add(str(rate or ""))
        for mapping in TaxMapping.objects.filter(provider=provider):
            if str(mapping.tax_rate_id or "") not in keep_taxes:
                audit.record(mapping, "delete")
                mapping.delete()
    if tracking is not None:
        keep_branches: set[str] = set()
        for row in tracking:
            if not row.get("option_id"):
                continue
            mapping = TrackingMapping.objects.filter(
                provider=provider, branch_id=row["branch"]
            ).first() or TrackingMapping(provider=provider, branch_id=row["branch"])
            with audit.track(mapping):
                mapping.category_id = str(row["category_id"])
                mapping.option_id = str(row["option_id"])
                mapping.name = str(row.get("name", ""))[:200]
                mapping.save()
            keep_branches.add(str(row["branch"]))
        for mapping in TrackingMapping.objects.filter(provider=provider):
            if str(mapping.branch_id) not in keep_branches:
                audit.record(mapping, "delete")
                mapping.delete()


def enable(
    conn: AccountingConnection, *, backfill_from: date | None = None
) -> AccountingConnection:
    """Switch sync on once the mappings are complete (FR-23-1). Nothing before
    ``start_date`` (default today) syncs unless a backfill is asked for."""
    from .mappings import problems

    entitlements.require(FEATURE)
    if not conn.connection.is_live:
        raise BusinessRuleViolation(_("Reconnect the account first."))
    issues = problems(conn.provider, conn)
    if issues:
        raise BusinessRuleViolation(
            _("Finish the mappings before switching sync on."),
            extra={"errors": {"mappings": [i["message"] for i in issues]}},
        )
    with transaction.atomic():
        conn = AccountingConnection.objects.select_for_update().get(pk=conn.pk)
        others = AccountingConnection.objects.filter(enabled=True).exclude(pk=conn.pk)
        if others.exists():
            raise BusinessRuleViolation(_("Another accounting connection is already syncing."))
        with audit.track(conn, action="enable"):
            conn.enabled = True
            conn.enabled_at = now()
            if conn.start_date is None:
                from tutortrack.billing.services import org_today

                conn.start_date = org_today()
            conn.save()
        _ensure_schedule_later(conn)
    if backfill_from is not None:
        start_backfill(conn, backfill_from)
    return conn


def _ensure_schedule_later(conn: AccountingConnection) -> None:
    org_id, conn_id = conn.organisation_id, conn.pk

    def _ensure() -> None:
        from .processes import ensure_daily_schedule

        try:
            ensure_daily_schedule(org_id, conn_id)
        except Exception:  # Temporal down: the next enable or save retries
            logger.exception("accounting.schedule_failed")

    transaction.on_commit(_ensure)


@transaction.atomic
def disable(conn: AccountingConnection) -> AccountingConnection:
    conn = AccountingConnection.objects.select_for_update().get(pk=conn.pk)
    with audit.track(conn, action="disable"):
        conn.enabled = False
        conn.save()
    sid, org_id = conn.schedule_id, conn.organisation_id
    if sid:

        def _drop() -> None:
            from tutortrack.core.workflows.schedules import delete_schedule

            try:
                delete_schedule(org_id, sid)
            except Exception:
                logger.exception("accounting.schedule_delete_failed")

        transaction.on_commit(_drop)
    return conn


def record_schedule(conn_id: Any, schedule_id: str) -> None:
    AccountingConnection.objects.filter(pk=conn_id).update(schedule_id=schedule_id)


def disconnect(conn: AccountingConnection) -> AccountingConnection:
    """Revoke at the provider; ``integration.disconnected`` then switches sync off."""
    integrations.disconnect(conn.connection)
    conn.refresh_from_db()
    return conn


def on_disconnected(connection_id: Any) -> None:
    conn = AccountingConnection.objects.filter(connection_id=connection_id).first()
    if conn is not None and conn.enabled:
        disable(conn)


def on_connection_error(connection_id: Any, status: str, error: str) -> None:
    conn = AccountingConnection.objects.filter(connection_id=connection_id).first()
    if conn is None:
        return
    with transaction.atomic():
        publish(
            events.AccountingConnectionError(
                subject_id=conn.pk, provider=conn.provider, status=status, error=error[:300]
            )
        )


# --- the sync engine -----------------------------------------------------------------------------


def _link(conn: AccountingConnection, object_type: str, object_id: str) -> ExternalRecordLink:
    link, _created = ExternalRecordLink.objects.get_or_create(
        connection=conn,
        object_type=object_type,
        object_id=str(object_id),
        defaults={"provider": conn.provider, "label": builders.label_for(object_type, object_id)},
    )
    return link


def _log(link: ExternalRecordLink, outcome: str, message: str = "") -> None:
    SyncLogEntry.objects.create(link=link, outcome=outcome, message=message[:500])


def plan(object_type: str, object_id: str, *, workflow_id: str = "") -> dict[str, Any]:
    """What a sync workflow should do: prerequisites to sync first, then push (or not)."""
    conn = active_connection()
    if conn is None:
        return {"status": "disabled", "prerequisites": [], "push": False}
    if conn.mode == AccountingConnection.Mode.SUMMARY and object_type in builders.SALES_SIDE:
        return {"status": "skipped", "prerequisites": [], "push": False}
    container = object_type in builders.CONTAINERS
    if not container:
        with transaction.atomic():
            link = _link(conn, object_type, object_id)
            if workflow_id:
                ExternalRecordLink.objects.filter(pk=link.pk).update(workflow_id=workflow_id)
        if link.status == Status.SYNCED and object_type in builders.ISSUED_ONCE:
            return {"status": "synced", "prerequisites": [], "push": False}
        if link.status == Status.SKIPPED and link.error_code == SKIPPED_BY_USER:
            return {"status": "skipped", "prerequisites": [], "push": False}
    deps = builders.prerequisites(conn, object_type, object_id)
    return {"status": "ready", "prerequisites": [list(d) for d in deps], "push": not container}


def sync(
    object_type: str,
    object_id: str,
    *,
    inline: bool = False,
    backfill: bool = False,
    conn: AccountingConnection | None = None,
) -> str:
    """Push one record: ``synced``, ``skipped`` or ``error`` (needs a person). Retryable
    provider failures raise. ``inline`` syncs prerequisites first in this process
    (backfills); workflows run them as child workflows instead."""
    conn = conn or active_connection()
    if conn is None:
        return "disabled"
    object_id = str(object_id)
    if object_type in builders.CONTAINERS:
        results = [
            sync(t, i, inline=True, backfill=backfill, conn=conn)
            for t, i in builders.prerequisites(conn, object_type, object_id)
        ]
        return "error" if "error" in results else "synced"
    if inline:
        for dep_type, dep_id in builders.prerequisites(conn, object_type, object_id):
            result = sync(dep_type, dep_id, inline=True, backfill=backfill, conn=conn)
            if result == "error":
                break
    try:
        return _sync_one(conn, object_type, object_id, backfill=backfill)
    except ProviderError as exc:
        explained = explain(conn.provider, exc)
        if isinstance(exc, AuthError):
            integrations.record_failure(conn.connection, exc)
        if explained.retryable:
            note_retry(object_type, object_id, str(exc), conn=conn)
            raise
        record_error(object_type, object_id, explained.message, explained.code, conn=conn)
        return "error"


def _sync_one(
    conn: AccountingConnection, object_type: str, object_id: str, *, backfill: bool
) -> str:
    with transaction.atomic():
        link = ExternalRecordLink.objects.select_for_update().get(
            pk=_link(conn, object_type, object_id).pk
        )
        if link.status == Status.SYNCED and object_type in builders.ISSUED_ONCE:
            return "synced"
        if link.status == Status.SKIPPED and link.error_code == SKIPPED_BY_USER:
            return "skipped"  # until someone retries it
        ctx = Context(conn)
        if backfill:
            ctx.conn = _without_start(conn)
        try:
            built = builders.build(ctx, object_type, object_id)
        except Skip as skip:
            if link.status == Status.SYNCED:
                return "synced"  # e.g. the mode changed later: what's there stays
            _mark_skipped(link, str(skip))
            return "skipped"
        doc = _apply_lock_date(conn, built)
        digest = doc.content_hash()
        if link.status == Status.SYNCED and link.synced_hash == digest and not built.void:
            return "synced"
        if built.void and link.meta.get("voided"):
            return "synced"
        outcome = _push(conn, link, built, doc, digest)
        _wake_dependents(conn, object_type, object_id)
    integrations.record_success(conn.connection, synced=True)
    logger.info("accounting.synced", object_type=object_type, outcome=outcome)
    return "synced"


def _without_start(conn: AccountingConnection) -> AccountingConnection:
    copy = AccountingConnection.objects.get(pk=conn.pk)
    copy.start_date = None
    return copy


def _apply_lock_date(conn: AccountingConnection, built: Built) -> Any:
    doc = built.doc
    if built.void or not conn.lock_date or not doc.date:
        return doc
    if date.fromisoformat(doc.date) > conn.lock_date:
        return doc
    if conn.lock_behaviour == AccountingConnection.LockBehaviour.HOLD:
        raise PeriodLocked(
            _("The ledger is locked up to %(day)s; this record is held until it's unlocked.")
            % {"day": conn.lock_date.isoformat()}
        )
    first_open = conn.lock_date + timedelta(days=1)
    note = _("Originally dated %(day)s (period locked)") % {"day": doc.date}
    return doc.with_date(first_open.isoformat(), note)


def _push(
    conn: AccountingConnection, link: ExternalRecordLink, built: Built, doc: Any, digest: str
) -> str:
    creds = integrations.credentials(conn.connection)
    client = client_for(conn.provider)
    ratelimit.acquire(conn.connection.external_account_id or str(conn.pk), client.rate_limit)
    if built.void:
        client.void(creds, "invoice", link.external_id)
        outcome = Outcome.VOIDED
        external_id, number, meta = link.external_id, link.external_number, {"voided": True}
    else:
        pushed = client.push(
            creds, doc, link.external_id, idempotency_key=f"tt-{link.pk}-{digest[:16]}"
        )
        outcome = Outcome.CREATED if pushed.created else Outcome.UPDATED
        external_id, number, meta = pushed.external_id, pushed.number, dict(pushed.meta)
        if pushed.created and built.attach_invoice:
            _attach(client, creds, built.attach_invoice, external_id)
    link.external_id = external_id
    link.external_number = number or link.external_number
    link.synced_hash = digest
    link.status = Status.SYNCED
    link.error = ""
    link.error_code = ""
    link.label = built.label[:200]
    link.attempts += 1
    link.last_attempt_at = now()
    link.synced_at = now()
    link.posted_date = date.fromisoformat(doc.date) if doc.date else link.posted_date
    link.meta = {**link.meta, **built.meta, **meta}
    link.save()
    _log(link, outcome, doc.note)
    publish(
        events.AccountingSyncSucceeded(
            subject_id=link.pk,
            provider=conn.provider,
            object_type=link.object_type,
            object_id=link.object_id,
            external_id=external_id,
            outcome=str(outcome),
        )
    )
    return str(outcome)


def _attach(client: Any, creds: Any, invoice_id: str, external_id: str) -> None:
    from tutortrack.billing.models import Invoice
    from tutortrack.billing.pdf import invoice_pdf

    invoice = Invoice.objects.filter(pk=invoice_id).first()
    if invoice is None:
        return
    try:
        client.attach(creds, "invoice", external_id, f"{invoice.number}.pdf", invoice_pdf(invoice))
    except Exception as exc:  # the invoice is in; a missing PDF is not worth failing for
        logger.info("accounting.attach_failed", error=str(exc)[:200])


def _mark_skipped(link: ExternalRecordLink, reason: str, *, by_user: bool = False) -> None:
    changed = link.status != Status.SKIPPED or link.error != reason[:500]
    link.status = Status.SKIPPED
    link.error = reason[:500]
    link.error_code = SKIPPED_BY_USER if by_user else "skipped"
    link.last_attempt_at = now()
    link.save()
    if changed:
        _log(link, Outcome.SKIPPED, reason)


def _wake_dependents(conn: AccountingConnection, object_type: str, object_id: str) -> None:
    """Records that were waiting for this one try again (their workflows get "retry")."""
    waiting = ExternalRecordLink.objects.filter(
        connection=conn, status=Status.ERROR, error_code=PrerequisiteMissing.code
    ).exclude(workflow_id="")
    for link in waiting[:50]:
        deps = builders.prerequisites(conn, link.object_type, link.object_id)
        if (object_type, object_id) in deps:
            from tutortrack.core.workflows import signal

            signal(link.workflow_id, "retry")


def record_error(
    object_type: str,
    object_id: str,
    message: str,
    code: str = "rejected",
    *,
    conn: AccountingConnection | None = None,
) -> None:
    conn = conn or active_connection()
    if conn is None:
        return
    with transaction.atomic():
        link = ExternalRecordLink.objects.select_for_update().get(
            pk=_link(conn, object_type, object_id).pk
        )
        changed = link.status != Status.ERROR or link.error != message[:500]
        link.status = Status.ERROR
        link.error = message[:500]
        link.error_code = code[:40]
        link.attempts += 1
        link.last_attempt_at = now()
        link.save()
        _log(link, Outcome.ERROR, message)
        if changed:
            publish(
                events.AccountingSyncFailed(
                    subject_id=link.pk,
                    provider=conn.provider,
                    object_type=object_type,
                    object_id=str(object_id),
                    error_code=code,
                    error=message[:300],
                )
            )


def record_blocked(object_type: str, object_id: str) -> None:
    """A prerequisite didn't sync, so neither can this."""
    record_error(
        object_type,
        object_id,
        _("Waiting for a record it depends on (see the other errors), then retry this."),
        PrerequisiteMissing.code,
    )


def note_retry(
    object_type: str, object_id: str, message: str, *, conn: AccountingConnection | None = None
) -> None:
    conn = conn or active_connection()
    if conn is None:
        return
    with transaction.atomic():
        link = _link(conn, object_type, object_id)
        ExternalRecordLink.objects.filter(pk=link.pk).update(last_attempt_at=now())
        _log(link, Outcome.RETRYING, explain(conn.provider, ProviderError(message)).message)


def final_failure(object_type: str, object_id: str, message: str) -> None:
    """Temporal gave up retrying a transient failure: show it on the dashboard."""
    conn = active_connection()
    provider = conn.provider if conn is not None else ""
    explained = explain(provider, ProviderError(message))
    record_error(object_type, object_id, explained.message, "unavailable", conn=conn)


# --- dashboard actions ---------------------------------------------------------------------------


def retry(link: ExternalRecordLink) -> ExternalRecordLink:
    """Try again (after re-mapping, reconnecting or unlocking the period)."""
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal, start, workflow_id

    from .processes import AccountingSyncWorkflow, SyncInput

    with transaction.atomic():
        link = ExternalRecordLink.objects.select_for_update().get(pk=link.pk)
        with audit.track(link, action="retry"):
            link.status = Status.PENDING
            link.error_code = ""
            link.save()
        running = (
            link.workflow_id
            and WorkflowLink.objects.filter(workflow_id=link.workflow_id, status="running").exists()
        )
        if running:
            signal(link.workflow_id, "retry")
        else:
            wid = workflow_id(
                "acct-sync",
                link.organisation_id,
                link.object_type,
                link.object_id,
                f"retry-{link.attempts}-{now().strftime('%Y%m%d%H%M%S%f')}",
            )
            ExternalRecordLink.objects.filter(pk=link.pk).update(workflow_id=wid)
            start(
                AccountingSyncWorkflow,
                SyncInput(
                    organisation_id=str(link.organisation_id),
                    object_type=link.object_type,
                    object_id=link.object_id,
                ),
                id=wid,
                subject=("accounting_record", str(link.pk)),
            )
    link.refresh_from_db()
    return link


def retry_failed() -> int:
    links = list(ExternalRecordLink.objects.filter(status=Status.ERROR)[:200])
    for link in links:
        retry(link)
    return len(links)


def skip(link: ExternalRecordLink, *, reason: str = "") -> ExternalRecordLink:
    from tutortrack.core.models import WorkflowLink
    from tutortrack.core.workflows import signal

    with transaction.atomic():
        link = ExternalRecordLink.objects.select_for_update().get(pk=link.pk)
        if link.status == Status.SYNCED:
            raise BusinessRuleViolation(_("It's already in the ledger."))
        with audit.track(link, action="skip"):
            _mark_skipped(link, reason or _("Skipped from the sync dashboard."), by_user=True)
        if (
            link.workflow_id
            and WorkflowLink.objects.filter(workflow_id=link.workflow_id, status="running").exists()
        ):
            signal(link.workflow_id, "skip")
    return link


# --- backfill (E23-T06) --------------------------------------------------------------------------


def start_backfill(conn: AccountingConnection, since: date) -> str:
    from tutortrack.core.workflows import start, workflow_id

    from .processes import AccountingBackfillWorkflow, BackfillInput

    if not conn.enabled:
        raise BusinessRuleViolation(_("Switch sync on first."))
    wid = workflow_id(
        "acct-backfill", conn.organisation_id, conn.pk, now().strftime("%Y%m%d%H%M%S%f")
    )
    with transaction.atomic(), audit.track(conn, action="backfill"):
        conn.backfill = {
            "status": "running",
            "since": since.isoformat(),
            "workflow_id": wid,
            "synced": 0,
            "errors": 0,
            "skipped": 0,
            "started_at": now().isoformat(),
        }
        conn.save()
        start(
            AccountingBackfillWorkflow,
            BackfillInput(
                organisation_id=str(conn.organisation_id),
                connection_id=str(conn.pk),
                since=since.isoformat(),
            ),
            id=wid,
            subject=("accounting_connection", str(conn.pk)),
        )
    return wid


def backfill_kinds(conn: AccountingConnection) -> list[str]:
    kinds = []
    if conn.mode == AccountingConnection.Mode.SUMMARY:
        kinds.append("journal")
    else:
        kinds.extend(["invoice", "credit_note", "write_off", "payment", "refund"])
    kinds.append("provider_payout")
    if conn.sync_bills:
        kinds.extend(["bill", "bill_payment"])
    return kinds


def _candidates(conn: AccountingConnection, kind: str, since: date, after: str) -> list[str]:
    from tutortrack.billing.models import CreditNote, Invoice
    from tutortrack.core.time import local_date_range_to_utc
    from tutortrack.payments.models import Payment, ProviderPayout, Refund
    from tutortrack.payroll.models import Payout

    from .builders import Context as Ctx

    tz = str(Ctx(conn).tz)
    since_utc, _until = local_date_range_to_utc(since, since, tz)
    if kind == "journal":
        from tutortrack.billing.services import org_today

        day = since if not after else date.fromisoformat(after) + timedelta(days=1)
        out: list[str] = []
        while day < org_today() and len(out) < 1000:
            out.append(day.isoformat())
            day += timedelta(days=1)
        return out
    qs: Any
    if kind == "invoice":
        qs = Invoice.objects.filter(issue_date__gte=since).exclude(status=Invoice.Status.DRAFT)
    elif kind == "credit_note":
        qs = CreditNote.objects.filter(issued_at__gte=since_utc)
    elif kind == "write_off":
        qs = Invoice.objects.filter(
            status=Invoice.Status.WRITTEN_OFF, written_off_at__gte=since_utc
        )
    elif kind == "payment":
        qs = Payment.objects.filter(received_at__gte=since_utc).exclude(
            status__in=[Payment.Status.PENDING, Payment.Status.FAILED]
        )
    elif kind == "refund":
        qs = Refund.objects.filter(status=Refund.Status.SUCCEEDED, created_at__gte=since_utc)
    elif kind == "provider_payout":
        qs = ProviderPayout.objects.filter(created_at__gte=since_utc)
    elif kind == "bill":
        qs = Payout.objects.filter(pay_run__approved_at__gte=since_utc)
    else:
        qs = Payout.objects.filter(status=Payout.Status.PAID, paid_at__gte=since_utc)
    if after:
        qs = qs.filter(pk__gt=after)
    return [str(pk) for pk in qs.order_by("pk").values_list("pk", flat=True)]


def backfill_batch(
    connection_id: str, since: date, checkpoint: dict[str, Any], batch_size: int
) -> dict[str, Any]:
    """Sync the next ``batch_size`` records after ``checkpoint`` (resumable; records
    already in the ledger are no-ops)."""
    conn = AccountingConnection.objects.select_related("connection").get(pk=connection_id)
    if not conn.enabled:
        return {"done": True, "checkpoint": checkpoint, "cancelled": True}
    kinds = backfill_kinds(conn)
    index, after = int(checkpoint.get("kind", 0)), str(checkpoint.get("after", ""))
    counts = {"synced": 0, "errors": 0, "skipped": 0}
    done_items = 0
    while index < len(kinds) and done_items < batch_size:
        kind = kinds[index]
        ids = _candidates(conn, kind, since, after)[: batch_size - done_items]
        if not ids:
            index, after = index + 1, ""
            continue
        for object_id in ids:
            result = sync(kind, object_id, inline=True, backfill=True, conn=conn)
            counts[
                "synced" if result == "synced" else "errors" if result == "error" else "skipped"
            ] += 1
            after = object_id
            done_items += 1
    done = index >= len(kinds)
    new_checkpoint = {"kind": index, "after": after}
    with transaction.atomic():
        fresh = AccountingConnection.objects.select_for_update().get(pk=conn.pk)
        progress = dict(fresh.backfill)
        for key, value in counts.items():
            progress[key] = int(progress.get(key, 0)) + value
        progress["checkpoint"] = new_checkpoint
        progress["status"] = "done" if done else "running"
        if done:
            progress["finished_at"] = now().isoformat()
        fresh.backfill = progress
        fresh.save(update_fields=["backfill", "updated_at"])
    return {"done": done, "checkpoint": new_checkpoint, **counts}


def cancel_backfill(conn: AccountingConnection) -> AccountingConnection:
    from tutortrack.core.workflows import signal

    wid = str(conn.backfill.get("workflow_id", ""))
    with transaction.atomic(), audit.track(conn, action="cancel_backfill"):
        conn.backfill = {**conn.backfill, "status": "cancelled"}
        conn.save()
        if wid:
            signal(wid, "cancel")
    return conn


# --- daily housekeeping (summary journal, reconciliation check, digest) -----------------------


def daily(connection_id: str, day: date | None = None) -> dict[str, Any]:
    """Run once a day per organisation (Temporal Schedule): post yesterday's summary
    journal (summary mode), compare recently synced invoice balances with the ledger
    (FR-23-4 reconciliation helper), and send finance a digest of open errors."""
    from tutortrack.billing.services import org_today

    conn = AccountingConnection.objects.select_related("connection").get(pk=connection_id)
    result: dict[str, Any] = {"journal": "", "drift": 0, "errors": 0, "digest": False}
    if not conn.enabled:
        return {**result, "journal": "disabled"}
    day = day or org_today() - timedelta(days=1)
    if conn.mode == AccountingConnection.Mode.SUMMARY:
        result["journal"] = sync("journal", day.isoformat(), conn=conn)
    result["drift"] = reconcile(conn)
    result["errors"] = ExternalRecordLink.objects.filter(
        connection=conn, status=Status.ERROR
    ).count()
    result["digest"] = send_digest(conn)
    return result


def reconcile(conn: AccountingConnection, *, limit: int = 50) -> int:
    """Flag synced invoices whose ledger balance differs from ours (e.g. a payment
    recorded directly in Xero). Importing them is Phase 2b (E23-T09)."""
    from tutortrack.billing.models import Invoice

    since = now() - timedelta(days=30)
    links = ExternalRecordLink.objects.filter(
        connection=conn, object_type="invoice", status=Status.SYNCED, synced_at__gte=since
    ).order_by("-synced_at")[:limit]
    try:
        creds = integrations.credentials(conn.connection)
    except ProviderError:
        return 0
    client = client_for(conn.provider)
    drift = 0
    for link in links:
        invoice = Invoice.objects.filter(pk=link.object_id).first()
        if invoice is None or link.meta.get("voided"):
            continue
        try:
            theirs = client.balance(creds, "invoice", link.external_id)
        except ProviderError:
            continue
        ours = str(invoice.balance_due.amount)
        from decimal import Decimal

        if theirs is not None and Decimal(theirs) != invoice.balance_due.amount:
            drift += 1
            if link.meta.get("drift", {}).get("theirs") != theirs:
                with transaction.atomic():
                    link.meta = {**link.meta, "drift": {"ours": ours, "theirs": theirs}}
                    link.save(update_fields=["meta", "updated_at"])
                    _log(
                        link,
                        Outcome.ERROR,
                        _("The ledger says %(theirs)s is owed; TutorTrack says %(ours)s.")
                        % {"theirs": theirs, "ours": ours},
                    )
        elif link.meta.get("drift"):
            with transaction.atomic():
                link.meta = {k: v for k, v in link.meta.items() if k != "drift"}
                link.save(update_fields=["meta", "updated_at"])
    return drift


def send_digest(conn: AccountingConnection) -> bool:
    from tutortrack.tenancy.settings_service import get_setting

    from .notifications import notify_digest

    if not get_setting("accounting.error_digest"):
        return False
    errors = list(
        ExternalRecordLink.objects.filter(connection=conn, status=Status.ERROR).order_by(
            "-updated_at"
        )[:20]
    )
    if not errors:
        return False
    with transaction.atomic():
        AccountingConnection.objects.filter(pk=conn.pk).update(last_digest_at=now())
        notify_digest(
            conn,
            errors,
            total=ExternalRecordLink.objects.filter(connection=conn, status=Status.ERROR).count(),
        )
    return True
