"""Accounting reads (E23): connections, mapping sets, the sync dashboard and per-record
sync status for badges on invoices and payments."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, QuerySet

from tutortrack.core.permissions import scope_queryset

from .models import (
    AccountingConnection,
    ExternalRecordLink,
    LedgerPaymentImport,
    SyncLogEntry,
)

VIEW = "integrations.accounting.view"


def connections(user: Any) -> QuerySet[AccountingConnection]:
    qs = AccountingConnection.objects.select_related("connection", "branch").exclude(
        connection__status="disconnected"
    )
    return scope_queryset(user, qs, VIEW)


def records(user: Any) -> QuerySet[ExternalRecordLink]:
    return scope_queryset(user, ExternalRecordLink.objects.all(), VIEW)


def payment_imports(user: Any) -> QuerySet[LedgerPaymentImport]:
    """Payments read back from the ledger (E23-T09), imported or skipped."""
    return scope_queryset(
        user,
        LedgerPaymentImport.objects.select_related("invoice", "invoice__client", "payment"),
        VIEW,
    )


def log(link: ExternalRecordLink, limit: int = 50) -> list[SyncLogEntry]:
    return list(SyncLogEntry.objects.filter(link=link)[:limit])


def stats(conn: AccountingConnection) -> dict[str, int]:
    counts = dict.fromkeys(ExternalRecordLink.Status.values, 0)
    for row in (
        ExternalRecordLink.objects.filter(connection=conn).values("status").annotate(n=Count("id"))
    ):
        counts[row["status"]] = row["n"]
    return counts


def statuses(user: Any, object_type: str, object_ids: list[str]) -> list[ExternalRecordLink]:
    """Each record's links on the switched-on ledgers (sync badges; a record has one per
    ledger it went to, gap G5: per-branch ledgers)."""
    from .routing import enabled_connections

    conns = [c.pk for c in enabled_connections()]
    qs = records(user).filter(object_type=object_type, object_id__in=object_ids[:200])
    if conns:
        qs = qs.filter(connection__in=conns)
    return list(qs)
