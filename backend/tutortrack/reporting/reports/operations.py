"""Operations reports (E26-T05): lessons, attendance, cancellations, utilisation (net of
time off), report SLA, unconfirmed lessons, location and room use. Tutors with
``reporting.operations.view:own`` see their own lessons."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.utils.translation import gettext_lazy as _

from tutortrack.core.time import now

from .. import dims, periods
from ..models import FactLesson
from .base import (
    Column,
    Params,
    ReportDef,
    Result,
    filter_custom_field,
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
    split_custom_field,
)

CODENAME = "reporting.operations.view"
LESSON_FIELDS = {
    "branch": "branch_id",
    "tutor": "tutor_id",
    "service": "service_id",
    "subject": "subject_id",
    "job": "job_id",
    "location": "location_id",
    "lesson": "lesson_id",  # students' custom fields reach lessons through attendees
}
LESSON_FILTERS = ("branch", "tutor", "service", "subject")
# Gap G5: lesson reports filter on students' and tutors' custom fields too.
LESSON_CF_FILTERS = (*LESSON_FILTERS, "custom_field")
LESSON_CF_ENTITIES = ("student", "tutor")
STATUS_LABELS = {
    "planned": _("Planned"),
    "completed": _("Completed"),
    "cancelled": _("Cancelled"),
    "missed": _("Missed"),
}


def _tutor_custom_field(params: Params) -> bool:
    return bool(params.custom_field) and split_custom_field(params.custom_field)[0] == "tutor"


def lesson_facts(user: Any, params: Params, *, primary: bool | None = True) -> Any:
    qs = scoped(user, FactLesson.objects.all(), CODENAME)
    # Filtering on tutors uses every tutor's row, not only the lesson's primary one.
    if primary is not None and not params.tutor and not _tutor_custom_field(params):
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
        filters=LESSON_CF_FILTERS,
        custom_fields=LESSON_CF_ENTITIES,
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
        filters=LESSON_CF_FILTERS,
        custom_fields=LESSON_CF_ENTITIES,
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
        filters=LESSON_CF_FILTERS,
        custom_fields=LESSON_CF_ENTITIES,
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


# Gap G5 (FR-26-2 "utilisation vs availability"): availability net of time off.

Span = tuple[datetime, datetime]


def _merge(spans: Iterable[Span]) -> list[Span]:
    out: list[Span] = []
    for start, end in sorted(s for s in spans if s[1] > s[0]):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _length(spans: Iterable[Span]) -> int:
    return int(sum((end - start).total_seconds() for start, end in spans) // 60)


def _intersect(a: list[Span], b: list[Span]) -> list[Span]:
    """Overlap of two merged, sorted span lists."""
    out: list[Span] = []
    i = j = 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if start < end:
            out.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _subtract(a: list[Span], b: list[Span]) -> list[Span]:
    """``a`` without ``b`` (both merged and sorted)."""
    out: list[Span] = []
    for start, end in a:
        cursor = start
        for b_start, b_end in b:
            if b_end <= cursor or b_start >= end:
                continue
            if b_start > cursor:
                out.append((cursor, b_start))
            cursor = max(cursor, b_end)
        if cursor < end:
            out.append((cursor, end))
    return out


def net_availability(
    windows: Iterable[Span], time_off: Iterable[Span], extra: Iterable[Span]
) -> dict[str, int]:
    """Minutes of weekly availability (``weekly``), approved time off inside it (``off``),
    approved extra availability outside it and outside time off (``extra``), and what is
    left to book (``available`` = weekly - off + extra)."""
    w, o, e = _merge(windows), _merge(time_off), _merge(extra)
    weekly = _length(w)
    off = _length(_intersect(w, o))
    added = _length(_subtract(_subtract(e, w), o))
    return {"weekly": weekly, "off": off, "extra": added, "available": weekly - off + added}


def availability(tutor_ids: list[Any], start: date, end: date) -> dict[str, dict[str, int]]:
    """Per tutor, ``net_availability`` over the organisation-local days [start, end]: weekly
    windows in each template's timezone, less approved time off, plus approved extra
    availability (FR-08-5 exceptions)."""
    from tutortrack.scheduling.models import AvailabilityException, AvailabilityTemplate

    org_zone = ZoneInfo(periods.org_timezone())
    lower = datetime.combine(start, time(0), tzinfo=org_zone)
    upper = datetime.combine(end + timedelta(days=1), time(0), tzinfo=org_zone)
    windows: dict[str, list[Span]] = defaultdict(list)
    templates = (
        AvailabilityTemplate.objects.filter(tutor_id__in=tutor_ids, effective_from__lte=end)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=start))
        .prefetch_related("windows")
    )
    for template in templates:
        zone = ZoneInfo(template.timezone) if template.timezone else org_zone
        first = max(start, template.effective_from)
        last = min(end, template.effective_to) if template.effective_to else end
        by_day: dict[int, list[Any]] = defaultdict(list)
        for w in template.windows.all():
            by_day[w.weekday].append(w)
        day = first
        while day <= last:
            for w in by_day.get(day.weekday(), []):
                windows[str(template.tutor_id)].append(
                    (
                        max(datetime.combine(day, w.start_time, tzinfo=zone), lower),
                        min(datetime.combine(day, w.end_time, tzinfo=zone), upper),
                    )
                )
            day += timedelta(days=1)
    off: dict[str, list[Span]] = defaultdict(list)
    extra: dict[str, list[Span]] = defaultdict(list)
    exceptions = AvailabilityException.objects.filter(
        tutor_id__in=tutor_ids,
        status=AvailabilityException.Status.APPROVED,
        start__lt=upper,
        end__gt=lower,
    )
    for x in exceptions:
        target = off if x.type == AvailabilityException.Type.OFF else extra
        target[str(x.tutor_id)].append((max(x.start, lower), min(x.end, upper)))
    return {
        str(t): net_availability(windows[str(t)], off[str(t)], extra[str(t)]) for t in tutor_ids
    }


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
    if params.custom_field:
        tutors = filter_custom_field(tutors, params, {"tutor": "pk"})
    ids = {str(t) for t in tutors.values_list("pk", flat=True)} | set(rows_by)
    figures = availability(list(ids), params.period.start, params.period.end)
    names = dims.labels("tutor", ids)
    rows: list[dict[str, Any]] = []
    for tutor_id in ids:
        r = rows_by.get(tutor_id, {})
        booked = int(r.get("booked") or 0)
        f = figures.get(tutor_id) or {"weekly": 0, "off": 0, "extra": 0, "available": 0}
        rows.append(
            {
                "group": names.get(tutor_id, ""),
                "group_id": tutor_id,
                "lessons": int(r.get("lessons") or 0),
                "weekly": hours(f["weekly"]),
                "time_off": hours(f["off"]),
                "extra": hours(f["extra"]),
                "available": hours(f["available"]),
                "booked": hours(booked),
                "delivered": hours(r.get("delivered") or 0),
                "utilisation": percent(booked, f["available"]),
                "_available_minutes": f["available"],
                "_booked_minutes": booked,
            }
        )
    rows.sort(key=lambda row: str(row["group"]))
    result = Result(
        columns=[
            Column("group", _("Tutor")),
            Column("lessons", _("Lessons delivered"), "count"),
            Column("weekly", _("Weekly availability hours"), "hours"),
            Column("time_off", _("Time off hours"), "hours"),
            Column("extra", _("Extra availability hours"), "hours"),
            Column("available", _("Available hours (net)"), "hours"),
            Column("booked", _("Booked hours"), "hours"),
            Column("delivered", _("Delivered hours"), "hours"),
            Column("utilisation", _("Utilisation %"), "percent"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["utilisation"]},
    )
    total_available = sum(row.pop("_available_minutes") for row in rows)
    total_booked = sum(row.pop("_booked_minutes") for row in rows)
    result.totals = [
        {
            "lessons": sum(row["lessons"] for row in rows),
            **{
                key: str(sum(Decimal(row[key]) for row in rows))
                for key in ("weekly", "time_off", "extra", "available", "delivered")
            },
            "booked": hours(total_booked),
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
        description=_(
            "Hours booked and delivered against each tutor's availability, net of approved "
            "time off and plus extra availability."
        ),
        run=tutor_utilisation,
        filters=("branch", "tutor", "custom_field"),
        custom_fields=("tutor",),
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
        filters=LESSON_CF_FILTERS,
        custom_fields=LESSON_CF_ENTITIES,
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
        title=_("Location use"),
        category="operations",
        codename=CODENAME,
        description=_("Booked hours at each location (see Room utilisation for each room)."),
        run=location_utilisation,
        filters=("branch", "service", "subject"),
        ordering="-hours",
    )
)


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def open_minutes(opening_hours: dict[str, Any], start: date, end: date) -> int:
    """Minutes a location is open over [start, end] from its weekly opening hours
    (``{"mon": [{"start": "09:00", "end": "17:00"}], ...}``, the business-hours shape)."""

    def minutes(value: str) -> int:
        hh, mm = str(value).split(":")[:2]
        return int(hh) * 60 + int(mm)

    per_weekday = {}
    for index, day in enumerate(DAYS):
        total = 0
        for slot in opening_hours.get(day) or []:
            try:
                total += max(0, minutes(slot["end"]) - minutes(slot["start"]))
            except (KeyError, TypeError, ValueError):
                continue
        per_weekday[index] = total
    out, day_ = 0, start
    while day_ <= end:
        out += per_weekday[day_.weekday()]
        day_ += timedelta(days=1)
    return out


def room_utilisation(user: Any, params: Params) -> Result:
    """Per room (E06-T10): lessons and hours booked (not cancelled) against the hours its
    location is open (the location's opening hours, else the business hours), and how full
    the room was against its capacity."""
    from tutortrack.catalogue.models import Room
    from tutortrack.scheduling.models import Lesson
    from tutortrack.tenancy.settings_service import get_setting

    facts = lesson_facts(user, params).exclude(status="cancelled")
    room = Subquery(Lesson.objects.filter(pk=OuterRef("lesson_id")).values("room_id")[:1])
    data = {
        str(r["_room"]): r
        for r in facts.annotate(_room=room)
        .exclude(_room__isnull=True)
        .order_by()
        .values("_room")
        .annotate(lessons=Count("pk"), minutes=Sum("minutes"), attendees=Sum("attendees"))
    }
    listed = scoped_by(
        user,
        Room.objects.filter(active=True),
        CODENAME,
        branch="location__branch_id",
        own=Q(pk__in=[]),  # tutors only see the rooms they taught in
    )
    if params.branch:
        listed = listed.filter(location__branch_id__in=params.branch)
    ids = {str(pk) for pk in listed.values_list("pk", flat=True)} | set(data)
    business_hours = get_setting("general.business_hours") or {}
    rows: list[dict[str, Any]] = []
    totals = {"lessons": 0, "minutes": 0, "open": 0, "attendees": 0}
    rooms = Room.objects.filter(pk__in=ids).select_related("location")
    for r in rooms.order_by("location__name", "name"):
        booked = data.get(str(r.pk), {})
        lessons = int(booked.get("lessons") or 0)
        minutes = int(booked.get("minutes") or 0)
        attendees = int(booked.get("attendees") or 0)
        open_ = open_minutes(
            r.location.opening_hours or business_hours, params.period.start, params.period.end
        )
        places = lessons * r.capacity if r.capacity else 0
        rows.append(
            {
                "group": r.name,
                "group_id": str(r.pk),
                "location": r.location.name,
                "capacity": r.capacity if r.capacity is not None else "",
                "lessons": lessons,
                "hours": hours(minutes),
                "open_hours": hours(open_),
                "utilisation": percent(minutes, open_),
                "attendees": attendees,
                "fill": percent(attendees, places) if places else "",
            }
        )
        totals["lessons"] += lessons
        totals["minutes"] += minutes
        totals["open"] += open_
        totals["attendees"] += attendees
    return Result(
        columns=[
            Column("group", _("Room")),
            Column("location", _("Location")),
            Column("capacity", _("Capacity")),
            Column("lessons", _("Lessons"), "count"),
            Column("hours", _("Booked hours"), "hours"),
            Column("open_hours", _("Open hours"), "hours"),
            Column("utilisation", _("Utilisation %"), "percent"),
            Column("attendees", _("Attendee places"), "count"),
            Column("fill", _("Seats filled %"), "percent"),
        ],
        rows=rows,
        totals=[
            {
                "lessons": totals["lessons"],
                "hours": hours(totals["minutes"]),
                "open_hours": hours(totals["open"]),
                "utilisation": percent(totals["minutes"], totals["open"]),
                "attendees": totals["attendees"],
            }
        ],
        chart={"type": "bar", "x": "group", "y": ["utilisation"]},
    )


register(
    ReportDef(
        key="room_utilisation",
        title=_("Room utilisation"),
        category="operations",
        codename=CODENAME,
        description=_(
            "Hours booked in each room against the hours its location is open, and seats filled."
        ),
        run=room_utilisation,
        filters=("branch", "service", "subject"),
        ordering="-utilisation",
    )
)


# --- client feedback (E09-T09) ------------------------------------------------------------------


def _stars(value: Any) -> str:
    from decimal import ROUND_HALF_UP

    if value is None:
        return ""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def lesson_feedback(user: Any, params: Params) -> Result:
    """Families' post-lesson ratings per tutor: asked, answered, average and low scores."""
    from django.db.models import Avg

    from tutortrack.delivery.models import LessonFeedback
    from tutortrack.tenancy.settings_service import get_setting

    qs = scoped_by(
        user,
        LessonFeedback.objects.exclude(status=LessonFeedback.Status.SKIPPED),
        CODENAME,
        branch="branch_id",
        own=Q(tutor_id__in=my_tutor_ids(user)),
    )
    qs = filter_facts(
        in_period(qs, params, "lesson_date"),
        params,
        {"branch": "branch_id", "tutor": "tutor_id", "client": "client_id"},
    )
    low = int(get_setting("delivery.feedback_alert_at_or_below"))
    answered = Q(status=LessonFeedback.Status.ANSWERED)
    data = (
        qs.values("tutor_id")
        .annotate(
            asked=Count("pk"),
            answered=Count("pk", filter=answered),
            average=Avg("rating", filter=answered),
            low=Count("pk", filter=answered & Q(rating__lte=low)),
        )
        .order_by("tutor_id")
    )
    names = dims.labels("tutor", (r["tutor_id"] for r in data))
    rows = [
        {
            "group": names.get(str(r["tutor_id"]), "") if r["tutor_id"] else str(_("(none)")),
            "group_id": str(r["tutor_id"] or ""),
            "asked": r["asked"],
            "answered": r["answered"],
            "answer_rate": percent(r["answered"], r["asked"]),
            "average": _stars(r["average"]),
            "low": r["low"],
        }
        for r in data
    ]
    overall = qs.aggregate(
        asked=Count("pk"),
        answered=Count("pk", filter=answered),
        average=Avg("rating", filter=answered),
        low=Count("pk", filter=answered & Q(rating__lte=low)),
    )
    totals = [
        {
            "asked": overall["asked"],
            "answered": overall["answered"],
            "answer_rate": percent(overall["answered"], overall["asked"]),
            "average": _stars(overall["average"]),  # the overall average, not a sum
            "low": overall["low"],
        }
    ]
    return Result(
        totals=totals,
        columns=[
            Column("group", _("Tutor")),
            Column("asked", _("Asked"), "count"),
            Column("answered", _("Answered"), "count"),
            Column("answer_rate", _("Answer rate %"), "percent"),
            Column("average", _("Average stars"), "number"),
            Column("low", _("Low ratings"), "count"),
        ],
        rows=rows,
        chart={"type": "bar", "x": "group", "y": ["average"]},
    )


register(
    ReportDef(
        key="lesson_feedback",
        title=_("Lesson feedback"),
        category="operations",
        codename=CODENAME,
        description=_("Families' star ratings after lessons, per tutor (E09 surveys)."),
        run=lesson_feedback,
        filters=("branch", "tutor", "client"),
        ordering="-average",
    )
)
