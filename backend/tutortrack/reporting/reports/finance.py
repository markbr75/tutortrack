"""Finance reports (E26-T04)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.utils.translation import gettext_lazy as _

from .. import dims
from ..models import FactCharge, FactLesson, FactPayItem, FactPayment
from ..periods import org_today
from .base import (
    Column,
    Params,
    ReportDef,
    Result,
    filter_facts,
    group_column,
    grouped,
    in_period,
    money,
    money_columns,
    percent,
    register,
    scoped,
    scoped_by,
)

CODENAME = "reporting.finance.view"
CHARGE_FIELDS = {
    "branch": "branch_id",
    "tutor": "tutor_id",
    "client": "client_id",
    "student": "student_id",
    "service": "service_id",
    "subject": "subject_id",
    "job": "job_id",
}
ALL_FILTERS = ("branch", "tutor", "client", "service", "subject", "tag", "custom_field")
LESSON_PAY_KINDS = ("lesson", "cancellation", "charge_share", "event")


def _charges(user: Any, params: Params) -> Any:
    qs = scoped(user, FactCharge.objects.exclude(status="void"), CODENAME)
    return filter_facts(in_period(qs, params), params, CHARGE_FIELDS)


# --- revenue ------------------------------------------------------------------------------------


def revenue(user: Any, params: Params) -> Result:
    rows = grouped(
        _charges(user, params),
        params.group_by,
        {
            "lines": Count("pk"),
            "net": Sum("net_amount"),
            "tax": Sum("tax_amount"),
            "gross": Sum("gross_amount"),
        },
        fields=CHARGE_FIELDS,
    )
    money_columns(rows, ("net", "tax", "gross"))
    return Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("lines", _("Charges"), "count"),
            Column("net", _("Net"), "money"),
            Column("tax", _("Tax"), "money"),
            Column("gross", _("Gross"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["net"]},
    )


register(
    ReportDef(
        key="revenue",
        title=_("Revenue"),
        category="finance",
        codename=CODENAME,
        description=_(
            "Charges earned in the period by month, service, subject, tutor, branch or client."
        ),
        run=revenue,
        filters=ALL_FILTERS,
        group_by=("month", "week", "day", "service", "subject", "tutor", "branch", "client"),
    )
)


def uninvoiced(user: Any, params: Params) -> Result:
    qs = scoped(user, FactCharge.objects.filter(status="uninvoiced"), CODENAME)
    qs = filter_facts(in_period(qs, params), params, CHARGE_FIELDS)
    rows = grouped(
        qs,
        params.group_by,
        {"lines": Count("pk"), "gross": Sum("gross_amount")},
        fields=CHARGE_FIELDS,
    )
    money_columns(rows, ("gross",))
    return Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("lines", _("Charges"), "count"),
            Column("gross", _("Amount"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["gross"]},
    )


register(
    ReportDef(
        key="uninvoiced_charges",
        title=_("Charges not yet invoiced"),
        category="finance",
        codename=CODENAME,
        description=_("Charges waiting for the next invoice run."),
        run=uninvoiced,
        filters=ALL_FILTERS,
        group_by=("client", "month", "service", "tutor", "branch"),
        default_period="last_12_months",
        ordering="-gross",
    )
)


# --- invoices register --------------------------------------------------------------------------


def invoices_register(user: Any, params: Params) -> Result:
    from tutortrack.billing.models import Invoice

    qs = scoped(user, Invoice.objects.exclude(status="draft"), CODENAME)
    qs = in_period(qs, params, "issue_date")
    qs = filter_facts(qs, params, {"branch": "branch_id", "client": "client_id"})
    rows = []
    for inv in qs.select_related("client").order_by("issue_date", "number")[:5000]:
        rows.append(
            {
                "id": str(inv.pk),
                "number": inv.number,
                "client": inv.client.display_name,
                "issue_date": inv.issue_date.isoformat() if inv.issue_date else "",
                "due_date": inv.due_date.isoformat() if inv.due_date else "",
                "status": str(Invoice.Status(inv.status).label),
                "currency": inv.currency,
                "net": money(inv.subtotal_amount, inv.currency),
                "tax": money(inv.tax_total_amount, inv.currency),
                "total": money(inv.total_amount, inv.currency),
                "paid": money(inv.amount_paid_amount, inv.currency),
                "credited": money(inv.amount_credited_amount, inv.currency),
                "balance": money(inv.balance_due_amount, inv.currency),
            }
        )
    return Result(
        columns=[
            Column("number", _("Number")),
            Column("client", _("Client")),
            Column("issue_date", _("Issued"), "date"),
            Column("due_date", _("Due"), "date"),
            Column("status", _("Status")),
            Column("currency", _("Currency")),
            Column("net", _("Net"), "money"),
            Column("tax", _("Tax"), "money"),
            Column("total", _("Total"), "money"),
            Column("paid", _("Paid"), "money"),
            Column("credited", _("Credited"), "money"),
            Column("balance", _("Balance due"), "money"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="invoices_register",
        title=_("Invoices register"),
        category="finance",
        codename=CODENAME,
        description=_("Every invoice issued in the period with what has been paid or credited."),
        run=invoices_register,
        filters=("branch", "client", "tag", "custom_field"),
    )
)


# --- payments -----------------------------------------------------------------------------------

RECEIVED = ("succeeded", "partially_refunded", "refunded", "disputed")


def payments_received(user: Any, params: Params) -> Result:
    from tutortrack.payments.models import Payment

    qs = scoped(user, FactPayment.objects.filter(status__in=RECEIVED), CODENAME)
    qs = filter_facts(in_period(qs, params), params, {"branch": "branch_id", "client": "client_id"})
    choices = (
        dict(Payment.Method.choices)
        if params.group_by == "method"
        else dict(Payment._meta.get_field("provider").choices or [])
        if params.group_by == "provider"
        else None
    )
    rows = grouped(
        qs,
        params.group_by,
        {
            "payments": Count("pk"),
            "amount": Sum("amount_amount"),
            "refunded": Sum("refunded_amount"),
            "fees": Sum("fee_amount"),
        },
        fields={"client": "client_id", "branch": "branch_id"},
        choices=choices,
    )
    for row in rows:
        received = Decimal(row["amount"] or 0) - Decimal(row["refunded"] or 0)
        row["net"] = received - Decimal(row["fees"] or 0)
        row["received"] = received
    money_columns(rows, ("amount", "refunded", "received", "fees", "net"))
    return Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("payments", _("Payments"), "count"),
            Column("amount", _("Amount"), "money"),
            Column("refunded", _("Refunded"), "money"),
            Column("received", _("Kept"), "money"),
            Column("fees", _("Fees"), "money"),
            Column("net", _("Net of fees"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["received"]},
    )


register(
    ReportDef(
        key="payments_received",
        title=_("Payments received"),
        category="finance",
        codename=CODENAME,
        description=_("Money received by method, provider or period, with refunds and fees."),
        run=payments_received,
        filters=("branch", "client", "tag", "custom_field"),
        group_by=("method", "provider", "month", "week", "day", "client", "branch"),
    )
)


# --- aged debtors and balances ------------------------------------------------------------------

BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def aged_debtors(user: Any, params: Params) -> Result:
    from tutortrack.billing.models import Invoice
    from tutortrack.billing.selectors import bucket_for

    today = org_today()
    qs = scoped(user, Invoice.objects.filter(status__in=Invoice.OPEN), CODENAME)
    qs = filter_facts(qs, params, {"branch": "branch_id", "client": "client_id"})
    by: dict[tuple[str, str], dict[str, Any]] = {}
    for inv in qs.filter(balance_due_amount__gt=0).only(
        "client_id", "currency", "due_date", "balance_due_amount"
    ):
        row = by.setdefault(
            (str(inv.client_id), inv.currency),
            {
                "client_id": str(inv.client_id),
                "currency": inv.currency,
                "invoices": 0,
                **{b: Decimal(0) for b in BUCKETS},
                "total": Decimal(0),
            },
        )
        days = (today - inv.due_date).days if inv.due_date else 0
        row[bucket_for(days)] += inv.balance_due_amount
        row["total"] += inv.balance_due_amount
        row["invoices"] += 1
    names = dims.labels("client", (k[0] for k in by))
    rows = []
    for (client_id, _currency), row in by.items():
        row["client"] = names.get(client_id, "")
        rows.append(row)
    money_columns(rows, (*BUCKETS, "total"))
    return Result(
        columns=[
            Column("client", _("Client")),
            Column("currency", _("Currency")),
            Column("invoices", _("Invoices"), "count"),
            Column("current", _("Not yet due"), "money"),
            Column("1_30", _("1\N{EN DASH}30 days"), "money"),
            Column("31_60", _("31\N{EN DASH}60 days"), "money"),
            Column("61_90", _("61\N{EN DASH}90 days"), "money"),
            Column("90_plus", _("Over 90 days"), "money"),
            Column("total", _("Total owed"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "client", "y": list(BUCKETS), "stacked": True},
    )


register(
    ReportDef(
        key="aged_debtors",
        title=_("Aged debtors"),
        category="finance",
        codename=CODENAME,
        description=_("What each client owes today, by how overdue it is."),
        run=aged_debtors,
        filters=("branch", "client", "tag", "custom_field"),
        period=False,
        ordering="-total",
    )
)


def client_balances(user: Any, params: Params) -> Result:
    """Ledger balance per client; a negative balance is credit we hold (a liability)."""
    from tutortrack.billing.models import ClientLedgerEntry, Invoice

    entries = scoped_by(user, ClientLedgerEntry.objects.all(), CODENAME, branch="client__branch_id")
    entries = filter_facts(entries, params, {"branch": "client__branch_id", "client": "client_id"})
    ledger = {
        (str(r["client_id"]), r["currency"]): r["t"]
        for r in entries.values("client_id", "currency").annotate(t=Sum("amount_amount"))
    }
    open_qs = scoped(user, Invoice.objects.filter(status__in=Invoice.OPEN), CODENAME)
    open_qs = filter_facts(open_qs, params, {"branch": "branch_id", "client": "client_id"})
    owed = {
        (str(r["client_id"]), r["currency"]): r["t"]
        for r in open_qs.values("client_id", "currency").annotate(t=Sum("balance_due_amount"))
    }
    names = dims.labels("client", (k[0] for k in {*ledger, *owed}))
    rows = []
    for key in sorted({*ledger, *owed}):
        balance = Decimal(ledger.get(key) or 0)
        invoices = Decimal(owed.get(key) or 0)
        credit = max(invoices - balance, Decimal(0))
        if not balance and not invoices:
            continue
        rows.append(
            {
                "client_id": key[0],
                "client": names.get(key[0], ""),
                "currency": key[1],
                "balance": balance,
                "owed": invoices,
                "credit": credit,
            }
        )
    money_columns(rows, ("balance", "owed", "credit"))
    return Result(
        columns=[
            Column("client", _("Client")),
            Column("currency", _("Currency")),
            Column("balance", _("Ledger balance"), "money"),
            Column("owed", _("On open invoices"), "money"),
            Column("credit", _("Credit held"), "money"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="client_balances",
        title=_("Client balances and credit"),
        category="finance",
        codename=CODENAME,
        description=_("Each client's balance and the prepaid credit you hold for them."),
        run=client_balances,
        filters=("branch", "client", "tag", "custom_field"),
        period=False,
        ordering="client",
    )
)


# --- tax, refunds and write-offs ----------------------------------------------------------------


def tax_summary(user: Any, params: Params) -> Result:
    from tutortrack.billing.models import CreditNoteLine, InvoiceLine

    lines = scoped_by(
        user,
        InvoiceLine.objects.filter(
            invoice__issue_date__gte=params.period.start,
            invoice__issue_date__lte=params.period.end,
        ).exclude(invoice__status__in=("draft", "void")),
        CODENAME,
        branch="invoice__branch_id",
    )
    lines = filter_facts(
        lines, params, {"branch": "invoice__branch_id", "client": "invoice__client_id"}
    )
    credits = scoped_by(
        user,
        CreditNoteLine.objects.filter(
            credit_note__issued_at__date__gte=params.period.start,
            credit_note__issued_at__date__lte=params.period.end,
        ),
        CODENAME,
        branch="credit_note__branch_id",
    )
    credits = filter_facts(
        credits, params, {"branch": "credit_note__branch_id", "client": "credit_note__client_id"}
    )
    by: dict[tuple[str, str], dict[str, Decimal]] = {}

    def bucket(rate: Any, currency: str) -> dict[str, Decimal]:
        key = (str(Decimal(rate).normalize()), currency)
        return by.setdefault(
            key, {k: Decimal(0) for k in ("net", "tax", "credited_net", "credited_tax")}
        )

    for r in lines.values("tax_percent", "currency").annotate(
        net=Sum("net_amount"), tax=Sum("tax_amount")
    ):
        b = bucket(r["tax_percent"], r["currency"])
        b["net"] += r["net"] or 0
        b["tax"] += r["tax"] or 0
    for r in credits.values("invoice_line__tax_percent", "currency").annotate(
        net=Sum("net_amount"), tax=Sum("tax_amount")
    ):
        b = bucket(r["invoice_line__tax_percent"] or 0, r["currency"])
        b["credited_net"] += r["net"] or 0
        b["credited_tax"] += r["tax"] or 0
    rows: list[dict[str, Any]] = []
    for (rate, currency), b in sorted(by.items()):
        rows.append(
            {
                "rate": f"{rate}%",
                "currency": currency,
                **b,
                "net_total": b["net"] - b["credited_net"],
                "tax_total": b["tax"] - b["credited_tax"],
            }
        )
    money_columns(rows, ("net", "tax", "credited_net", "credited_tax", "net_total", "tax_total"))
    return Result(
        columns=[
            Column("rate", _("Tax rate")),
            Column("currency", _("Currency")),
            Column("net", _("Invoiced net"), "money"),
            Column("tax", _("Invoiced tax"), "money"),
            Column("credited_net", _("Credited net"), "money"),
            Column("credited_tax", _("Credited tax"), "money"),
            Column("net_total", _("Net"), "money"),
            Column("tax_total", _("Tax due"), "money"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="tax_summary",
        title=_("Tax summary"),
        category="finance",
        codename=CODENAME,
        description=_("Tax on invoices issued in the period, less credit notes, by rate."),
        run=tax_summary,
        filters=("branch", "client"),
        default_period="last_quarter",
    )
)


def refunds_write_offs(user: Any, params: Params) -> Result:
    from tutortrack.billing.models import Invoice
    from tutortrack.payments.models import Refund

    rows: list[dict[str, Any]] = []
    refunds = scoped_by(
        user,
        Refund.objects.filter(status="succeeded"),
        CODENAME,
        branch="payment__branch_id",
    )
    refunds = in_period(refunds, params, "created_at__date")
    refunds = filter_facts(
        refunds, params, {"branch": "payment__branch_id", "client": "payment__client_id"}
    )
    for r in refunds.select_related("payment__client"):
        rows.append(
            {
                "date": r.created_at.date().isoformat(),
                "type": str(_("Refund")),
                "client": r.payment.client.display_name,
                "reference": r.payment.reference,
                "reason": r.reason,
                "currency": r.currency,
                "amount": money(r.amount_amount, r.currency),
            }
        )
    written = scoped(user, Invoice.objects.filter(status="written_off"), CODENAME)
    written = in_period(written, params, "written_off_at__date")
    written = filter_facts(written, params, {"branch": "branch_id", "client": "client_id"})
    for inv in written.select_related("client"):
        amount = inv.total_amount - inv.amount_paid_amount - inv.amount_credited_amount
        rows.append(
            {
                "date": inv.written_off_at.date().isoformat() if inv.written_off_at else "",
                "type": str(_("Write-off")),
                "client": inv.client.display_name,
                "reference": inv.number,
                "reason": inv.write_off_reason,
                "currency": inv.currency,
                "amount": money(amount, inv.currency),
            }
        )
    rows.sort(key=lambda r: r["date"])
    return Result(
        columns=[
            Column("date", _("Date"), "date"),
            Column("type", _("Type")),
            Column("client", _("Client")),
            Column("reference", _("Reference")),
            Column("reason", _("Reason")),
            Column("currency", _("Currency")),
            Column("amount", _("Amount"), "money"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="refunds_write_offs",
        title=_("Refunds and write-offs"),
        category="finance",
        codename=CODENAME,
        description=_("Money given back and debts written off in the period."),
        run=refunds_write_offs,
        filters=("branch", "client"),
    )
)


# --- margin -------------------------------------------------------------------------------------

MARGIN_FIELDS = {
    "tutor": "tutor_id",
    "service": "service_id",
    "job": "job_id",
    "branch": "branch_id",
}


def margin_rows(user: Any, params: Params) -> list[dict[str, Any]]:
    charges = scoped(user, FactCharge.objects.exclude(status="void"), CODENAME)
    charges = filter_facts(in_period(charges, params), params, CHARGE_FIELDS)
    pay = scoped(
        user,
        FactPayItem.objects.exclude(status="void").filter(kind__in=LESSON_PAY_KINDS),
        CODENAME,
    )
    pay = filter_facts(in_period(pay, params), params, {**MARGIN_FIELDS, "client": None})
    if params.client or params.subject or params.tag or params.custom_field:
        pay = pay.filter(lesson_id__in=charges.values("lesson_id"))
    revenue = grouped(
        charges, params.group_by, {"revenue": Sum("net_amount")}, fields=MARGIN_FIELDS
    )
    cost = grouped(pay, params.group_by, {"cost": Sum("amount_amount")}, fields=MARGIN_FIELDS)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in revenue + cost:
        key = (row["group_id"], row["currency"])
        target = merged.setdefault(key, {**row, "revenue": Decimal(0), "cost": Decimal(0)})
        for name in ("revenue", "cost"):
            if name in row and row[name] is not None:
                target[name] += Decimal(row[name])
    rows = sorted(merged.values(), key=lambda r: (r["group"], r["currency"]))
    for row in rows:
        row["margin"] = row["revenue"] - row["cost"]
        row["margin_percent"] = percent(row["margin"], row["revenue"])
    money_columns(rows, ("revenue", "cost", "margin"))
    return rows


def margin(user: Any, params: Params) -> Result:
    rows = margin_rows(user, params)
    result = Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("revenue", _("Revenue (net)"), "money"),
            Column("cost", _("Tutor pay"), "money"),
            Column("margin", _("Margin"), "money"),
            Column("margin_percent", _("Margin %"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["revenue", "cost"]},
    )
    from .base import compute_totals

    totals = compute_totals(result)
    for t in totals:
        t["margin_percent"] = percent(Decimal(t["margin"]), Decimal(t["revenue"]))
    result.totals = totals if not params.currency else None
    return result


register(
    ReportDef(
        key="margin",
        title=_("Margin"),
        category="finance",
        codename=CODENAME,
        description=_("Revenue less tutor pay by tutor, service, job or month."),
        run=margin,
        filters=ALL_FILTERS,
        group_by=("tutor", "service", "job", "month", "branch"),
        ordering="-margin",
    )
)


# --- cash forecast ------------------------------------------------------------------------------

HORIZONS = (
    (30, _("Next 30 days")),
    (60, _("31\N{EN DASH}60 days")),
    (90, _("61\N{EN DASH}90 days")),
)


def forecast_rows(user: Any, params: Params, codename: str = CODENAME) -> list[dict[str, Any]]:
    today = org_today()
    qs = scoped(
        user,
        FactLesson.objects.filter(
            status="planned", date__gte=today, date__lte=today + timedelta(days=89)
        ),
        codename,
    )
    qs = filter_facts(
        qs,
        params,
        {
            "branch": "branch_id",
            "tutor": "tutor_id",
            "service": "service_id",
            "subject": "subject_id",
        },
    )
    rows: list[dict[str, Any]] = []
    first = 0
    for days, label in HORIZONS:
        window = qs.filter(
            date__gte=today + timedelta(days=first), date__lte=today + timedelta(days=days - 1)
        )
        for r in (
            window.values("currency")
            .annotate(
                lessons=Count("pk", filter=Q(primary=True)),
                revenue=Sum("revenue_amount"),
                pay=Sum("pay_amount"),
            )
            .order_by("currency")
        ):
            rows.append(
                {
                    "group": str(label),
                    "group_id": str(days),
                    "currency": r["currency"],
                    "lessons": r["lessons"],
                    "revenue": r["revenue"] or 0,
                    "pay": r["pay"] or 0,
                    "net": Decimal(r["revenue"] or 0) - Decimal(r["pay"] or 0),
                }
            )
        first = days
    money_columns(rows, ("revenue", "pay", "net"))
    return rows


def cash_forecast(user: Any, params: Params) -> Result:
    return Result(
        columns=[
            Column("group", _("When")),
            Column("currency", _("Currency")),
            Column("lessons", _("Scheduled lessons"), "count"),
            Column("revenue", _("Expected charges"), "money"),
            Column("pay", _("Expected tutor pay"), "money"),
            Column("net", _("Expected net"), "money"),
        ],
        rows=forecast_rows(user, params),
        chart={"type": "bar", "x": "group", "y": ["revenue", "pay"]},
    )


register(
    ReportDef(
        key="cash_forecast",
        title=_("Cash forecast"),
        category="finance",
        codename=CODENAME,
        description=_("Scheduled lessons priced at their rates for the next 30, 60 and 90 days."),
        run=cash_forecast,
        filters=("branch", "tutor", "service", "subject"),
        period=False,
    )
)
