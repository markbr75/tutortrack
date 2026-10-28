"""Workflow reads for the editor (E33 T08): the records a preview can use, **Preview for a
family** (the timeline with real dates, the path each split takes and what each step would
send), **Coming up** (a scheduled or date start's next dates and how many records each would
pick) and where each run is.

Nothing here sends or changes anything. Previews answer "only if" and split questions as
the record is now; a run asks them again when it gets to each step.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from . import conditions, registry, services, timing
from .actions import RunContext
from .models import Automation, AutomationRun, AutomationRunStep

UPCOMING = 5
SCAN_DAYS = 92  # how far ahead "Coming up" looks for a date start's records
RECORDS = 20

# --- records ------------------------------------------------------------------------------------

# What the record picker searches, per record type (text fields on the model).
SEARCH: dict[str, tuple[str, ...]] = {
    "client": ("display_name",),
    "student": ("first_name", "last_name", "preferred_name"),
    "tutor": ("display_name", "first_name", "last_name", "email"),
    "lesson": ("title",),
    "lesson_report": ("lesson__title",),
    "enquiry": ("title",),
    "invoice": ("number", "client__display_name"),
    "job": ("reference", "name"),
    "tutor_application": ("first_name", "last_name", "email"),
    "compliance_record": ("tutor__display_name", "tutor__first_name", "tutor__last_name"),
    "package": ("name", "client__display_name"),
    "branch": ("name",),
    "payment_request": ("number", "description", "client__display_name"),
    "review_request": ("client__display_name",),
}


def record_label(subject_key: str, obj: Any) -> str:
    """A record as staff know it: the family's name, the invoice number, the lesson and when."""
    if subject_key == "lesson":
        local = obj.start.astimezone(ZoneInfo(obj.timezone or "UTC"))
        return f"{obj.title}, {local:%Y-%m-%d %H:%M}"
    if subject_key == "lesson_report":
        return str(obj.lesson.title)
    if subject_key == "compliance_record":
        return f"{obj.tutor} · {getattr(obj.requirement, 'name', obj.requirement)}"
    if subject_key == "invoice_run":
        return f"{obj.branch.name}: {obj.period_start:%Y-%m-%d} to {obj.period_end:%Y-%m-%d}"
    if subject_key == "payment_request":
        return str(obj.number or obj.description)
    if subject_key == "review_request":
        return f"{obj.client} ({obj.created_at:%Y-%m-%d})"
    return str(obj)


def find_records(subject_key: str, q: str = "") -> list[dict[str, str]]:
    """Up to 20 records of this type for the preview's picker, newest first."""
    subject = registry.subject(subject_key)
    if subject is None:
        return []
    model = subject.model_class()
    qs = model.objects.all()
    if hasattr(model, "archived_at"):
        qs = qs.filter(archived_at__isnull=True)
    q = q.strip()
    if q:
        match = Q(pk__in=[]) if not SEARCH.get(subject_key) else Q()
        for name in SEARCH.get(subject_key, ()):
            match |= Q(**{f"{name}__icontains": q})
        qs = qs.filter(match)
    return [
        {"id": str(obj.pk), "label": record_label(subject_key, obj)}
        for obj in qs.order_by("-created_at")[:RECORDS]
    ]


def labels_for(runs: list[AutomationRun]) -> dict[str, str]:
    """Each run's record as staff know it (one query per kind of record)."""
    by_kind: dict[str, set[str]] = {}
    for run in runs:
        if run.subject_id:
            by_kind.setdefault(run.subject_type, set()).add(run.subject_id)
    labels: dict[str, str] = {}
    for kind, ids in by_kind.items():
        subject = registry.subject(kind)
        if subject is None:
            continue
        for obj in subject.model_class().objects.filter(pk__in=list(ids)):
            labels[str(obj.pk)] = record_label(kind, obj)
    return labels


# --- where each run is ----------------------------------------------------------------------------


def with_position(qs: QuerySet[AutomationRun]) -> QuerySet[AutomationRun]:
    """Runs with where each one is: the wait it's in and when it ends, and how many steps it
    has done (the wake time is display only; Temporal holds the timer)."""
    waiting = AutomationRunStep.objects.filter(
        run=OuterRef("pk"), status=AutomationRunStep.Status.WAITING
    ).order_by("-created_at")
    done = ~Q(steps__status=AutomationRunStep.Status.WAITING)
    return qs.annotate(
        waiting_until=Subquery(waiting.values("resume_at")[:1]),
        waiting_step=Subquery(waiting.values("step_key")[:1]),
        steps_done=Count("steps", filter=done, distinct=True),
    )


# --- preview ------------------------------------------------------------------------------------


def _question_labels(condition: Any) -> list[str]:
    labels = conditions.predicates()
    if not isinstance(condition, dict):
        return []
    if condition.get("predicate"):
        return [labels.get(str(condition["predicate"]), str(condition["predicate"]))]
    return [label for c in condition.get("all") or [] for label in _question_labels(c)]


def _org_zone() -> ZoneInfo:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)


def _at(config: dict[str, Any]) -> time:
    hour, minute = (int(x) for x in str(config.get("time") or "08:00").split(":"))
    return time(hour, minute)


def schedule_slots(
    config: dict[str, Any], after: datetime, count: int = UPCOMING
) -> list[datetime]:
    """The next times a schedule start fires, in the organisation's time zone (as
    ``services.sync_schedule`` sets it up)."""
    zone = _org_zone()
    at = _at(config)
    frequency = config.get("frequency") or "daily"
    weekday = int(config.get("weekday") or 0) % 7
    day_of_month = min(max(int(config.get("day") or 1), 1), 28)
    day = after.astimezone(zone).date()
    out: list[datetime] = []
    for _i in range(400):
        fires = (
            frequency == "daily"
            or (frequency == "weekly" and day.weekday() == weekday)
            or (frequency == "monthly" and day.day == day_of_month)
        )
        moment = datetime.combine(day, at, tzinfo=zone)
        if fires and moment > after:
            out.append(moment)
            if len(out) == count:
                break
        day += timedelta(days=1)
    return out


def _day_of(value: Any, zone: ZoneInfo) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(zone).date()
    return value if isinstance(value, date) else None


def _this_year(day: date, year: int) -> date:
    try:
        return day.replace(year=year)
    except ValueError:  # 29 February
        return date(year, 2, 28)


def start_moments(automation: Automation, definition: dict[str, Any], obj: Any) -> list[datetime]:
    """When a run would start for this record: now for an event or by hand; the next time a
    schedule fires; for a date start, each of its days (or times) for the record's date."""
    current = now()
    kind = definition["trigger_type"]
    config = definition["trigger_config"] or {}
    if kind == Automation.Trigger.SCHEDULE:
        return schedule_slots(config, current, 1)
    if kind != Automation.Trigger.DATE:
        return [current]
    value = getattr(obj, str(config.get("field") or ""), None)
    if value is None:
        return []
    if "minutes" in config:
        return sorted(value + timedelta(minutes=int(m)) for m in config.get("minutes") or [])
    zone = _org_zone()
    day = _day_of(value, zone)
    if day is None:
        return []
    if config.get("anniversary"):  # this year's (or next year's) birthday
        today = current.astimezone(zone).date()
        day = _this_year(day, today.year)
        if day + timedelta(days=min(services._offsets(config))) < today:
            day = _this_year(day, today.year + 1)
    days = sorted({day + timedelta(days=d) for d in services._offsets(config)})
    return [datetime.combine(d, _at(config), tzinfo=zone) for d in days]


def _message(action_key: str) -> dict[str, str] | None:
    from tutortrack.comms import registry as comms

    from .catalogue import ACTION_MESSAGES

    key = ACTION_MESSAGES.get(action_key)
    if not key:
        return None
    try:
        return {"type": key, "label": _(comms.get(key).label)}
    except KeyError:
        return {"type": key, "label": key}


def _walk(
    steps: list[dict[str, Any]], ctx: RunContext, moment: datetime, calendar: Any,
    prefix: str = "", path: str = "",
) -> tuple[list[dict[str, Any]], datetime]:  # fmt: skip
    """The timeline from ``moment``: each step with when it would happen."""
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        key = f"{prefix}{index}"
        row: dict[str, Any] = {"key": key, "path": path, "type": step.get("type"), "ok": True,
                               "skipped": False, "message": None, "questions": []}  # fmt: skip
        kind = step.get("type")
        if kind == "wait":
            anchor = None
            if step.get("until"):
                anchor = services._anchor(conditions.resolve(ctx.context, str(step["until"])))
            ends = timing.resume_at(start=moment, step=step, calendar=calendar, anchor=anchor)
            row["description"] = services.describe_wait(step)
            if step.get("until") and anchor is None:
                row["note"] = _("The record has no date for this, so it carries straight on.")
            elif ends < moment:
                row["note"] = _("That time has passed, so it carries straight on.")
            moment = max(moment, ends)
        elif kind == "action":
            action = registry.action(str(step.get("action") or ""))
            row["message"] = _message(str(step.get("action") or ""))
            if step.get("only_if") and not conditions.evaluate(step["only_if"], ctx.context):
                row["skipped"] = True
                row["questions"] = _question_labels(step["only_if"])
                row["description"] = action.label if action else _("Unknown")
                row["note"] = _("Skipped: its “only if” isn't met.")
            else:
                try:
                    row["description"] = (
                        action.describe(ctx, step.get("config") or {}) if action else _("Unknown")
                    )
                except (BusinessRuleViolation, ValueError) as exc:
                    row["description"] = str(getattr(exc, "detail", exc))
                    row["ok"] = False
        elif kind == "branch":
            matched = conditions.evaluate(step.get("if"), ctx.context)
            row["questions"] = _question_labels(step.get("if"))
            row["answer"] = "yes" if matched else "no"
            row["description"] = _("Yes") if matched else _("No")
        row["at"] = moment
        rows.append(row)
        if kind == "branch":
            arm = "then" if row["answer"] == "yes" else "else"
            more, moment = _walk(step.get(arm) or [], ctx, moment, calendar, f"{key}.{arm}.",
                                 row["answer"])  # fmt: skip
            rows += more
    return rows, moment


def preview(
    automation: Automation, subject_id: str, draft: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Preview for a record (FR-33-3): the saved workflow, or the editor's unsaved ``draft``
    (start, conditions, stop when and steps), with real dates."""
    definition = {name: getattr(automation, name) for name in services.DEFINITION}
    definition.update({k: v for k, v in (draft or {}).items() if k in services.DEFINITION})
    subject_type = automation.subject_type
    if draft:
        subject_type, _key = services.validate_definition(
            trigger_type=definition["trigger_type"], trigger_config=definition["trigger_config"],
            conditions_=definition["conditions"], steps=definition["steps"],
            stop_when=definition["stop_when"],
        )  # fmt: skip
    subject = registry.subject(subject_type)
    try:
        obj = subject.load(subject_id) if subject is not None else None
    except (ValueError, ValidationError):  # not an id at all
        obj = None
    if subject is None or obj is None:
        raise services._invalid("subject_id", _("Record not found."))
    context = services.build_context(subject, obj)
    matched = conditions.evaluate(definition["conditions"], context)
    starts = start_moments(automation, definition, obj)
    current = now()
    start = next((s for s in starts if s >= current), starts[-1] if starts else None)
    ctx = RunContext(automation=automation, subject=subject, obj=obj, context=context,
                     key="preview", author=services._author(automation))  # fmt: skip
    steps: list[dict[str, Any]] = []
    if matched and start is not None:
        calendar = timing.calendar_for(obj, start.date())
        steps, _end = _walk(definition["steps"], ctx, start, calendar)
    stops = {t.event: t.label for t in registry.triggers()}
    return {
        "record": {"id": str(obj.pk), "label": record_label(subject.key, obj)},
        "matched": matched,
        "failed_checks": [] if matched else _question_labels(definition["conditions"]),
        "start": start,
        "starts": starts,
        "start_passed": start is not None and start < current,
        "stop_when": [_(stops.get(e, e)) for e in definition["stop_when"] or []],
        "steps": steps,
    }


# --- coming up ----------------------------------------------------------------------------------


def _near_upcoming(automation: Automation, current: datetime) -> list[dict[str, Any]]:
    """For a "near a date" start: the next sweep slots with records due and how many."""
    subject = registry.subject(automation.subject_type)
    if subject is None:
        return []
    config = automation.trigger_config or {}
    name = str(config["field"])
    every = timedelta(minutes=services.NEAR_EVERY_MINUTES)
    slots: dict[datetime, int] = {}
    for minutes in config.get("minutes") or []:
        offset = timedelta(minutes=int(minutes))
        values = (
            subject.model_class()
            .objects.filter(**{f"{name}__gt": current - offset})
            .order_by(name)
            .values_list(name, flat=True)[: services.FAN_OUT_LIMIT]
        )
        for value in values:
            moment = value + offset
            # The sweep that picks it: the next quarter hour from its moment.
            slot = datetime.fromtimestamp(
                -(-moment.timestamp() // every.total_seconds()) * every.total_seconds(),
                tz=moment.tzinfo,
            )
            slots[slot] = slots.get(slot, 0) + 1
    return [{"at": at, "count": slots[at]} for at in sorted(slots)[:UPCOMING]]


def upcoming(automation: Automation) -> dict[str, Any]:
    """Coming up (FR-33-3): a scheduled or date start's next 5 dates and how many records
    each would pick ("1 Nov, 06:00: 38 families"). Counts are before the start's "only if"
    checks, which are asked of each record on the day."""
    current = now()
    config = automation.trigger_config or {}
    kind = automation.trigger_type
    dates: list[dict[str, Any]] = []
    if kind == Automation.Trigger.SCHEDULE:
        for slot in schedule_slots(config, current):
            dates.append({"at": slot, "count": len(services.due_records(automation, slot.date()))})
    elif kind == Automation.Trigger.DATE and "minutes" in config:
        dates = _near_upcoming(automation, current)
    elif kind == Automation.Trigger.DATE:
        zone = _org_zone()
        at = _at(config)
        day = current.astimezone(zone).date()
        for _i in range(SCAN_DAYS):
            moment = datetime.combine(day, at, tzinfo=zone)
            if moment > current:
                found = len(services.due_records(automation, day))
                if found:
                    dates.append({"at": moment, "count": found})
                    if len(dates) == UPCOMING:
                        break
            day += timedelta(days=1)
    return {
        "kind": kind,
        "dates": dates,
        "before_checks": bool(automation.conditions),
        "looked_ahead_days": SCAN_DAYS if kind == Automation.Trigger.DATE else 0,
    }
