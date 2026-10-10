"""Sales and growth reports (E26-T06): enquiry funnel, sources and conversion time, lost
reasons, retention cohorts, churned students and client lifetime value. Referral, affiliate
and review reports wait for E25."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils.translation import gettext_lazy as _

from .. import dims, periods
from ..models import FactCharge
from .base import (
    Column,
    Params,
    ReportDef,
    Result,
    filter_facts,
    money_columns,
    percent,
    register,
    scoped,
    scoped_by,
)

CODENAME = "reporting.sales.view"


def _enquiries(user: Any, params: Params) -> Any:
    from tutortrack.leads.models import Enquiry

    start, end = params.period.utc_bounds(periods.org_timezone())
    qs = scoped(user, Enquiry.objects.filter(created_at__gte=start, created_at__lt=end), CODENAME)
    return filter_facts(qs, params, {"branch": "branch_id", "client": "client_id"})


def enquiry_funnel(user: Any, params: Params) -> Result:
    from tutortrack.leads.models import EnquiryStageHistory, PipelineStage

    enquiries = _enquiries(user, params)
    totals = dict(
        enquiries.values("pipeline_id").annotate(n=Count("pk")).values_list("pipeline_id", "n")
    )
    reached = dict(
        EnquiryStageHistory.objects.filter(enquiry__in=enquiries)
        .values("to_stage")
        .annotate(n=Count("enquiry", distinct=True))
        .values_list("to_stage", "n")
    )
    current = dict(
        enquiries.values("stage_id").annotate(n=Count("pk")).values_list("stage_id", "n")
    )
    rows = []
    stages = PipelineStage.objects.filter(pipeline_id__in=totals).select_related("pipeline")
    for stage in stages.order_by("pipeline__name", "order"):
        total = totals.get(stage.pipeline_id, 0)
        count = max(reached.get(stage.pk, 0), current.get(stage.pk, 0))
        rows.append(
            {
                "pipeline": stage.pipeline.name,
                "group": stage.name,
                "group_id": str(stage.pk),
                "reached": count,
                "now": current.get(stage.pk, 0),
                "rate": percent(count, total),
            }
        )
    return Result(
        columns=[
            Column("pipeline", _("Pipeline")),
            Column("group", _("Stage")),
            Column("reached", _("Reached"), "count"),
            Column("now", _("At this stage now"), "count"),
            Column("rate", _("% of enquiries"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["reached"]},
        totals=[{"reached": sum(totals.values())}] if totals else [],
    )


register(
    ReportDef(
        key="enquiry_funnel",
        title=_("Enquiry funnel"),
        category="sales",
        codename=CODENAME,
        description=_("How far the period's enquiries got through each pipeline."),
        run=enquiry_funnel,
        filters=("branch", "client"),
        default_period="last_90_days",
    )
)


def enquiry_sources(user: Any, params: Params) -> Result:
    from tutortrack.leads.models import Enquiry

    qs = _enquiries(user, params)
    field = {"source": "source", "owner": "owner_id", "month": "month"}[params.group_by]
    if field == "month":
        qs = qs.annotate(month=TruncMonth("created_at"))
    data = (
        qs.values(field)
        .annotate(
            total=Count("pk"),
            won=Count("pk", filter=Q(status="won")),
            lost=Count("pk", filter=Q(status="lost")),
        )
        .order_by(field)
    )
    durations: dict[str, list[float]] = defaultdict(list)
    for e in qs.filter(status="won", won_at__isnull=False).values(field, "created_at", "won_at"):
        durations[str(e[field])].append((e["won_at"] - e["created_at"]).total_seconds() / 86400)
    sources = dict(Enquiry.Source.choices)
    owners: dict[str, str] = {}
    if field == "owner_id":
        from django.contrib.auth import get_user_model

        ids = [r["owner_id"] for r in data if r["owner_id"]]
        owners = {
            str(u.pk): (u.get_full_name() or u.email)
            for u in get_user_model().objects.filter(pk__in=ids)
        }
    rows = []
    for r in data:
        raw = r[field]
        if field == "source":
            label = str(sources.get(raw, raw))
        elif field == "owner_id":
            label = owners.get(str(raw), str(_("Unassigned")))
        else:
            label = raw.date().isoformat() if raw else ""
        days = durations.get(str(raw), [])
        closed = r["won"] + r["lost"]
        rows.append(
            {
                "group": label,
                "group_id": str(raw or ""),
                "total": r["total"],
                "won": r["won"],
                "lost": r["lost"],
                "conversion": percent(r["won"], closed),
                "days_to_win": str(round(Decimal(sum(days) / len(days)), 1)) if days else "",
            }
        )
    return Result(
        columns=[
            Column(
                "group",
                {"source": _("Source"), "owner": _("Owner"), "month": _("Month")}[params.group_by],
            ),
            Column("total", _("Enquiries"), "count"),
            Column("won", _("Won"), "count"),
            Column("lost", _("Lost"), "count"),
            Column("conversion", _("Win rate %"), "percent"),
            Column("days_to_win", _("Average days to win"), "number"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["total", "won"]},
        totals=[
            {
                "total": sum(r["total"] for r in rows),
                "won": sum(r["won"] for r in rows),
                "lost": sum(r["lost"] for r in rows),
                "conversion": percent(
                    sum(r["won"] for r in rows), sum(r["won"] + r["lost"] for r in rows)
                ),
            }
        ],
    )


register(
    ReportDef(
        key="enquiry_sources",
        title=_("Enquiry sources and conversion"),
        category="sales",
        codename=CODENAME,
        description=_("Where enquiries came from, how many were won and how long it took."),
        run=enquiry_sources,
        filters=("branch", "client"),
        group_by=("source", "owner", "month"),
        default_period="last_90_days",
    )
)


def lost_reasons(user: Any, params: Params) -> Result:
    qs = _enquiries(user, params).filter(status="lost")
    data = qs.values("lost_reason").annotate(n=Count("pk")).order_by("-n")
    total = sum(r["n"] for r in data)
    rows = [
        {
            "group": r["lost_reason"] or str(_("No reason given")),
            "group_id": r["lost_reason"],
            "lost": r["n"],
            "share": percent(r["n"], total),
        }
        for r in data
    ]
    return Result(
        columns=[
            Column("group", _("Reason")),
            Column("lost", _("Enquiries lost"), "count"),
            Column("share", _("Share %"), "percent"),
        ],
        rows=rows,
        chart={"type": "pie", "x": "group", "y": ["lost"]},
        totals=[{"lost": total}],
    )


register(
    ReportDef(
        key="lost_reasons",
        title=_("Lost enquiry reasons"),
        category="sales",
        codename=CODENAME,
        description=_("Why enquiries were lost."),
        run=lost_reasons,
        filters=("branch", "client"),
        default_period="last_90_days",
    )
)


# --- retention ----------------------------------------------------------------------------------


def _active_months(user: Any, params: Params, start: date, end: date) -> dict[str, set[date]]:
    """Months in which each student had a delivered lesson, in [start, end]."""
    from tutortrack.scheduling.models import LessonAttendee

    tz = periods.org_timezone()
    since, until = periods.Period(start, end).utc_bounds(tz)
    qs = scoped_by(
        user,
        LessonAttendee.objects.filter(
            lesson__status="completed", lesson__start__gte=since, lesson__start__lt=until
        ).exclude(
            outcome__in=("no_show", "cancelled_client", "cancelled_tutor", "cancelled_admin")
        ),
        CODENAME,
        branch="lesson__branch_id",
    )
    qs = filter_facts(
        qs,
        params,
        {"branch": "lesson__branch_id", "client": "client_id", "service": "lesson__service_id"},
    )
    from zoneinfo import ZoneInfo

    months: dict[str, set[date]] = defaultdict(set)
    for student_id, month in (
        qs.annotate(m=TruncMonth("lesson__start", tzinfo=ZoneInfo(tz)))
        .values_list("student_id", "m")
        .distinct()
    ):
        months[str(student_id)].add(month.date() if hasattr(month, "date") else month)
    return months


def _month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def retention(user: Any, params: Params) -> Result:
    """Students by the month of their first delivered lesson, and the share still having
    lessons 1, 3 and 6 months later."""
    today = periods.org_today()
    months = _active_months(user, params, date(2000, 1, 1), today)
    cohorts: dict[date, list[set[int]]] = defaultdict(list)
    for active in months.values():
        first = min(active)
        if params.period.start <= first <= params.period.end:
            cohorts[first].append({_month_index(m) for m in active})
    rows = []
    for cohort in sorted(cohorts):
        students = cohorts[cohort]
        base = _month_index(cohort)
        row: dict[str, Any] = {
            "group": cohort.isoformat()[:7],
            "group_id": cohort.isoformat(),
            "students": len(students),
        }
        for offset in (1, 3, 6):
            if base + offset > _month_index(today):
                row[f"m{offset}"] = ""
                continue
            kept = sum(1 for s in students if any(m >= base + offset for m in s))
            row[f"m{offset}"] = percent(kept, len(students))
        rows.append(row)
    return Result(
        columns=[
            Column("group", _("First lesson month")),
            Column("students", _("New students"), "count"),
            Column("m1", _("Still learning after 1 month %"), "percent"),
            Column("m3", _("After 3 months %"), "percent"),
            Column("m6", _("After 6 months %"), "percent"),
        ],
        rows=rows,
        chart={"type": "line", "x": "group", "y": ["m1", "m3", "m6"]},
    )


register(
    ReportDef(
        key="retention",
        title=_("Student retention cohorts"),
        category="sales",
        codename=CODENAME,
        description=_("Of the students who started each month, how many kept having lessons."),
        run=retention,
        filters=("branch", "client", "service"),
        default_period="last_12_months",
    )
)


def churned(user: Any, params: Params, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Students with delivered lessons in the comparison period but none in this one."""
    previous = periods.comparison(params.period, "previous_period") or params.period
    months_before = _active_months(user, params, previous.start, previous.end)
    months_now = _active_months(user, params, params.period.start, params.period.end)
    gone = [s for s in months_before if s not in months_now]
    names = dims.labels("student", gone)
    rows = [
        {"id": s, "student": names.get(s, ""), "last_month": max(months_before[s]).isoformat()[:7]}
        for s in gone[:limit]
    ]
    rows.sort(key=lambda r: r["student"])
    return rows


def churned_students(user: Any, params: Params) -> Result:
    return Result(
        columns=[
            Column("student", _("Student")),
            Column("last_month", _("Last lesson month")),
        ],
        rows=churned(user, params),
        totals=[],
    )


register(
    ReportDef(
        key="churned_students",
        title=_("Churned students"),
        category="sales",
        codename=CODENAME,
        description=_("Students who had lessons in the previous period but none in this one."),
        run=churned_students,
        filters=("branch", "client", "service"),
    )
)


def lifetime_value(user: Any, params: Params) -> Result:
    qs = scoped(user, FactCharge.objects.exclude(status="void"), CODENAME)
    qs = filter_facts(
        qs,
        params,
        {
            "branch": "branch_id",
            "client": "client_id",
            "service": "service_id",
            "subject": "subject_id",
        },
    )
    data = (
        qs.values("client_id", "currency")
        .annotate(
            revenue=Sum("net_amount"),
            first=Min("date"),
            last=Max("date"),
            students=Count("student_id", distinct=True),
            lessons=Count("lesson_id", distinct=True),
        )
        .order_by("client_id")
    )
    names = dims.labels("client", (r["client_id"] for r in data))
    rows = []
    for r in data:
        months = _month_index(r["last"]) - _month_index(r["first"]) + 1
        revenue = Decimal(r["revenue"] or 0)
        rows.append(
            {
                "group": names.get(str(r["client_id"]), ""),
                "group_id": str(r["client_id"]),
                "currency": r["currency"],
                "first": r["first"].isoformat(),
                "last": r["last"].isoformat(),
                "months": months,
                "students": r["students"],
                "lessons": r["lessons"],
                "revenue": revenue,
                "per_month": revenue / months,
            }
        )
    money_columns(rows, ("revenue", "per_month"))
    result = Result(
        columns=[
            Column("group", _("Client")),
            Column("currency", _("Currency")),
            Column("first", _("First charge"), "date"),
            Column("last", _("Latest charge"), "date"),
            Column("months", _("Months"), "count"),
            Column("students", _("Students"), "count"),
            Column("lessons", _("Lessons"), "count"),
            Column("revenue", _("Lifetime revenue (net)"), "money"),
            Column("per_month", _("Per month"), "money"),
        ],
        rows=rows,
    )
    by: dict[str, list[Decimal]] = defaultdict(list)
    for row in rows:
        by[row["currency"]].append(Decimal(row["revenue"]))
    result.totals = [
        {
            "currency": c,
            "revenue": str(sum(v)),
            "per_month": "",
            "lessons": sum(r["lessons"] for r in rows if r["currency"] == c),
            "months": "",
            "students": sum(r["students"] for r in rows if r["currency"] == c),
            "average": str((sum(v, Decimal(0)) / len(v)).quantize(Decimal("0.01"))),
        }
        for c, v in sorted(by.items())
    ]
    return result


register(
    ReportDef(
        key="lifetime_value",
        title=_("Client lifetime value"),
        category="sales",
        codename=CODENAME,
        description=_("Everything each client has been charged, over how many months."),
        run=lifetime_value,
        filters=("branch", "client", "service", "subject", "tag", "custom_field"),
        period=False,
        ordering="-revenue",
    )
)
