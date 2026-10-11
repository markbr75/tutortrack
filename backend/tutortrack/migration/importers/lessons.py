"""Lessons, historic and future, with series detection (E28-T03).

* Lessons before the cutover date (or already completed/cancelled) are history: they are
  recorded as delivered without creating charges or pay (the opening balance carries the
  money), through ``scheduling.services.import_lesson``.
* Future planned lessons that repeat every week (or fortnight) at the same time with the
  same people become one lesson series (``create_series``); the rest are single lessons.
* Imported lessons never notify clients or tutors.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils.translation import gettext as _

from . import refs
from .base import Context, FieldSpec, Importer, Outcome, Plan, RowError, register
from .base import label as _l
from .common import money_or_none, not_found, ref
from .jobs import REFERENCE_FIELDS, TUTOR_FIELDS, resolve_students

LESSON_STATUSES = ("planned", "completed", "cancelled", "missed")
MIN_SERIES = 3


def _local(day: date, at: time, tz: str) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(tz))


@register
class LessonImporter(Importer):
    key = "lessons"
    label = _l("Lessons")
    description = _l(
        "Past lessons (kept as history, no charges) and future lessons; weekly patterns "
        "become series."
    )
    permissions = ("scheduling.lesson.create",)
    target_type = "scheduling.lesson"
    upsert_keys = ("external_id", "none")
    default_upsert = "external_id"
    fields = [
        FieldSpec(
            "external_id",
            _l("Lesson ID"),
            synonyms=("lesson id", "appointment id", "event id", "id"),
        ),
        FieldSpec(
            "date",
            _l("Date"),
            "date",
            required=True,
            synonyms=("date", "lesson date", "start date", "day"),
        ),
        FieldSpec(
            "start_time",
            _l("Start time"),
            "time",
            required=True,
            synonyms=("start time", "start", "time", "from"),
        ),
        FieldSpec("end_time", _l("End time"), "time", synonyms=("end time", "end", "finish", "to")),
        FieldSpec(
            "duration_minutes",
            _l("Duration (minutes)"),
            "int",
            synonyms=("duration", "length", "minutes"),
        ),
        FieldSpec("timezone", _l("Time zone"), synonyms=("timezone", "time zone")),
        FieldSpec("job_external_id", _l("Job ID"), synonyms=("job id", "service id")),
        FieldSpec("job_reference", _l("Job reference"), synonyms=("job reference", "job ref")),
        FieldSpec("service", _l("Service"), synonyms=("service", "lesson type", "subject")),
        FieldSpec("service_external_id", _l("Service ID"), synonyms=("service id",)),
        *REFERENCE_FIELDS,
        FieldSpec(
            "student_names",
            _l("Students (names, separated by ;)"),
            "list",
            synonyms=("students", "student", "attendees", "student names", "recipients"),
        ),
        FieldSpec(
            "student_external_ids",
            _l("Student IDs"),
            "list",
            synonyms=("student ids", "student id"),
        ),
        *TUTOR_FIELDS,
        FieldSpec(
            "status",
            _l("Status"),
            "choice",
            choices=LESSON_STATUSES,
            synonyms=("status", "lesson status", "attendance"),
        ),
        FieldSpec(
            "charge_rate", _l("Charge rate"), "decimal", synonyms=("charge rate", "price", "fee")
        ),
        FieldSpec(
            "pay_rate", _l("Pay rate"), "decimal", synonyms=("pay rate", "wage", "tutor pay")
        ),
        FieldSpec("online", _l("Online"), "bool", synonyms=("online",)),
        FieldSpec("notes", _l("Notes"), synonyms=("notes", "description", "comments")),
    ]
    example = {
        "date": "2026-11-02",
        "start_time": "16:00",
        "end_time": "17:00",
        "job_external_id": "J-12",
        "status": "planned",
    }

    # --- shared resolution ---

    def _tz(self, values: dict[str, Any], ctx: Context, job: Any) -> str:
        tz = values.get("timezone") or (job.branch.timezone if job is not None else ctx.timezone)
        try:
            ZoneInfo(str(tz))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise RowError(_("Unknown time zone."), "timezone") from exc
        return str(tz)

    def _minutes(self, values: dict[str, Any], service: Any) -> int:
        if values.get("end_time") and values.get("start_time"):
            start = datetime.combine(date.min, values["start_time"])
            end = datetime.combine(date.min, values["end_time"])
            if end <= start:
                end += timedelta(days=1)
            return int((end - start).total_seconds() // 60)
        if values.get("duration_minutes"):
            return int(values["duration_minutes"])
        return int(service.default_duration_minutes) if service is not None else 60

    def _people(self, values: dict[str, Any], ctx: Context) -> dict[str, Any]:
        job = refs.find_job(ctx, values)
        if (values.get("job_external_id") or values.get("job_reference")) and job is None:
            raise RowError(not_found(_("Job")), "job_external_id")
        named_service = values.get("service") or values.get("service_external_id")
        service = refs.find_service(ctx, values) if named_service else None
        if named_service and service is None:
            raise RowError(not_found(_("Service")), "service")
        service = service or (job.service if job is not None else None)
        if service is None:
            raise RowError(_("Give a job or a service."), "service")
        client = refs.find_client(ctx, values) or (job.client if job is not None else None)
        named = values.get("student_names") or values.get("student_external_ids")
        students = resolve_students(ctx, values, client) if (named or job is None) else None
        tutor = (
            refs.find_tutor(ctx, values) if any(values.get(f.key) for f in TUTOR_FIELDS) else None
        )
        if tutor is None and any(values.get(f.key) for f in TUTOR_FIELDS):
            raise RowError(not_found(_("Tutor")), "tutor_email")
        return {"job": job, "service": service, "students": students, "tutor": tutor}

    def _historic(self, values: dict[str, Any], ctx: Context) -> bool:
        status = values.get("status") or "planned"
        return status != "planned" or values["date"] < ctx.cutover

    # --- series detection ---

    def prepare(self, rows: list[Any], ctx: Context) -> None:
        """``rows``: (row_number, values) of rows without errors. Marks weekly runs."""
        groups: dict[tuple[Any, ...], list[tuple[date, int]]] = defaultdict(list)
        for number, values in rows:
            if self._historic(values, ctx) or (
                values.get("external_id")
                and ctx.upsert_key != "none"
                and refs.ref_for(ctx, "scheduling.lesson", values["external_id"])
            ):
                continue
            key = (
                values.get("job_external_id") or values.get("job_reference") or "",
                str(values.get("client_external_id") or values.get("client_email") or ""),
                values.get("service") or values.get("service_external_id") or "",
                tuple(
                    sorted(values.get("student_names") or values.get("student_external_ids") or [])
                ),
                str(
                    values.get("tutor_external_id")
                    or values.get("tutor_email")
                    or values.get("tutor_name")
                    or ""
                ),
                values["date"].weekday(),
                values["start_time"],
                self._minutes(values, None),
                values.get("timezone") or "",
                values.get("charge_rate"),
                values.get("pay_rate"),
            )
            groups[key].append((values["date"], number))
        series: dict[int, dict[str, Any]] = {}
        for items in groups.values():
            items.sort()
            run: list[tuple[date, int]] = []
            step = 0
            for item in [*items, None]:
                if item is not None and run:
                    gap = (item[0] - run[-1][0]).days
                    if (len(run) == 1 and gap in (7, 14)) or (len(run) > 1 and gap == step):
                        step = gap
                        run.append(item)
                        continue
                if len(run) >= int(ctx.options.get("series_min") or MIN_SERIES):
                    head = run[0][1]
                    series[head] = {
                        "interval": step // 7,
                        "start": run[0][0].isoformat(),
                        "until": run[-1][0].isoformat(),
                        "rows": [n for _d, n in run],
                    }
                    for _d, number in run[1:]:
                        series[number] = {"head": head}
                run, step = ([item] if item is not None else []), 0
        ctx.cache["series"] = series

    def check(self, values: dict[str, Any], ctx: Context) -> Plan:
        if values.get("external_id") and ctx.claim("lesson", values["external_id"]):
            ctx.error("external_id", _("This lesson id appears earlier in the file."))
        if values.get("external_id") and ctx.upsert_key != "none":
            target = refs.ref_for(ctx, "scheduling.lesson", values["external_id"])
            if target:
                ctx.warn("external_id", _("Already imported; skipped."))
                return Plan(action="skip", target_type="scheduling.lesson", target_id=target)
        try:
            found = self._people(values, ctx)
            self._tz(values, ctx, found["job"])
        except RowError as exc:
            ctx.error(exc.field, str(exc))
            return Plan()
        minutes = self._minutes(values, found["service"])
        if not 5 <= minutes <= 720:
            ctx.error("end_time", _("Lessons last between 5 minutes and 12 hours."))
        marker = ctx.cache.get("series", {}).get(ctx.row_number)
        if marker and "head" in marker:
            ctx.warn(
                "date", _("Part of the weekly series in row %(row)s.") % {"row": marker["head"]}
            )
            return Plan(action="skip", extra={"_series_of": marker["head"]})
        if marker:
            return Plan(
                effects=[("scheduling.lessonseries", "create")],
                extra={"_series": marker},
            )
        return Plan(effects=[("scheduling.lesson", "create")])

    def apply(self, values: dict[str, Any], ctx: Context) -> Outcome:
        from tutortrack.scheduling import services as scheduling

        if values.get("_series_of"):
            return Outcome(action="skip")
        found = self._people(values, ctx)
        job, service, tutor = found["job"], found["service"], found["tutor"]
        tz = self._tz(values, ctx, job)
        currency = job.currency if job is not None else service.currency
        attendees = None
        if found["students"] is not None:
            attendees = [
                {
                    "student": s,
                    "charge_rate_override": money_or_none(values.get("charge_rate"), currency),
                }
                for s in found["students"]
            ]
        elif values.get("charge_rate") is not None and job is not None:
            attendees = [
                {
                    "student": link.student,
                    "charge_rate_override": money_or_none(values["charge_rate"], currency),
                }
                for link in job.students.filter(active_to__isnull=True).select_related("student")
            ]
        tutors = None
        if tutor is not None:
            tutors = [
                {
                    "tutor": tutor,
                    "pay_rate_override": money_or_none(values.get("pay_rate"), currency),
                }
            ]
        minutes = self._minutes(values, service)
        marker = values.get("_series")
        if marker:
            result = scheduling.create_series(
                rrule=f"FREQ=WEEKLY;INTERVAL={marker['interval']}",
                start_date=date.fromisoformat(marker["start"]),
                start_time=values["start_time"],
                duration_minutes=minutes,
                service=service,
                job=job,
                timezone=tz,
                attendees=attendees,
                tutors=tutors,
                until=date.fromisoformat(marker["until"]),
                skip_holidays=False,
                online=bool(values.get("online")),
                notes_for_tutor=values.get("notes") or "",
                conflict_mode="create",
                notify=False,
            )
            series = result.series
            out = Outcome(
                action="create", target_type="scheduling.lessonseries", target_id=str(series.pk)
            )
            out.created.append(ref(series))
            if result.skipped:
                out.warnings.append(
                    _("%(n)s occurrences were skipped.") % {"n": len(result.skipped)}
                )
            return out
        start = _local(values["date"], values["start_time"], tz)
        end = start + timedelta(minutes=minutes)
        historic = self._historic(values, ctx)
        lesson = scheduling.import_lesson(
            start=start,
            end=end,
            service=service,
            job=job,
            timezone=tz,
            attendees=attendees,
            tutors=tutors,
            status=values.get("status") or ("completed" if historic else "planned"),
            historic=historic,
            online=bool(values.get("online")),
            notes_internal=values.get("notes") or "",
        )
        out = Outcome(action="create", target_type="scheduling.lesson", target_id=str(lesson.pk))
        out.created.append(ref(lesson))
        if values.get("external_id"):
            out.created.append(
                refs.remember(ctx, "scheduling.lesson", values["external_id"], lesson)
            )
        return out
