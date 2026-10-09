"""The client ledger (E10-T01): posting with invariants, and balances.

Sign convention: positive = the client owes more (invoices, refunds), negative = less
(payments, credit notes, top-ups, write-offs). ``balance_after`` is the running sum per
client and currency; posts lock the client row so concurrent posts serialise.

Balances shown (FR-10 §2):
* **invoice balance**: owed on issued invoices (Σ ``balance_due`` of open invoices)
* **available credit**: money held for the client and not yet used
  (= invoice balance - ledger balance, when positive)
* **uninvoiced**: charges not yet on an invoice
* **projected**: available credit - uninvoiced - scheduled lessons (prepaid clients)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import connection
from django.db.models import Sum

from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.people.models import Client

from .models import Charge, ClientLedgerEntry, Invoice

INCREASES = {ClientLedgerEntry.Type.INVOICE, ClientLedgerEntry.Type.REFUND}
DECREASES = {
    ClientLedgerEntry.Type.INVOICE_VOID,
    ClientLedgerEntry.Type.PAYMENT,
    ClientLedgerEntry.Type.CREDIT_NOTE,
    ClientLedgerEntry.Type.PAYMENT_REQUEST_PAYMENT,
    ClientLedgerEntry.Type.WRITE_OFF,
}


class LedgerError(ValueError):
    pass


def _sum(qs: Any, field: str, currency: str) -> Money:
    total = qs.aggregate(total=Sum(field))["total"]
    return Money(total or Decimal(0), currency).round_to_minor()


def ledger_balance(client: Any, currency: str) -> Money:
    return _sum(
        ClientLedgerEntry.objects.filter(client=client, currency=currency),
        "amount_amount",
        currency,
    )


def post(
    client: Client,
    type: str,
    amount: Money,
    *,
    ref: Any = None,
    description: str = "",
    occurred_at: datetime | None = None,
    user: Any = None,
) -> ClientLedgerEntry:
    """Append an entry. ``amount`` is signed; its sign must match the entry type."""
    if not connection.in_atomic_block:
        raise LedgerError("Ledger posts must run inside the transaction that causes them.")
    if (type in INCREASES and amount.is_negative()) or (type in DECREASES and amount.is_positive()):
        raise LedgerError(f"{type} entries cannot be {amount}")
    if not amount.is_rounded():
        raise LedgerError("Round ledger amounts to the currency's minor unit.")
    Client.objects.select_for_update().filter(pk=client.pk).first()  # serialise per client
    current = ledger_balance(client, amount.currency)
    return ClientLedgerEntry.objects.create(
        client=client,
        type=type,
        currency=amount.currency,
        amount=amount,
        balance_after=current + amount,
        ref_type=type_of(ref),
        ref_id=str(ref.pk) if ref is not None else "",
        description=description[:300],
        occurred_at=occurred_at or now(),
        created_by=user,
    )


def type_of(ref: Any) -> str:
    return "" if ref is None else f"{ref._meta.app_label}.{ref._meta.model_name}"


@dataclass(frozen=True)
class Balances:
    currency: str
    ledger: Money
    invoice_balance: Money
    available_credit: Money
    uninvoiced: Money
    projected: Money
    overdue: Money

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            **{
                name: getattr(self, name).to_dict()
                for name in (
                    "ledger",
                    "invoice_balance",
                    "available_credit",
                    "uninvoiced",
                    "projected",
                    "overdue",
                )
            },
        }


def balances(client: Any, currency: str | None = None) -> Balances:
    currency = currency or client.currency
    ledger = ledger_balance(client, currency)
    open_invoices = Invoice.objects.filter(
        client=client, currency=currency, status__in=Invoice.OPEN
    )
    invoice_balance = _sum(open_invoices, "balance_due_amount", currency)
    from .services import org_today

    overdue = _sum(open_invoices.filter(due_date__lt=org_today()), "balance_due_amount", currency)
    credit = invoice_balance - ledger
    available = credit if credit.is_positive() else Money.zero(currency)
    uninvoiced = _sum(
        Charge.objects.filter(client=client, currency=currency, status=Charge.Status.UNINVOICED),
        "gross_amount",
        currency,
    )
    scheduled = scheduled_charges(client, currency)
    return Balances(
        currency=currency,
        ledger=ledger,
        invoice_balance=invoice_balance,
        available_credit=available,
        uninvoiced=uninvoiced,
        projected=available - uninvoiced - scheduled,
        overdue=overdue,
    )


def scheduled_charges(client: Any, currency: str) -> Money:
    """What the client's planned future lessons will cost (prepaid projections)."""
    from tutortrack.scheduling.models import Lesson, LessonAttendee

    total = (
        LessonAttendee.objects.filter(
            client=client,
            currency=currency,
            chargeable=True,
            lesson__status=Lesson.Status.PLANNED,
            lesson__start__gte=now(),
        ).aggregate(total=Sum("charge_amount_amount"))["total"]
        or 0
    )
    return Money(Decimal(total), currency)
