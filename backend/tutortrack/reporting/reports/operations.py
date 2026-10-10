"""Operations reports (E26-T05): lessons, attendance, cancellations, utilisation, report SLA,
unconfirmed lessons and location use. Tutors with ``reporting.operations.view:own`` see
their own lessons."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, Sum
from django.utils.translation import gettext_lazy as _

from tutortrack.core.time import now

from .. import dims
from ..models import FactLesson
from .base import (
    Column,
    Params,
    ReportDef,
    Result,
    filter_facts,
    group_column,
    grouped,
    hours,
    in_period,
    my_tutor_ids,
    percent,
    register,
    scoped,
    scoped_by,
)

CODENAME = "reporting.operations.view"
LESSON_FIELDS = {
    "branch": "branch_id",
    "tutor": "tutor_id",
    "service": "service_id",
    "subject": "subject_id",
    "job": "job_id",
    "location": "location_id",
}
LESSON_FILTERS = ("branch", "tutor", "service", "subject")
STATUS_LABELS = {
    "planned": _("Planned"),
    "completed": _("Completed"),
    "cancelled": _("Cancelled"),
    "missed": _("Missed"),
}


def lesson_facts(user: Any, params: Params, *, primary: bool | None = True) -> Any:
    qs = scoped(user, FactLesson.objects.all(), CODENAME)
    if primary is not None and not params.tutor:
        qs = qs.filter(primary=primary)
    return filter_facts(in_period(qs, params), params, LESSON_FIELDS)


def lessons_by_status(user: Any, params: Params) -> Result:
    # Grouped by tutor, each tutor counts the lessons they teach (shared ones too).
    qs = lesson_facts(user, params, primary=None if params.group_by == "tutor" else True)
    rows = grouped(
        qs,
        params.group_by,
        {
            "lessons": Count("pk"),
            "completed": Count("pk", filter=Q(status="completed")),
            "cancelled": Count("pk", filter=Q(status="cancelled")),
            "missed": Count("pk", filter=Q(status="missed")),
            "planned": Count("pk", filter=Q(status="planned")),
            "scheduled": Sum("minutes"),
            "delivered": Sum("delivered_minutes"),
        },
        fields=LESSON_FIELDS,
        by_currency=False,
        choices=STATUS_LABELS if params.group_by == "status" else None,
    )
    for row in rows:
        row["scheduled"] = hours(row["scheduled"])
        row["delivered"] = hours(row["delivered"])
        row["cancellation_rate"] = percent(row["cancelled"], row["lessons"])
    return Result(
        columns=[
            group_column(params),
            Column("lessons", _("Lessons"), "count"),
            Column("completed", _("Completed"), "count"),
            Column("cancelled", _("Cancelled"), "count"),
            Column("missed", _("Missed"), "count"),
            Column("planned", _("Planned"), "count"),
            Column("scheduled", _("Scheduled hours"), "hours"),
            Column("delivered", _("Delivered hours"), "hours"),
            Column("cancellation_rate", _("Cancelled %"), "percent"),
        ],
        rows=rows,
        chart={
            "type": "bar",
            "x": "group",
            "y": ["completed", "cancelled", "missed"],
            "stacked": True,
        },
    )


register(
    ReportDef(
        key="lessons",
        title=_("Lessons by status"),
        category="operations",
        codename=CODENAME,
        description=_("Lessons and hours by status, month, tutor, service or branch."),
        run=lessons_by_status,
        filters=LESSON_FILTERS,
        group_by=("status", "month", "week", "day", "tutor", "service", "subject", "branch"),
    )
)


# --- attendance and cancellations ---------------------------------------------------------------


def _attendees(user: Any, params: Params) -> Any:
    from tutortrack.scheduling.models import LessonAttendee

    qs = LessonAttendee.objects.filter(
        lesson__in=lesson_facts(user, params, primary=None).values("lesson_id")
    )
    return qs


def attendance(user: Any, params: Params) -> Result:
    from tutortrack.scheduling.models import LessonAttendee

    qs = _attendees(user, params).exclude(outcome="")
    field = {
        "outcome": "outcome",
        "student": "student_id",
        "service": "lesson__service_id",
        "month": None,
    }[params.group_by]
    if field is None:
        from django.db.models.functions import TruncMonth

        data = (
            qs.annotate(m=TruncMonth("lesson__start"))
            .values("m", "outcome")
            .annotate(n=Count("pk"))
            .order_by("m")
        )
        by: dict[str, dict[str, Any]] = {}
        for r in data:
            label = r["m"].date().isoformat()
            row = by.setdefault(label, {"group": label, "group_id": label, "total": 0})
            row[r["outcome"]] = row.get(r["outcome"], 0) + r["n"]
            row["total"] += r["n"]
        rows = list(by.values())
    else:
        data = qs.values(field, "outcome").annotate(n=Count("pk")).order_by(field)
        names = (
            dims.labels(
                "student" if params.group_by == "student" else "service", (r[field] for r in data)
            )
            if params.group_by != "outcome"
            else {}
        )
        outcomes = dict(LessonAttendee.Outcome.choices)
        by = {}
        for r in data:
            raw = r[field]
            label = (
                str(outcomes.get(raw, raw))
                if params.group_by == "outcome"
                else names.get(str(raw), "")
            )
            row = by.setdefault(str(raw), {"group": label, "group_id": str(raw), "total": 0})
            row[r["outcome"]] = row.get(r["outcome"], 0) + r["n"]
            row["total"] += r["n"]
        rows = list(by.values())
    keys = [o for o, _label in LessonAttendee.Outcome.choices]
    for row in rows:
        for k in keys:
            row.setdefault(k, 0)
        attended = row["present"] + row["late"]
        row["attendance_rate"] = percent(attended, row["total"])
    columns = [
        Column(
            "group",
            {
                "outcome": _("Outcome"),
                "student": _("Student"),
                "service": _("Service"),
                "month": _("Month"),
            }[params.group_by],
        )
    ]
    if params.group_by == "outcome":
        columns.append(Column("total", _("Attendees"), "count"))
    else:
        columns += [Column(k, label, "count") for k, label in LessonAttendee.Outcome.choices]
        columns += [
            Column("total", _("Attendees"), "count"),
            Column("attendance_rate", _("Attended %"), "percent"),
        ]
    return Result(
        columns=columns,
        rows=rows,
        chart={
            "type": "pie" if params.group_by == "outcome" else "bar",
            "x": "group",
            "y": ["total"]
            if params.group_by == "outcome"
            else ["present", "no_show", "absent_notified"],
        },
    )


register(
    ReportDef(
        key="attendance",
        title=_("Attendance"),
        category="operations",
        codename=CODENAME,
        description=_("Attendance outcomes by outcome, student, service or month."),
        run=attendance,
        filters=LESSON_FILTERS,
        group_by=("outcome", "month", "student", "service"),
    )
)


def cancellations(user: Any, params: Params) -> Result:
    from tutortrack.delivery.models import CancellationRecord

    qs = CancellationRecord.objects.filter(
        lesson_id__in=lesson_facts(user, params, primary=None).values("lesson_id")
    )
    kinds = dict(CancellationRecord.Kind.choices)
    who = {"client": _("Client"), "student": _("Student"), "tutor": _("Tutor"), "admin": _("Us")}
    field = {"who": "cancelled_by_type", "kind": "kind", "notice": None}[params.group_by]
    rows: list[dict[str, Any]] = []
    if field is None:
        bands = (
            (0, 24, _("Under 24 hours")),
            (24, 48, _("24\N{EN DASH}48 hours")),
            (48, 24 * 7, _("2\N{EN DASH}7 days")),
            (24 * 7, 10**9, _("Over a week")),
        )
        for low, high, label in bands:
            band = qs.filter(notice_minutes__gte=low * 60, notice_minutes__lt=high * 60)
            agg = band.aggregate(
                n=Count("pk"),
                charged=Count("pk", filter=Q(charge_percent__gt=0)),
                makeups=Count("pk", filter=Q(makeup_credit_issued=True)),
            )
            rows.append(
                {
                    "group": str(label),
                    "group_id": str(low),
                    "cancellations": agg["n"],
                    "charged": agg["charged"],
                    "makeups": agg["makeups"],
                }
            )
    else:
        data = (
            qs.values(field)
            .annotate(
                n=Count("pk"),
                charged=Count("pk", filter=Q(charge_percent__gt=0)),
                makeups=Count("pk", filter=Q(makeup_credit_issued=True)),
                overridden=Count("pk", filter=Q(overridden=True)),
            )
            .order_by("-n")
        )
        labels = kinds if field == "kind" else who
        for r in data:
            raw = r[field]
            rows.append(
                {
                    "group": str(labels.get(raw, raw)),
                    "group_id": raw,
                    "cancellations": r["n"],
                    "charged": r["charged"],
                    "makeups": r["makeups"],
                }
            )
    for row in rows:
        row["charged_rate"] = percent(row["charged"], row["cancellations"])
    return Result(
        columns=[
            Column(
                "group",
                {
                    "who": _("Cancelled by"),
                    "kind": _("Policy outcome"),
                    "notice": _("Notice given"),
                }[params.group_by],
            ),
            Column("cancellations", _("Cancellations"), "count"),
            Column("charged", _("Charged"), "count"),
            Column("makeups", _("Makeup credits"), "count"),
            Column("charged_rate", _("Charged %"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["cancellations", "charged"]},
    )


register(
    ReportDef(
        key="cancellations",
        title=_("Cancellation analysis"),
        category="operations",
        codename=CODENAME,
        description=_("Who cancelled, how much notice they gave and what the policy decided."),
        run=cancellations,
        filters=LESSON_FILTERS,
        group_by=("who", "kind", "notice"),
    )
)


# --- utilisation --------------------------------------------------------------------------------


def available_minutes(tutor_ids: list[Any], start: date, end: date) -> dict[str, int]:
    """Minutes of weekly availability per tutor in [start, end] (exceptions not deducted)."""
    from tutortrack.scheduling.models import AvailabilityTemplate

    templates = (
        AvailabilityTemplate.objects.filter(tutor_id__in=tutor_ids, effective_from__lte=end)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=start))
        .prefetch_related("windows")
    )
    out: dict[str, int] = defaultdict(int)
    for template in templates:
        first = max(start, template.effective_from)
        last = min(end, template.effective_to) if template.effective_to else end
        if last < first:
            continue
        per_weekday: dict[int, int] = defaultdict(int)
        for w in template.windows.all():
            minutes = (
                datetime.combine(first, w.end_time) - datetime.combine(first, w.start_time)
            ).seconds // 60
            per_weekday[w.weekday] += minutes
        day = first
        while day <= last:
            out[str(template.tutor_id)] += per_weekday.get(day.weekday(), 0)
            day += timedelta(days=1)
    return out


def tutor_utilisation(user: Any, params: Params) -> Result:
    qs = lesson_facts(user, params, primary=None).exclude(tutor_id__isnull=True)
    data = (
        qs.values("tutor_id")
        .annotate(
            booked=Sum("minutes", filter=Q(status__in=("planned", "completed", "missed"))),
            delivered=Sum("delivered_minutes"),
            lessons=Count("pk", filter=Q(status="completed")),
        )
        .order_by("tutor_id")
    )
    rows_by = {str(r["tutor_id"]): r for r in data}
    from tutortrack.people.models import TutorProfile

    tutors = scoped_by(
        user,
        TutorProfile.objects.filter(status__in=("active", "restricted")),
        CODENAME,
        branch="branches",
        own=Q(membership__user=user),
    )
    if params.tutor:
        tutors = tutors.filter(pk__in=params.tutor)
    if params.branch:
        tutors = tutors.filter(branches__in=params.branch)
    ids = {str(t) for t in tutors.values_list("pk", flat=True)} | set(rows_by)
    available = available_minutes(list(ids), params.period.start, params.period.end)
    names = dims.labels("tutor", ids)
    rows: list[dict[str, Any]] = []
    for tutor_id in ids:
        r = rows_by.get(tutor_id, {})
        booked = int(r.get("booked") or 0)
        rows.append(
            {
                "group": names.get(tutor_id, ""),
                "group_id": tutor_id,
                "lessons": int(r.get("lessons") or 0),
                "available": hours(available.get(tutor_id, 0)),
                "booked": hours(booked),
                "delivered": hours(r.get("delivered") or 0),
                "utilisation": percent(booked, available.get(tutor_id, 0)),
            }
        )
    rows.sort(key=lambda row: str(row["group"]))
    result = Result(
        columns=[
            Column("group", _("Tutor")),
            Column("lessons", _("Lessons delivered"), "count"),
            Column("available", _("Available hours"), "hours"),
            Column("booked", _("Booked hours"), "hours"),
            Column("delivered", _("Delivered hours"), "hours"),
            Column("utilisation", _("Utilisation %"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["utilisation"]},
    )
    total_available = sum(Decimal(row["available"]) for row in rows)
    total_booked = sum(Decimal(row["booked"]) for row in rows)
    result.totals = [
        {
            "lessons": sum(row["lessons"] for row in rows),
            "available": str(total_available),
            "booked": str(total_booked),
            "delivered": str(sum(Decimal(row["delivered"]) for row in rows)),
            "utilisation": percent(total_booked, total_available),
        }
    ]
    return result


register(
    ReportDef(
        key="tutor_utilisation",
        title=_("Tutor hours and utilisation"),
        category="operations",
        codename=CODENAME,
        description=_("Hours booked and delivered against each tutor's weekly availability."),
        run=tutor_utilisation,
        filters=("branch", "tutor"),
        ordering="-utilisation",
    )
)


# --- lesson report SLA --------------------------------------------------------------------------


def report_sla(user: Any, params: Params) -> Result:
    from tutortrack.delivery.models import LessonReport

    qs = scoped_by(
        user,
        LessonReport.objects.all(),
        CODENAME,
        branch="lesson__branch_id",
        own=Q(tutor_id__in=my_tutor_ids(user)),
    )
    qs = in_period(qs, params, "due_at__date")
    qs = filter_facts(
        qs,
        params,
        {"branch": "lesson__branch_id", "tutor": "tutor_id", "service": "lesson__service_id"},
    )
    written = Q(submitted_at__isnull=False)
    data = (
        qs.values("tutor_id")
        .annotate(
            due=Count("pk"),
            on_time=Count("pk", filter=written & Q(submitted_at__lte=F("due_at"))),
            late=Count("pk", filter=written & Q(submitted_at__gt=F("due_at"))),
            outstanding=Count("pk", filter=Q(submitted_at__isnull=True, due_at__lt=now())),
        )
        .order_by("tutor_id")
    )
    names = dims.labels("tutor", (r["tutor_id"] for r in data))
    rows = [
        {
            "group": names.get(str(r["tutor_id"]), ""),
            "group_id": str(r["tutor_id"]),
            "due": r["due"],
            "on_time": r["on_time"],
            "late": r["late"],
            "outstanding": r["outstanding"],
            "on_time_rate": percent(r["on_time"], r["due"]),
        }
        for r in data
    ]
    result = Result(
        columns=[
            Column("group", _("Tutor")),
            Column("due", _("Reports due"), "count"),
            Column("on_time", _("On time"), "count"),
            Column("late", _("Late"), "count"),
            Column("outstanding", _("Overdue"), "count"),
            Column("on_time_rate", _("On time %"), "percent"),
        ],
        rows=rows,
        chart={
            "type": "bar",
            "x": "group",
            "y": ["on_time", "late", "outstanding"],
            "stacked": True,
        },
    )
    return result


register(
    ReportDef(
        key="report_sla",
        title=_("Lesson report deadlines"),
        category="operations",
        codename=CODENAME,
        description=_("Whether each tutor writes lesson reports on time."),
        run=report_sla,
        filters=("branch", "tutor", "service"),
        ordering="on_time_rate",
    )
)


# --- unconfirmed lessons and locations ----------------------------------------------------------


def unconfirmed_lessons(user: Any, params: Params) -> Result:
    qs = scoped(user, FactLesson.objects.filter(status="planned", end__lt=now()), CODENAME)
    qs = filter_facts(qs, params, LESSON_FIELDS)
    by_lesson: dict[str, dict[str, Any]] = {}
    tutor_names = dims.labels("tutor", qs.values_list("tutor_id", flat=True))
    for fact in qs.order_by("start")[:5000]:
        row = by_lesson.setdefault(
            str(fact.lesson_id),
            {
                "id": str(fact.lesson_id),
                "date": fact.date.isoformat(),
                "start": fact.start.isoformat(),
                "tutors": [],
                "flagged": bool(fact.unconfirmed),
                "service_id": str(fact.service_id or ""),
            },
        )
        if fact.tutor_id:
            row["tutors"].append(tutor_names.get(str(fact.tutor_id), ""))
    services = dims.labels("service", (r["service_id"] for r in by_lesson.values()))
    rows = []
    for row in by_lesson.values():
        rows.append(
            {
                "id": row["id"],
                "date": row["date"],
                "start": row["start"],
                "service": services.get(row["service_id"], ""),
                "tutors": ", ".join(row["tutors"]),
                "flagged": str(_("Yes")) if row["flagged"] else "",
            }
        )
    return Result(
        columns=[
            Column("date", _("Date"), "date"),
            Column("service", _("Service")),
            Column("tutors", _("Tutors")),
            Column("flagged", _("Flagged as unconfirmed")),
        ],
        rows=rows,
    )


register(
    ReportDef(
        key="unconfirmed_lessons",
        title=_("Unconfirmed lessons"),
        category="operations",
        codename=CODENAME,
        description=_("Lessons that have ended but nobody has marked as delivered or cancelled."),
        run=unconfirmed_lessons,
        filters=LESSON_FILTERS,
        period=False,
        ordering="date",
    )
)


def location_utilisation(user: Any, params: Params) -> Result:
    qs = lesson_facts(user, params).exclude(location_id__isnull=True).exclude(status="cancelled")
    rows = grouped(
        qs,
        "location",
        {"lessons": Count("pk"), "minutes": Sum("minutes"), "attendees": Sum("attendees")},
        fields=LESSON_FIELDS,
        by_currency=False,
    )
    for row in rows:
        row["hours"] = hours(row.pop("minutes"))
    return Result(
        columns=[
            Column("group", _("Location")),
            Column("lessons", _("Lessons"), "count"),
            Column("hours", _("Booked hours"), "hours"),
            Column("attendees", _("Attendee places"), "count"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["hours"]},
    )


register(
    ReportDef(
        key="location_utilisation",
        title=_("Room and location use"),
        category="operations",
        codename=CODENAME,
        description=_("Booked hours at each location (rooms arrive with E06 phase 2)."),
        run=location_utilisation,
        filters=("branch", "service", "subject"),
        ordering="-hours",
    )
)
