"""Client billing reads (E10): balances, statements and ageing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import QuerySet, Sum

from tutortrack.core.money import Money
from tutortrack.core.permissions import scope_queryset

from .models import ClientLedgerEntry, Invoice

BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def invoices(user: Any) -> QuerySet[Invoice]:
    return scope_queryset(user, Invoice.objects.all(), "billing.invoice.view").select_related(
        "client"
    )


def bucket_for(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "90_plus"


def ageing_of(open_invoices: QuerySet[Invoice], currency: str, today: date) -> dict[str, Money]:
    out = {name: Money.zero(currency).round_to_minor() for name in BUCKETS}
    for invoice in open_invoices.filter(currency=currency):
        days = (today - invoice.due_date).days if invoice.due_date else 0
        name = bucket_for(days)
        out[name] = out[name] + invoice.balance_due
    return out


@dataclass
class Statement:
    client_id: str
    currency: str
    start: date
    end: date
    opening: Money
    closing: Money
    entries: list[ClientLedgerEntry] = field(default_factory=list)
    ageing: dict[str, Money] = field(default_factory=dict)


def statement(client: Any, currency: str, start: date, end: date, tz: str) -> Statement:
    """FR-10-9: opening balance, the movements in the range, closing balance and ageing."""
    zone = ZoneInfo(tz)
    since = datetime.combine(start, time.min, tzinfo=zone)
    until = datetime.combine(end, time.max, tzinfo=zone)
    entries = ClientLedgerEntry.objects.filter(client=client, currency=currency)
    before = entries.filter(occurred_at__lt=since).aggregate(t=Sum("amount_amount"))["t"]
    rows = list(entries.filter(occurred_at__gte=since, occurred_at__lte=until))
    opening = Money(before or Decimal(0), currency).round_to_minor()
    closing = opening + Money(sum((r.amount_amount for r in rows), Decimal(0)), currency)
    open_invoices = Invoice.objects.filter(client=client, status__in=Invoice.OPEN)
    return Statement(
        client_id=str(client.pk),
        currency=currency,
        start=start,
        end=end,
        opening=opening,
        closing=closing,
        entries=rows,
        ageing=ageing_of(open_invoices, currency, end),
    )


def ageing_report(user: Any, currency: str) -> list[dict[str, Any]]:
    """Overdue invoices by client in ageing buckets (FR-10-14 global billing area)."""
    from .services import org_today

    today = org_today()
    rows: dict[str, dict[str, Any]] = {}
    for invoice in invoices(user).filter(status__in=Invoice.OPEN, currency=currency):
        days = (today - invoice.due_date).days if invoice.due_date else 0
        row = rows.setdefault(
            str(invoice.client_id),
            {
                "client": str(invoice.client_id),
                "client_name": invoice.client.display_name,
                **{name: Money.zero(currency) for name in BUCKETS},
                "total": Money.zero(currency),
            },
        )
        name = bucket_for(days)
        row[name] = row[name] + invoice.balance_due
        row["total"] = row["total"] + invoice.balance_due
    return sorted(rows.values(), key=lambda r: -r["total"].amount)


# --- for payroll (E12: pay tutors only when the client has paid) -------------------------------


def lesson_paid(lesson_id: Any) -> bool:
    """Every charge for the lesson is on a paid invoice (a lesson with no charges counts)."""
    from .models import Charge

    charges = Charge.objects.filter(lesson_id=lesson_id).exclude(status=Charge.Status.VOID)
    return not charges.exclude(invoice__status=Invoice.Status.PAID).exists()


def lessons_on_invoice(invoice_id: Any) -> list[Any]:
    from .models import Charge

    return list(
        Charge.objects.filter(invoice_id=invoice_id, lesson__isnull=False)
        .values_list("lesson_id", flat=True)
        .distinct()
    )
