"""Which ledger a record goes to (gap G5, FR-23-1: per-branch ledgers).

An organisation has at most one switched-on ledger for the whole organisation (``branch``
empty) and at most one per branch. A record goes to its branch's own ledger when that
branch has one switched on, otherwise to the organisation's ledger. Prerequisites (the
client before the invoice...) are synced into the same ledger as the record that needs
them, so a client billed by two branches with separate ledgers is a contact in both.

``Scope`` is the same rule from a ledger's side: which branches' records it takes. Summary
journals, backfills and GL exports filter with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.db.models import F, QuerySet

from tutortrack.integrations.models import IntegrationConnection

from .models import AccountingConnection

LIVE = (IntegrationConnection.Status.ACTIVE, IntegrationConnection.Status.ERROR)


def enabled_connections() -> list[AccountingConnection]:
    """Switched-on ledgers whose connection is still live (organisation's first)."""
    return list(
        AccountingConnection.objects.select_related("connection")
        .filter(enabled=True, connection__status__in=LIVE)
        .order_by(F("branch_id").asc(nulls_first=True), "-enabled_at")
    )


def for_branch(
    branch_id: Any, conns: list[AccountingConnection] | None = None
) -> AccountingConnection | None:
    """The ledger a record of ``branch_id`` goes to (``None`` = not synced)."""
    conns = enabled_connections() if conns is None else conns
    organisation = None
    for conn in conns:
        if conn.branch_id is None:
            organisation = organisation or conn
        elif branch_id and str(conn.branch_id) == str(branch_id):
            return conn
    return organisation


@dataclass(frozen=True)
class Scope:
    """The branches a ledger takes: just ``include`` (a branch's own ledger), or every
    branch except ``exclude`` (the organisation's ledger, minus branches with their own)."""

    include: str | None = None
    exclude: frozenset[str] = field(default_factory=frozenset)

    def allows(self, branch_id: Any) -> bool:
        key = str(branch_id) if branch_id else ""
        if self.include is not None:
            return key == self.include
        return key not in self.exclude

    def filter(self, qs: QuerySet[Any], field_name: str = "branch_id") -> QuerySet[Any]:
        if self.include is not None:
            return qs.filter(**{field_name: self.include})
        if self.exclude:
            return qs.exclude(**{f"{field_name}__in": list(self.exclude)})
        return qs


EVERYTHING = Scope()


def scope(conn: AccountingConnection | None) -> Scope:
    if conn is None:
        return EVERYTHING
    if conn.branch_id:
        return Scope(include=str(conn.branch_id))
    others = frozenset(
        str(c.branch_id) for c in enabled_connections() if c.branch_id and c.pk != conn.pk
    )
    return Scope(exclude=others)


def routes_to(conn: AccountingConnection, branch_id: Any) -> bool:
    """Whether a record of ``branch_id`` belongs in ``conn``'s ledger."""
    return scope(conn).allows(branch_id)


def branch_of(object_type: str, object_id: str) -> Any:
    """The branch a record belongs to (``None`` when it has none or doesn't exist)."""
    from tutortrack.billing.models import CreditNote, Invoice
    from tutortrack.payments.models import Dispute, Payment, ProviderPayout, Refund
    from tutortrack.payroll.models import Payout, PayRun, PayStatement
    from tutortrack.people.models import Client

    def first(qs: QuerySet[Any], value: str) -> Any:
        return qs.values_list(value, flat=True).first()

    if object_type in ("invoice", "write_off"):
        return first(Invoice.objects.filter(pk=object_id), "branch_id")
    if object_type == "credit_note":
        return first(CreditNote.objects.filter(pk=object_id), "branch_id")
    if object_type in ("payment", "reallocation"):
        return first(Payment.objects.filter(pk=object_id), "branch_id")
    if object_type == "refund":
        return first(Refund.objects.filter(pk=object_id), "payment__branch_id")
    if object_type == "chargeback":
        return first(Dispute.objects.filter(pk=object_id), "payment__branch_id")
    if object_type == "contact":
        return first(Client.objects.filter(pk=object_id), "branch_id")
    if object_type == "provider_payout":
        return first(ProviderPayout.objects.filter(pk=object_id), "account__branch_id")
    if object_type in ("bill", "bill_payment"):
        return first(Payout.objects.filter(pk=object_id), "pay_run__branch_id")
    if object_type == "pay_run":
        return first(PayRun.objects.filter(pk=object_id), "branch_id")
    if object_type == "pay_statement":
        return first(PayStatement.objects.filter(pk=object_id), "payout__pay_run__branch_id")
    return None


def route(object_type: str, object_id: str) -> AccountingConnection | None:
    return for_branch(branch_of(object_type, str(object_id)))


def resolve(connection_id: str, object_type: str, object_id: str) -> AccountingConnection | None:
    """The ledger a sync is for: the one named (prerequisites and retries keep their
    parent's ledger), else the record's own."""
    if connection_id:
        return (
            AccountingConnection.objects.select_related("connection")
            .filter(pk=connection_id, enabled=True, connection__status__in=LIVE)
            .first()
        )
    return route(object_type, object_id)
