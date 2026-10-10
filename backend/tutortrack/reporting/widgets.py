"""Dashboard widgets and role layouts (E26-T02, E26-T03, FR-26-1).

A widget computes one tile for a period (with an optional comparison period and branch
filter) under its permission's data scope, and names the report it drills into. Layouts are
ordered ``{"widget": key, "size": "s"|"m"|"l"}`` lists: the user's own, or a preset for
their role (``simple`` is the MVP dashboard for sole traders).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils.translation import gettext_lazy as _

from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now

from . import dims, periods
from .models import DailyAggregate, FactCharge, FactLesson, FactPayItem, FactPayment
from .reports.base import Params, hours, money, my_tutor_ids, percent, scoped, scoped_by

SIZES = ("s", "m", "l")


@dataclass
class Context:
    user: Any
    period: periods.Period
    previous: periods.Period | None
    branch: list[str]
    today: Any
    preset: str = "this_month"

    def params(self, period: periods.Period | None = None) -> Params:
        return Params(period=period or self.period, preset=self.preset, branch=list(self.branch))


@dataclass
class Data:
    unit: str = "count"  # count | money | percent | hours
    values: list[dict[str, Any]] = field(default_factory=list)  # {label, currency, value, previous}
    series: list[dict[str, Any]] = field(default_factory=list)  # {x, y: {name: value}}
    rows: list[dict[str, Any]] = field(default_factory=list)  # {label, value, detail}
    report_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Widget:
    key: str
    title: Any
    category: str
    codename: str
    kind: str  # kpi | chart | list
    compute: Callable[[Context], Data]
    report: str = ""
    size: str = "s"

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": str(self.title),
            "category": self.category,
            "kind": self.kind,
            "default_size": self.size,
            "report": self.report,
        }


_widgets: dict[str, Widget] = {}


def widget(
    key: str,
    title: Any,
    category: str,
    codename: str,
    kind: str = "kpi",
    *,
    report: str = "",
    size: str = "",
) -> Callable[[Callable[[Context], Data]], Callable[[Context], Data]]:
    def decorator(fn: Callable[[Context], Data]) -> Callable[[Context], Data]:
        default = size or {"kpi": "s", "list": "m", "chart": "l"}[kind]
        _widgets[key] = Widget(key, title, category, codename, kind, fn, report, default)
        return fn

    return decorator


def get(key: str) -> Widget | None:
    return _widgets.get(key)


def available(user: Any) -> list[Widget]:
    return [w for w in _widgets.values() if has_perm(user, w.codename)]


# --- helpers ------------------------------------------------------------------------------------

FIN = "reporting.finance.view"
OPS = "reporting.operations.view"
PAY = "reporting.payroll.view"
SALES = "reporting.sales.view"
PEOPLE = "reporting.people.view"


def _in(qs: Any, period: periods.Period, lookup: str = "date") -> Any:
    return qs.filter(**{f"{lookup}__gte": period.start, f"{lookup}__lte": period.end})


def _branch(qs: Any, ctx: Context, lookup: str = "branch_id") -> Any:
    return qs.filter(**{f"{lookup}__in": ctx.branch}) if ctx.branch else qs


def _money_by_currency(
    ctx: Context, compute: Callable[[periods.Period], dict[str, Decimal]], label: str = ""
) -> list[dict[str, Any]]:
    now_values = compute(ctx.period)
    before = compute(ctx.previous) if ctx.previous else {}
    currencies = sorted(set(now_values) | set(before))
    return [
        {
            "label": label,
            "currency": c,
            "value": money(now_values.get(c, 0), c),
            "previous": money(before.get(c, 0), c) if ctx.previous else None,
        }
        for c in currencies
    ]


def _count(
    ctx: Context, compute: Callable[[periods.Period], int], label: str = ""
) -> dict[str, Any]:
    return {
        "label": label,
        "currency": "",
        "value": str(compute(ctx.period)),
        "previous": str(compute(ctx.previous)) if ctx.previous else None,
    }


def _sum_by_currency(qs: Any, amount: str) -> dict[str, Decimal]:
    return {
        r["currency"]: Decimal(r["t"] or 0)
        for r in qs.values("currency").annotate(t=Sum(amount)).order_by("currency")
    }


# --- finance ------------------------------------------------------------------------------------


@widget("revenue", _("Revenue"), "finance", FIN, report="revenue")
def revenue(ctx: Context) -> Data:
    def compute(period: periods.Period) -> dict[str, Decimal]:
        qs = scoped(ctx.user, FactCharge.objects.exclude(status="void"), FIN)
        return _sum_by_currency(_branch(_in(qs, period), ctx), "net_amount")

    return Data(unit="money", values=_money_by_currency(ctx, compute))


@widget("invoiced", _("Invoiced"), "finance", FIN, report="invoices_register")
def invoiced(ctx: Context) -> Data:
    from tutortrack.billing.models import Invoice

    def compute(period: periods.Period) -> dict[str, Decimal]:
        qs = scoped(ctx.user, Invoice.objects.exclude(status__in=("draft", "void")), FIN)
        return _sum_by_currency(_branch(_in(qs, period, "issue_date"), ctx), "total_amount")

    return Data(unit="money", values=_money_by_currency(ctx, compute))


@widget("collected", _("Collected"), "finance", FIN, report="payments_received")
def collected(ctx: Context) -> Data:
    def compute(period: periods.Period) -> dict[str, Decimal]:
        qs = scoped(
            ctx.user,
            FactPayment.objects.filter(
                status__in=("succeeded", "partially_refunded", "refunded", "disputed")
            ),
            FIN,
        )
        qs = _branch(_in(qs, period), ctx)
        out: dict[str, Decimal] = {}
        for r in qs.values("currency").annotate(a=Sum("amount_amount"), r=Sum("refunded_amount")):
            out[r["currency"]] = Decimal(r["a"] or 0) - Decimal(r["r"] or 0)
        return out

    return Data(unit="money", values=_money_by_currency(ctx, compute))


@widget("outstanding", _("Outstanding and overdue"), "finance", FIN, "list", report="aged_debtors")
def outstanding(ctx: Context) -> Data:
    from tutortrack.billing.models import Invoice
    from tutortrack.billing.selectors import bucket_for

    qs = _branch(scoped(ctx.user, Invoice.objects.filter(status__in=Invoice.OPEN), FIN), ctx)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    overdue: dict[str, Decimal] = defaultdict(Decimal)
    buckets: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for inv in qs.filter(balance_due_amount__gt=0).only(
        "currency", "due_date", "balance_due_amount"
    ):
        days = (ctx.today - inv.due_date).days if inv.due_date else 0
        totals[inv.currency] += inv.balance_due_amount
        if days > 0:
            overdue[inv.currency] += inv.balance_due_amount
        buckets[(bucket_for(days), inv.currency)] += inv.balance_due_amount
    values = []
    for c in sorted(totals):
        values.append(
            {
                "label": str(_("Outstanding")),
                "currency": c,
                "value": money(totals[c], c),
                "previous": None,
            }
        )
        values.append(
            {
                "label": str(_("Overdue")),
                "currency": c,
                "value": money(overdue[c], c),
                "previous": None,
            }
        )
    labels = {
        "current": _("Not yet due"),
        "1_30": _("1\N{EN DASH}30 days"),
        "31_60": _("31\N{EN DASH}60 days"),
        "61_90": _("61\N{EN DASH}90 days"),
        "90_plus": _("Over 90 days"),
    }
    rows = [
        {"label": str(labels[b]), "value": money(buckets[(b, c)], c), "detail": c}
        for c in sorted(totals)
        for b in labels
        if buckets.get((b, c))
    ]
    return Data(unit="money", values=values, rows=rows)


@widget("uninvoiced", _("Not yet invoiced"), "finance", FIN, report="uninvoiced_charges")
def uninvoiced(ctx: Context) -> Data:
    qs = _branch(scoped(ctx.user, FactCharge.objects.filter(status="uninvoiced"), FIN), ctx)
    values = [
        {"label": "", "currency": c, "value": money(v, c), "previous": None}
        for c, v in _sum_by_currency(qs, "gross_amount").items()
    ]
    return Data(unit="money", values=values, report_params={"period": "last_12_months"})


@widget("margin", _("Margin"), "finance", FIN, report="margin")
def margin(ctx: Context) -> Data:
    def parts(period: periods.Period) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        charges = _branch(
            _in(scoped(ctx.user, FactCharge.objects.exclude(status="void"), FIN), period), ctx
        )
        pay = _branch(
            _in(
                scoped(
                    ctx.user,
                    FactPayItem.objects.exclude(status="void").filter(
                        kind__in=("lesson", "cancellation", "charge_share", "event")
                    ),
                    FIN,
                ),
                period,
            ),
            ctx,
        )
        return _sum_by_currency(charges, "net_amount"), _sum_by_currency(pay, "amount_amount")

    rev, cost = parts(ctx.period)
    prev_rev, prev_cost = parts(ctx.previous) if ctx.previous else ({}, {})
    values = []
    for c in sorted(set(rev) | set(cost)):
        m = rev.get(c, Decimal(0)) - cost.get(c, Decimal(0))
        pm = prev_rev.get(c, Decimal(0)) - prev_cost.get(c, Decimal(0))
        values.append(
            {
                "label": f"{percent(m, rev.get(c))}%",
                "currency": c,
                "value": money(m, c),
                "previous": money(pm, c) if ctx.previous else None,
            }
        )
    return Data(unit="money", values=values)


@widget("cash_forecast", _("Cash forecast"), "finance", FIN, "list", report="cash_forecast")
def cash_forecast(ctx: Context) -> Data:
    from .reports.finance import forecast_rows

    rows = forecast_rows(ctx.user, ctx.params())
    return Data(
        unit="money",
        rows=[{"label": r["group"], "value": r["revenue"], "detail": r["currency"]} for r in rows],
    )


@widget("revenue_trend", _("Revenue trend"), "finance", FIN, "chart", report="revenue")
def revenue_trend(ctx: Context) -> Data:
    qs = _branch(
        _in(scoped(ctx.user, DailyAggregate.objects.exclude(currency=""), FIN), ctx.period), ctx
    )
    monthly = ctx.period.days > 62
    if monthly:
        data = (
            qs.annotate(x=TruncMonth("date"))
            .values("x", "currency")
            .annotate(t=Sum("revenue"), c=Sum("collected"))
            .order_by("x")
        )
    else:
        data = qs.values("date", "currency").annotate(t=Sum("revenue"), c=Sum("collected"))
        data = data.order_by("date")
    series = []
    for r in data:
        x = r["x"] if monthly else r["date"]
        series.append(
            {
                "x": x.isoformat()[: 7 if monthly else 10],
                "currency": r["currency"],
                "y": {
                    "revenue": money(r["t"], r["currency"]),
                    "collected": money(r["c"], r["currency"]),
                },
            }
        )
    return Data(
        unit="money", series=series, report_params={"group_by": "month" if monthly else "day"}
    )


# --- payroll ------------------------------------------------------------------------------------


@widget("next_pay_run", _("Next pay run"), "payroll", PAY, report="tutor_earnings")
def next_pay_run(ctx: Context) -> Data:
    qs = scoped(
        ctx.user, FactPayItem.objects.filter(status__in=("ready", "in_pay_run", "approved")), PAY
    )
    qs = _branch(qs, ctx)
    values = [
        {"label": "", "currency": c, "value": money(v, c), "previous": None}
        for c, v in _sum_by_currency(qs, "amount_amount").items()
    ]
    return Data(unit="money", values=values, report_params={"period": "last_90_days"})


@widget("earnings", _("Earnings"), "payroll", PAY, report="tutor_earnings")
def earnings(ctx: Context) -> Data:
    def compute(period: periods.Period) -> dict[str, Decimal]:
        qs = scoped(ctx.user, FactPayItem.objects.exclude(status="void"), PAY)
        return _sum_by_currency(_branch(_in(qs, period), ctx), "amount_amount")

    return Data(unit="money", values=_money_by_currency(ctx, compute))


# --- operations ---------------------------------------------------------------------------------


def _lessons(ctx: Context, period: periods.Period) -> Any:
    qs = scoped(ctx.user, FactLesson.objects.all(), OPS)
    if has_perm(ctx.user, OPS) and not my_own_only(ctx.user, OPS):
        qs = qs.filter(primary=True)
    return _branch(_in(qs, period), ctx)


def my_own_only(user: Any, codename: str) -> bool:
    from tutortrack.core.permissions import permission_scope

    return permission_scope(user, codename) == "own"


@widget("lessons", _("Lessons delivered"), "operations", OPS, report="lessons")
def lessons(ctx: Context) -> Data:
    def stats(period: periods.Period) -> dict[str, Any]:
        return (
            _lessons(ctx, period)
            .filter(status="completed")
            .aggregate(n=Count("pk"), m=Sum("delivered_minutes"))
        )

    cur = stats(ctx.period)
    prev = stats(ctx.previous) if ctx.previous else None
    return Data(
        unit="count",
        values=[
            {
                "label": str(_("Lessons")),
                "currency": "",
                "value": str(cur["n"]),
                "previous": str(prev["n"]) if prev else None,
            },
            {
                "label": str(_("Hours")),
                "currency": "",
                "value": hours(cur["m"]),
                "previous": hours(prev["m"]) if prev else None,
            },
        ],
    )


@widget("cancellation_rate", _("Cancellation rate"), "operations", OPS, report="cancellations")
def cancellation_rate(ctx: Context) -> Data:
    def rate(period: periods.Period) -> str:
        agg = (
            _lessons(ctx, period)
            .exclude(status="planned")
            .aggregate(n=Count("pk"), c=Count("pk", filter=Q(status="cancelled")))
        )
        return percent(agg["c"], agg["n"])

    return Data(
        unit="percent",
        values=[
            {
                "label": "",
                "currency": "",
                "value": rate(ctx.period),
                "previous": rate(ctx.previous) if ctx.previous else None,
            }
        ],
    )


@widget("upcoming_today", _("Today's lessons"), "operations", OPS, "list", report="lessons")
def upcoming_today(ctx: Context) -> Data:
    qs = _lessons(ctx, periods.Period(ctx.today, ctx.today)).exclude(status="cancelled")
    facts = list(qs.order_by("start")[:20])
    services = dims.labels("service", (f.service_id for f in facts))
    lesson_tutors: dict[str, list[str]] = defaultdict(list)
    all_rows = FactLesson.objects.filter(lesson_id__in=[f.lesson_id for f in facts])
    names = dims.labels("tutor", all_rows.values_list("tutor_id", flat=True))
    for r in all_rows.exclude(tutor_id__isnull=True).order_by("created_at"):
        lesson_tutors[str(r.lesson_id)].append(names.get(str(r.tutor_id), ""))
    tz = periods.org_timezone()
    from zoneinfo import ZoneInfo

    rows = [
        {
            "label": f.start.astimezone(ZoneInfo(tz)).strftime("%H:%M"),
            "value": services.get(str(f.service_id), ""),
            "detail": ", ".join(lesson_tutors.get(str(f.lesson_id), [])),
            "id": str(f.lesson_id),
        }
        for f in facts
    ]
    return Data(
        unit="count",
        values=[{"label": "", "currency": "", "value": str(qs.count()), "previous": None}],
        rows=rows,
        report_params={"period": "today", "group_by": "status"},
    )


@widget("unconfirmed", _("Unconfirmed lessons"), "operations", OPS, report="unconfirmed_lessons")
def unconfirmed(ctx: Context) -> Data:
    qs = scoped(ctx.user, FactLesson.objects.filter(status="planned", end__lt=now()), OPS)
    n = _branch(qs, ctx).values("lesson_id").distinct().count()
    return Data(values=[{"label": "", "currency": "", "value": str(n), "previous": None}])


@widget("overdue_reports", _("Overdue lesson reports"), "operations", OPS, report="report_sla")
def overdue_reports(ctx: Context) -> Data:
    from tutortrack.delivery.models import LessonReport

    qs = scoped_by(
        ctx.user,
        LessonReport.objects.filter(submitted_at__isnull=True, due_at__lt=now()).exclude(
            status__in=("submitted", "approved")
        ),
        OPS,
        branch="lesson__branch_id",
        own=Q(tutor_id__in=my_tutor_ids(ctx.user)),
    )
    n = _branch(qs, ctx, "lesson__branch_id").count()
    return Data(values=[{"label": "", "currency": "", "value": str(n), "previous": None}])


@widget("utilisation", _("Tutor utilisation"), "operations", OPS, report="tutor_utilisation")
def utilisation(ctx: Context) -> Data:
    from .reports.operations import tutor_utilisation

    def rate(period: periods.Period) -> str:
        result = tutor_utilisation(ctx.user, ctx.params(period))
        return str(result.totals[0]["utilisation"]) if result.totals else "0.0"

    return Data(
        unit="percent",
        values=[
            {
                "label": "",
                "currency": "",
                "value": rate(ctx.period),
                "previous": rate(ctx.previous) if ctx.previous else None,
            }
        ],
    )


@widget("lessons_trend", _("Lessons trend"), "operations", OPS, "chart", report="lessons")
def lessons_trend(ctx: Context) -> Data:
    qs = _branch(
        _in(scoped(ctx.user, DailyAggregate.objects.filter(currency=""), OPS), ctx.period), ctx
    )
    data = (
        qs.values("date")
        .annotate(c=Sum("lessons_completed"), x=Sum("lessons_cancelled"))
        .order_by("date")
    )
    series = [
        {
            "x": r["date"].isoformat(),
            "currency": "",
            "y": {"completed": str(r["c"]), "cancelled": str(r["x"])},
        }
        for r in data
    ]
    return Data(unit="count", series=series, report_params={"group_by": "day"})


# --- people and sales ---------------------------------------------------------------------------


@widget(
    "active_people",
    _("Active students, clients and tutors"),
    "people",
    PEOPLE,
    "list",
    report="active_students",
)
def active_people(ctx: Context) -> Data:
    from tutortrack.people.models import Client, Student, TutorProfile

    students = _branch(scoped(ctx.user, Student.objects.filter(status="active"), PEOPLE), ctx)
    clients = _branch(scoped(ctx.user, Client.objects.filter(status="active"), PEOPLE), ctx)
    tutors = scoped_by(
        ctx.user,
        TutorProfile.objects.filter(status="active"),
        PEOPLE,
        branch="branches",
        own=Q(membership__user=ctx.user),
    )
    if ctx.branch:
        tutors = tutors.filter(branches__in=ctx.branch)
    rows = [
        {"label": str(_("Students")), "value": str(students.count()), "detail": ""},
        {"label": str(_("Clients")), "value": str(clients.count()), "detail": ""},
        {"label": str(_("Tutors")), "value": str(tutors.distinct().count()), "detail": ""},
    ]
    return Data(rows=rows)


@widget("compliance_expiring", _("Checks expiring"), "people", PEOPLE, report="tutor_compliance")
def compliance_expiring(ctx: Context) -> Data:
    from tutortrack.people.models import TutorProfile
    from tutortrack.recruitment.models import ComplianceRecord

    tutors = scoped_by(
        ctx.user,
        TutorProfile.objects.all(),
        PEOPLE,
        branch="branches",
        own=Q(membership__user=ctx.user),
    )
    soon = ctx.today + timedelta(days=30)
    n = ComplianceRecord.objects.filter(
        tutor__in=tutors, status="verified", expiry_date__isnull=False, expiry_date__lte=soon
    ).count()
    return Data(values=[{"label": "", "currency": "", "value": str(n), "previous": None}])


@widget("enquiries", _("New enquiries"), "sales", SALES, report="enquiry_sources")
def enquiries(ctx: Context) -> Data:
    from tutortrack.leads.models import Enquiry

    tz = periods.org_timezone()

    def stats(period: periods.Period) -> dict[str, int]:
        start, end = period.utc_bounds(tz)
        qs = scoped(
            ctx.user, Enquiry.objects.filter(created_at__gte=start, created_at__lt=end), SALES
        )
        return _branch(qs, ctx).aggregate(
            n=Count("pk"),
            won=Count("pk", filter=Q(status="won")),
            closed=Count("pk", filter=~Q(status="open")),
        )

    cur = stats(ctx.period)
    prev = stats(ctx.previous) if ctx.previous else None
    return Data(
        values=[
            {
                "label": str(_("Enquiries")),
                "currency": "",
                "value": str(cur["n"]),
                "previous": str(prev["n"]) if prev else None,
            },
            {
                "label": str(_("Win rate %")),
                "currency": "",
                "value": percent(cur["won"], cur["closed"]),
                "previous": percent(prev["won"], prev["closed"]) if prev else None,
            },
        ]
    )


@widget("churned_students", _("Churned students"), "sales", SALES, report="churned_students")
def churned_students(ctx: Context) -> Data:
    from .reports.sales import churned

    n = len(churned(ctx.user, ctx.params()))
    return Data(values=[{"label": "", "currency": "", "value": str(n), "previous": None}])


# --- layouts ------------------------------------------------------------------------------------

PRESETS: dict[str, list[str]] = {
    "simple": ["revenue", "outstanding", "lessons", "upcoming_today"],
    "owner": [
        "revenue",
        "collected",
        "outstanding",
        "margin",
        "lessons",
        "cancellation_rate",
        "enquiries",
        "active_people",
        "revenue_trend",
        "cash_forecast",
        "upcoming_today",
        "unconfirmed",
    ],
    "coordinator": [
        "lessons",
        "upcoming_today",
        "unconfirmed",
        "overdue_reports",
        "cancellation_rate",
        "utilisation",
        "enquiries",
        "active_people",
        "compliance_expiring",
        "churned_students",
        "lessons_trend",
    ],
    "finance": [
        "revenue",
        "invoiced",
        "collected",
        "outstanding",
        "uninvoiced",
        "margin",
        "next_pay_run",
        "cash_forecast",
        "revenue_trend",
    ],
    "tutor": ["upcoming_today", "lessons", "earnings", "overdue_reports"],
}
ROLE_PRESET = {
    "owner": "owner",
    "admin": "owner",
    "branch_manager": "owner",
    "coordinator": "coordinator",
    "finance": "finance",
    "tutor": "tutor",
}


def preset_for(role: str, setting: str, active_tutors: int) -> str:
    if setting == "simple":
        return "simple"
    if setting == "auto" and role in ("owner", "admin") and active_tutors <= 1:
        return "simple"
    return ROLE_PRESET.get(role, "coordinator")


def preset_layout(name: str, user: Any) -> list[dict[str, str]]:
    allowed = {w.key for w in available(user)}
    return [{"widget": key, "size": _widgets[key].size} for key in PRESETS[name] if key in allowed]
