"""Payroll reports (E26-T05). Tutors with ``reporting.payroll.view:own`` see their own."""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum
from django.utils.translation import gettext_lazy as _

from ..models import FactPayItem
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
    register,
    scoped,
)

CODENAME = "reporting.payroll.view"
PAY_FIELDS = {
    "branch": "branch_id",
    "tutor": "tutor_id",
    "service": "service_id",
    "job": "job_id",
    "pay_run": "pay_run_id",
}


def tutor_earnings(user: Any, params: Params) -> Result:
    from tutortrack.payroll.models import PayItem

    qs = scoped(user, FactPayItem.objects.exclude(status="void"), CODENAME)
    qs = filter_facts(in_period(qs, params), params, PAY_FIELDS)
    rows = grouped(
        qs,
        params.group_by,
        {
            "items": Count("pk"),
            "amount": Sum("amount_amount"),
            "paid": Sum("amount_amount", filter=Q(status="paid")),
            "held": Sum("amount_amount", filter=Q(status="held")),
        },
        fields=PAY_FIELDS,
        choices=dict(PayItem.Kind.choices)
        if params.group_by == "kind"
        else dict(PayItem.Status.choices)
        if params.group_by == "status"
        else None,
    )
    money_columns(rows, ("amount", "paid", "held"))
    return Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("items", _("Pay items"), "count"),
            Column("amount", _("Earned"), "money"),
            Column("paid", _("Paid"), "money"),
            Column("held", _("On hold"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["amount"]},
    )


register(
    ReportDef(
        key="tutor_earnings",
        title=_("Tutor earnings"),
        category="payroll",
        codename=CODENAME,
        description=_("Pay earned in the period by tutor, month or type of pay."),
        run=tutor_earnings,
        filters=("branch", "tutor", "service"),
        group_by=("tutor", "month", "week", "kind", "status", "branch"),
    )
)


def pay_runs(user: Any, params: Params) -> Result:
    from tutortrack.payroll.models import PayRun

    qs = scoped(user, PayRun.objects.exclude(status="cancelled"), CODENAME)
    qs = in_period(qs, params, "period_end")
    qs = filter_facts(qs, params, {"branch": "branch_id"})
    items = (
        scoped(user, FactPayItem.objects.filter(pay_run_id__in=qs.values("pk")), CODENAME)
        .values("pay_run_id", "currency")
        .annotate(n=Count("pk"), tutors=Count("tutor_id", distinct=True), t=Sum("amount_amount"))
    )
    by_run: dict[str, list[dict[str, Any]]] = {}
    for r in items:
        by_run.setdefault(str(r["pay_run_id"]), []).append(r)
    rows = []
    for run in qs.order_by("period_end", "number"):
        for r in by_run.get(str(run.pk), []) or [{"currency": "", "n": 0, "tutors": 0, "t": 0}]:
            rows.append(
                {
                    "id": str(run.pk),
                    "number": run.number,
                    "period": f"{run.period_start.isoformat()} \N{EN DASH} "
                    f"{run.period_end.isoformat()}",
                    "status": str(PayRun.Status(run.status).label),
                    "currency": r["currency"],
                    "tutors": r["tutors"],
                    "items": r["n"],
                    "total": money(r["t"], r["currency"]),
                    "paid_at": run.paid_at.date().isoformat() if run.paid_at else "",
                }
            )
    return Result(
        columns=[
            Column("number", _("Pay run")),
            Column("period", _("Period")),
            Column("status", _("Status")),
            Column("currency", _("Currency")),
            Column("tutors", _("Tutors"), "count"),
            Column("items", _("Pay items"), "count"),
            Column("total", _("Total"), "money"),
            Column("paid_at", _("Paid"), "date"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="pay_runs",
        title=_("Pay run summaries"),
        category="payroll",
        codename=CODENAME,
        description=_("Pay runs whose period ended in the range, with their totals."),
        run=pay_runs,
        filters=("branch",),
        default_period="last_12_months",
    )
)


def held_items(user: Any, params: Params) -> Result:
    from tutortrack.payroll.models import PayItem

    qs = scoped(user, PayItem.objects.filter(status=PayItem.Status.HELD), CODENAME)
    qs = filter_facts(qs, params, {"branch": "branch_id", "tutor": "tutor_id"})
    rows = [
        {
            "date": item.date.isoformat(),
            "tutor": item.tutor.full_name,
            "description": item.description,
            "reasons": ", ".join(str(r) for r in item.hold_reasons or []),
            "note": item.hold_note,
            "currency": item.currency,
            "amount": money(item.amount_amount, item.currency),
        }
        for item in qs.select_related("tutor").order_by("date")[:5000]
    ]
    return Result(
        columns=[
            Column("date", _("Date"), "date"),
            Column("tutor", _("Tutor")),
            Column("description", _("Description")),
            Column("reasons", _("Why it's held")),
            Column("note", _("Note")),
            Column("currency", _("Currency")),
            Column("amount", _("Amount"), "money"),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="held_items",
        title=_("Pay on hold"),
        category="payroll",
        codename=CODENAME,
        description=_("Pay items held back from pay runs and why."),
        run=held_items,
        filters=("branch", "tutor"),
        period=False,
    )
)


def _expenses(user: Any, params: Params, mileage: bool) -> Any:
    from tutortrack.payroll.models import Expense

    qs = scoped(user, Expense.objects.exclude(status__in=("draft", "rejected")), CODENAME)
    qs = qs.filter(distance__isnull=False) if mileage else qs.filter(distance__isnull=True)
    return filter_facts(
        in_period(qs, params),
        params,
        {"branch": "branch_id", "tutor": "tutor_id", "client": "client_id"},
    )


def expenses(user: Any, params: Params) -> Result:
    from tutortrack.payroll.models import Expense, ExpenseCategory

    qs = _expenses(user, params, mileage=False)
    categories = (
        {str(c.pk): c.name for c in ExpenseCategory.objects.all()}
        if params.group_by == "category"
        else None
    )
    rows = grouped(
        qs,
        params.group_by,
        {"claims": Count("pk"), "amount": Sum("amount_amount"), "tax": Sum("tax_amount")},
        fields={"category": "category_id", "tutor": "tutor_id", "branch": "branch_id"},
        choices=categories
        if params.group_by == "category"
        else dict(Expense.Status.choices)
        if params.group_by == "status"
        else None,
    )
    money_columns(rows, ("amount", "tax"))
    return Result(
        columns=[
            group_column(params)
            if params.group_by != "category"
            else Column("group", _("Category")),
            Column("currency", _("Currency")),
            Column("claims", _("Claims"), "count"),
            Column("amount", _("Amount"), "money"),
            Column("tax", _("Tax"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["amount"]},
    )


register(
    ReportDef(
        key="expenses",
        title=_("Expenses"),
        category="payroll",
        codename=CODENAME,
        description=_("Approved and waiting expense claims by category, tutor or month."),
        run=expenses,
        filters=("branch", "tutor", "client"),
        group_by=("category", "tutor", "month", "status", "branch"),
    )
)


def mileage(user: Any, params: Params) -> Result:
    qs = _expenses(user, params, mileage=True)
    rows = grouped(
        qs,
        params.group_by,
        {"claims": Count("pk"), "distance": Sum("distance"), "amount": Sum("amount_amount")},
        fields={"tutor": "tutor_id", "branch": "branch_id"},
    )
    for row in rows:
        row["distance"] = str(row["distance"] or 0)
    money_columns(rows, ("amount",))
    return Result(
        columns=[
            group_column(params),
            Column("currency", _("Currency")),
            Column("claims", _("Claims"), "count"),
            Column("distance", _("Distance"), "number"),
            Column("amount", _("Amount"), "money"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["distance"]},
    )


register(
    ReportDef(
        key="mileage",
        title=_("Mileage"),
        category="payroll",
        codename=CODENAME,
        description=_("Mileage claims by tutor or month."),
        run=mileage,
        filters=("branch", "tutor", "client"),
        group_by=("tutor", "month", "branch"),
    )
)
