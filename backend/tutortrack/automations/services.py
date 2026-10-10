"""Automation writes and the engine's steps (E14).

* Definitions: validated against the registry; editing the trigger, conditions or steps
  makes a new ``AutomationVersion`` (runs keep the version they started on).
* Runs: ``prepare_run`` applies the guardrails (kill switch, per-record daily limit,
  per-organisation hourly limit, loop depth) and the conditions, then ``launch`` starts
  ``AutomationRunWorkflow``. The workflow calls ``execute_step`` / ``evaluate_branch`` /
  ``start_wait`` / ``finish``, which are idempotent per run and step.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import EventEnvelope, publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.time import now

from . import conditions, events, registry
from .actions import RunContext
from .models import Automation, AutomationRun, AutomationRunStep, AutomationVersion

logger = structlog.get_logger(__name__)

MAX_STEPS = 30
MAX_NESTING = 3
MAX_CAUSATION_DEPTH = 3
MAX_WAIT_DAYS = 365
FAN_OUT_LIMIT = 2000
DEFINITION = ("trigger_type", "trigger_config", "conditions", "steps")
FREQUENCIES = ("daily", "weekly", "monthly")


def _invalid(field: str, messages: list[str] | str) -> BusinessRuleViolation:
    items = [messages] if isinstance(messages, str) else messages
    return BusinessRuleViolation(items[0], extra={"errors": {field: items}})


def _setting(key: str) -> Any:
    from tutortrack.tenancy.settings_service import get_setting

    return get_setting(key)


# --- definitions (T01) --------------------------------------------------------------------------


def _subject_for(trigger_type: str, config: dict[str, Any]) -> tuple[str, str]:
    """(subject type, trigger key) for a trigger, or a validation error."""
    if trigger_type == Automation.Trigger.EVENT:
        trigger = registry.trigger(str(config.get("event") or ""))
        if trigger is None:
            raise _invalid("trigger_config", _("Choose an event automations can react to."))
        return trigger.subject, trigger.event
    subject = registry.subject(str(config.get("subject") or ""))
    if subject is None:
        raise _invalid("trigger_config", _("Choose the kind of record."))
    if trigger_type == Automation.Trigger.SCHEDULE:
        if config.get("frequency") not in FREQUENCIES:
            raise _invalid("trigger_config", _("Run daily, weekly or monthly."))
        _cron(config)
    elif trigger_type == Automation.Trigger.DATE:
        if config.get("field") not in subject.date_fields:
            raise _invalid("trigger_config", _("Choose a date on the record."))
        try:
            int(config.get("offset_days") or 0)
        except (TypeError, ValueError) as exc:
            raise _invalid("trigger_config", _("Days before or after is a number.")) from exc
        _cron({**config, "frequency": "daily"})
    elif trigger_type != Automation.Trigger.MANUAL:
        raise _invalid("trigger_type", _("Unknown trigger."))
    return subject.key, ""


def _check_steps(
    steps: Any, subject: registry.Subject, user: Any, depth: int = 0
) -> tuple[list[str], int]:
    """Problems with the steps, and how many steps there are (nested ones included)."""
    if not isinstance(steps, list):
        return [_("Steps must be a list.")], 0
    if depth > MAX_NESTING:
        return [_("Branches are nested too deeply.")], 0
    errors: list[str] = []
    count = 0
    paths = subject.field_paths()
    for index, step in enumerate(steps):
        count += 1
        label = f"{index + 1}"
        if not isinstance(step, dict):
            errors.append(_("Step %(n)s is not valid.") % {"n": label})
            continue
        kind = step.get("type")
        if kind == "action":
            action = registry.action(str(step.get("action") or ""))
            if action is None:
                errors.append(_("Step %(n)s: unknown action.") % {"n": label})
                continue
            if action.subjects and subject.key not in action.subjects:
                errors.append(
                    _("Step %(n)s: %(a)s doesn't work on this kind of record.")
                    % {"n": label, "a": action.label}
                )
            if action.permission and user is not None and not _may(user, action.permission):
                raise PermissionDenied(
                    _("You need permission to use “%(a)s”.") % {"a": action.label}
                )
            config = step.get("config") or {}
            for f in action.fields:
                if f.required and config.get(f.name) in (None, "", []):
                    errors.append(_("Step %(n)s: fill in %(f)s.") % {"n": label, "f": f.label})
        elif kind == "wait":
            hours = float(step.get("hours") or 0) + 24 * float(step.get("days") or 0)
            until = step.get("until")
            if until and until not in paths:
                errors.append(_("Step %(n)s: unknown date field.") % {"n": label})
            if not until and not 0 < hours <= 24 * MAX_WAIT_DAYS:
                errors.append(_("Step %(n)s: wait between an hour and a year.") % {"n": label})
        elif kind == "branch":
            errors += [f"{label}: {e}" for e in conditions.validate(step.get("if"), paths)]
            for arm in ("then", "else"):
                more, n = _check_steps(step.get(arm) or [], subject, user, depth + 1)
                errors += more
                count += n
        else:
            errors.append(_("Step %(n)s: unknown step type.") % {"n": label})
    return errors, count


def _may(user: Any, codename: str) -> bool:
    from tutortrack.core.permissions import has_perm

    return has_perm(user, codename)


def validate_definition(
    *, trigger_type: str, trigger_config: dict[str, Any], conditions_: dict[str, Any],
    steps: list[dict[str, Any]], user: Any = None,
) -> tuple[str, str]:  # fmt: skip
    subject_type, trigger_key = _subject_for(trigger_type, trigger_config or {})
    subject = registry.subject(subject_type)
    if subject is None:
        raise _invalid("trigger_config", _("This kind of record isn't supported yet."))
    problems = conditions.validate(conditions_, subject.field_paths())
    if problems:
        raise _invalid("conditions", problems)
    step_errors, count = _check_steps(steps, subject, user)
    if step_errors:
        raise _invalid("steps", step_errors)
    if count == 0:
        raise _invalid("steps", _("Add at least one step."))
    if count > MAX_STEPS:
        raise _invalid("steps", _("Use at most %(n)s steps.") % {"n": MAX_STEPS})
    return subject_type, trigger_key


def _snapshot(automation: Automation) -> AutomationVersion:
    return AutomationVersion.objects.create(
        automation=automation,
        version=automation.version,
        trigger_type=automation.trigger_type,
        trigger_config=automation.trigger_config,
        conditions=automation.conditions,
        steps=automation.steps,
    )


def _saved(automation: Automation) -> None:
    publish(
        events.AutomationSaved(
            subject_id=automation.pk,
            trigger_type=automation.trigger_type,
            enabled=automation.enabled,
            automation_version=automation.version,
        )
    )


@transaction.atomic
def create_automation(
    *,
    name: str,
    trigger_type: str,
    trigger_config: dict[str, Any],
    steps: list[dict[str, Any]],
    conditions_: dict[str, Any] | None = None,
    description: str = "",
    enabled: bool = False,
    max_runs_per_record: int = 1,
    recipe_key: str = "",
    user: Any = None,
) -> Automation:
    subject_type, trigger_key = validate_definition(
        trigger_type=trigger_type, trigger_config=trigger_config,
        conditions_=conditions_ or {}, steps=steps, user=user,
    )  # fmt: skip
    automation = Automation.objects.create(
        name=name,
        description=description,
        trigger_type=trigger_type,
        trigger_key=trigger_key,
        trigger_config=trigger_config,
        subject_type=subject_type,
        conditions=conditions_ or {},
        steps=steps,
        enabled=enabled,
        max_runs_per_record=max_runs_per_record,
        recipe_key=recipe_key,
        webhook_secret=secrets.token_urlsafe(32),
    )
    _snapshot(automation)
    audit.record_create(automation)
    _saved(automation)
    return automation


@transaction.atomic
def update_automation(automation: Automation, *, user: Any = None, **changes: Any) -> Automation:
    """Edit; a changed trigger, conditions or steps make a new version."""
    automation = Automation.objects.select_for_update().get(pk=automation.pk)
    if "conditions_" in changes:
        changes["conditions"] = changes.pop("conditions_")
    definition_changed = any(
        k in changes and changes[k] != getattr(automation, k) for k in DEFINITION
    )
    if definition_changed:
        subject_type, trigger_key = validate_definition(
            trigger_type=changes.get("trigger_type", automation.trigger_type),
            trigger_config=changes.get("trigger_config", automation.trigger_config),
            conditions_=changes.get("conditions", automation.conditions),
            steps=changes.get("steps", automation.steps),
            user=user,
        )
        changes |= {"subject_type": subject_type, "trigger_key": trigger_key}
    allowed = {"name", "description", "enabled", "max_runs_per_record", *DEFINITION,
               "subject_type", "trigger_key"}  # fmt: skip
    with audit.track(automation):
        for key, value in changes.items():
            if key in allowed:
                setattr(automation, key, value)
        if definition_changed:
            automation.version += 1
        automation.save()
    if definition_changed:
        _snapshot(automation)
    _saved(automation)
    return automation


def set_enabled(automation: Automation, enabled: bool, *, user: Any = None) -> Automation:
    return update_automation(automation, enabled=enabled, user=user)


@transaction.atomic
def delete_automation(automation: Automation) -> None:
    audit.record(automation, "delete")
    publish(events.AutomationDeleted(subject_id=automation.pk))
    automation.enabled = False
    automation.save(update_fields=["enabled", "updated_at"])
    automation.delete()


# --- context ------------------------------------------------------------------------------------


def build_context(
    subject: registry.Subject, obj: Any, event: EventEnvelope | None = None
) -> dict[str, Any]:
    context: dict[str, Any] = {subject.key: subject.context(obj)}
    if event is not None:
        context["event"] = {
            "type": event.type,
            "data": event.data,
            "changes": event.changes,
            "actor": event.actor.get("type"),
        }
    return context


# --- runs (T03) ---------------------------------------------------------------------------------


def _depth_of(event: EventEnvelope | None) -> int:
    """How many automations deep this event is: events written by an automation's run carry
    the workflow as actor (loop detection)."""
    if event is None:
        return 0
    actor = event.actor or {}
    if actor.get("type") != "workflow" or not str(actor.get("id") or "").startswith("automation:"):
        return 0
    parent = AutomationRun.objects.filter(workflow_id=actor["id"]).first()
    return (parent.causation_depth + 1) if parent else 1


def _workflow_id(run: AutomationRun) -> str:
    from tutortrack.core.workflows import workflow_id

    key = run.run_key.replace(":", "-")
    return workflow_id("automation", run.organisation_id, run.automation_id,
                       run.subject_id or "none", key)  # fmt: skip


def prepare_run(
    automation: Automation,
    *,
    subject_id: str,
    run_key: str,
    event: EventEnvelope | None = None,
    manual: bool = False,
) -> AutomationRun | None:
    """Guardrails and conditions; returns the new run, or ``None`` when it shouldn't run."""
    if not manual and not automation.enabled:
        return None
    if not _setting("automations.enabled"):
        return None
    subject = registry.subject(automation.subject_type)
    obj = subject.load(subject_id) if subject is not None else None
    if subject is None or obj is None:
        return None
    current = now()
    if AutomationRun.objects.filter(
        automation=automation, subject_id=subject_id, run_key=run_key
    ).exists():
        return None  # this event (or schedule slot) already ran for the record
    if not manual:
        recent = AutomationRun.objects.filter(
            automation=automation, subject_id=subject_id,
            started_at__gte=current - timedelta(hours=24),
        ).exclude(status=AutomationRun.Status.SKIPPED).count()  # fmt: skip
        if recent >= automation.max_runs_per_record:
            return None
        hourly = AutomationRun.objects.filter(started_at__gte=current - timedelta(hours=1))
        if hourly.count() >= int(_setting("automations.max_runs_per_hour")):
            logger.warning("automation.rate_limited", automation_id=str(automation.pk))
            return None
    version = automation.versions.get(version=automation.version)
    depth = _depth_of(event)
    status = AutomationRun.Status.RUNNING
    error = ""
    if depth > MAX_CAUSATION_DEPTH:
        status, error = (
            AutomationRun.Status.SKIPPED,
            _("Stopped: automations triggering each other."),
        )
    elif not conditions.evaluate(automation.conditions, build_context(subject, obj, event)):
        return None
    try:
        with transaction.atomic():
            run = AutomationRun.objects.create(
                automation=automation,
                version=version,
                subject_type=subject.key,
                subject_id=str(subject_id),
                event_id=event.id if event else None,
                event_type=event.type if event else "",
                run_key=run_key[:200],
                status=status,
                causation_depth=depth,
                error=error,
                finished_at=current if status == AutomationRun.Status.SKIPPED else None,
            )
            run.workflow_id = _workflow_id(run)
            run.save(update_fields=["workflow_id", "updated_at"])
    except IntegrityError:
        return None
    return run


def launch(run: AutomationRun, *, start_at: int = 0) -> None:
    from tutortrack.core.workflows import start_now

    from .processes import AutomationRunWorkflow, RunInput

    if run.status == AutomationRun.Status.SKIPPED:
        return
    start_now(
        AutomationRunWorkflow,
        RunInput(organisation_id=str(run.organisation_id), run_id=str(run.pk), start_at=start_at),
        id=run.workflow_id,
        subject=("automation_run", str(run.pk)),
    )


def on_event(event: EventEnvelope) -> list[AutomationRun]:
    """Start the enabled automations listening for this event (the outbox subscriber)."""
    trigger = registry.trigger(event.type)
    if trigger is None or event.subject.get("type") != trigger.subject:
        return []
    started = []
    for automation in Automation.objects.filter(
        enabled=True, trigger_type=Automation.Trigger.EVENT, trigger_key=event.type
    ):
        run = prepare_run(
            automation, subject_id=str(event.subject["id"]), run_key=str(event.id), event=event
        )
        if run is not None:
            launch(run)
            started.append(run)
    return started


def run_manually(automation: Automation, subject_ids: list[str]) -> list[AutomationRun]:
    """The "Run automation" button: one run per chosen record (no daily limit)."""
    runs = []
    for subject_id in subject_ids[:200]:
        run = prepare_run(
            automation, subject_id=str(subject_id), run_key=f"manual:{uuid.uuid4()}", manual=True
        )
        if run is not None:
            launch(run)
            runs.append(run)
    return runs


@transaction.atomic
def retry(run: AutomationRun) -> AutomationRun:
    """Re-run from the failed step (completed steps aren't repeated)."""
    run = AutomationRun.objects.select_for_update().get(pk=run.pk)
    if run.status != AutomationRun.Status.FAILED:
        raise BusinessRuleViolation(_("Only failed runs can be retried."))
    failed = run.steps.filter(status=AutomationRunStep.Status.FAILED).order_by("created_at").first()
    start_at = int(failed.step_key.split(".")[0]) if failed else 0
    run.steps.filter(status=AutomationRunStep.Status.FAILED).delete()
    run.attempts += 1
    run.status = AutomationRun.Status.RUNNING
    run.error = ""
    run.finished_at = None
    base = _workflow_id(run)
    run.workflow_id = f"{base}-retry{run.attempts}"
    run.save()
    audit.record(run, "retry", {"attempts": [run.attempts - 1, run.attempts]})
    transaction.on_commit(lambda: launch(run, start_at=start_at))
    return run


# --- step execution (activities call these) -----------------------------------------------------


def _run_parts(run_id: str) -> tuple[AutomationRun, registry.Subject, Any]:
    run = AutomationRun.objects.select_related("automation", "version").get(pk=run_id)
    subject = registry.subject(run.subject_type)
    if subject is None:
        raise BusinessRuleViolation(_("This kind of record isn't supported any more."))
    obj = subject.load(run.subject_id)
    if obj is None:
        raise BusinessRuleViolation(_("The record no longer exists."))
    return run, subject, obj


def _author(automation: Automation) -> Any:
    from tutortrack.identity.models import User

    user_id = automation.updated_by_id or automation.created_by_id
    return User.objects.filter(pk=user_id).first() if user_id else None


def load_plan(run_id: str) -> list[dict[str, Any]]:
    run = AutomationRun.objects.select_related("version").get(pk=run_id)
    steps: list[dict[str, Any]] = run.version.steps
    return steps


def _record(run: AutomationRun, key: str, kind: str, status: str, **fields: Any) -> None:
    AutomationRunStep.objects.update_or_create(
        run=run, step_key=key, defaults={"step_type": kind, "status": status, **fields}
    )


def execute_step(run_id: str, key: str, step: dict[str, Any]) -> dict[str, Any]:
    """Run one action once: a completed step returns its stored result."""
    done = AutomationRunStep.objects.filter(
        run_id=run_id, step_key=key, status=AutomationRunStep.Status.COMPLETED
    ).first()
    if done is not None:
        return {"status": "completed", "result": done.result}
    run = AutomationRun.objects.select_related("automation").get(pk=run_id)
    try:
        with transaction.atomic():
            run, subject, obj = _run_parts(run_id)
            action = registry.action(str(step.get("action") or ""))
            if action is None:
                raise BusinessRuleViolation(_("Unknown action."))
            author = _author(run.automation)
            if action.permission and not (author is not None and _may(author, action.permission)):
                raise BusinessRuleViolation(
                    _("The automation's author no longer has permission for “%(a)s”.")
                    % {"a": action.label}
                )
            ctx = RunContext(
                automation=run.automation, subject=subject, obj=obj,
                context=build_context(subject, obj), key=f"automation:{run.pk}:{key}",
                author=author,
            )  # fmt: skip
            result = action.run(ctx, step.get("config") or {})
            _record(run, key, "action", AutomationRunStep.Status.COMPLETED, result=result, error="")
    except (BusinessRuleViolation, PermissionDenied, ValueError) as exc:
        message = str(getattr(exc, "detail", exc))
        _record(run, key, "action", AutomationRunStep.Status.FAILED, error=message[:2000])
        return {"status": "failed", "error": message}
    return {"status": "completed", "result": result}


def evaluate_branch(run_id: str, key: str, cond: dict[str, Any]) -> bool:
    run, subject, obj = _run_parts(run_id)
    outcome = conditions.evaluate(cond, build_context(subject, obj))
    _record(run, key, "branch", AutomationRunStep.Status.COMPLETED, result={"matched": outcome})
    return outcome


def start_wait(run_id: str, key: str, step: dict[str, Any], from_iso: str) -> str:
    """When the wait ends (ISO), recorded on the run log. ``until`` waits read a date on the
    record (plus ``offset_hours``); a missing date ends the wait at once."""
    run, subject, obj = _run_parts(run_id)
    start = datetime.fromisoformat(from_iso)
    if step.get("until"):
        value = conditions.resolve(build_context(subject, obj), str(step["until"]))
        moment = conditions._when(value)
        resume = (
            (moment + timedelta(hours=float(step.get("offset_hours") or 0))) if moment else start
        )
    else:
        hours = float(step.get("hours") or 0) + 24 * float(step.get("days") or 0)
        resume = start + timedelta(hours=hours)
    _record(run, key, "wait", AutomationRunStep.Status.WAITING, resume_at=resume)
    AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.WAITING)
    return resume.isoformat()


def end_wait(run_id: str, key: str) -> None:
    run = AutomationRun.objects.get(pk=run_id)
    _record(run, key, "wait", AutomationRunStep.Status.COMPLETED)
    AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.RUNNING)


@transaction.atomic
def finish(run_id: str, status: str, error: str = "") -> None:
    run = AutomationRun.objects.select_for_update().get(pk=run_id)
    if run.finished_at is not None and run.status == status:
        return
    if status == AutomationRun.Status.FAILED and not error:
        failed = run.steps.filter(status=AutomationRunStep.Status.FAILED).first()
        error = failed.error if failed else ""
    run.status = status
    run.error = error[:2000]
    run.finished_at = now()
    run.save(update_fields=["status", "error", "finished_at", "updated_at"])
    if status == AutomationRun.Status.FAILED:
        publish(
            events.AutomationRunFailed(
                subject_id=run.pk, automation_id=str(run.automation_id), error=run.error[:300]
            )
        )


# --- dry run (FR-14-4) --------------------------------------------------------------------------


def _describe_steps(
    steps: list[dict[str, Any]], ctx: RunContext, prefix: str = ""
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        key = f"{prefix}{index}"
        kind = step.get("type")
        if kind == "action":
            action = registry.action(str(step.get("action") or ""))
            try:
                text = action.describe(ctx, step.get("config") or {}) if action else _("Unknown")
                out.append({"key": key, "type": "action", "description": text, "ok": True})
            except (BusinessRuleViolation, ValueError) as exc:
                out.append(
                    {
                        "key": key,
                        "type": "action",
                        "description": str(getattr(exc, "detail", exc)),
                        "ok": False,
                    }
                )
        elif kind == "wait":
            if step.get("until"):
                text = _("Wait until %(f)s") % {"f": step["until"]}
            else:
                hours = float(step.get("hours") or 0) + 24 * float(step.get("days") or 0)
                text = _("Wait %(h)s hours") % {"h": f"{hours:g}"}
            out.append({"key": key, "type": "wait", "description": text, "ok": True})
        elif kind == "branch":
            matched = conditions.evaluate(step.get("if"), ctx.context)
            arm = "then" if matched else "else"
            out.append({"key": key, "type": "branch", "ok": True,
                        "description": _("Condition is %(v)s") % {"v": matched}})  # fmt: skip
            out += _describe_steps(step.get(arm) or [], ctx, f"{key}.{arm}.")
    return out


def dry_run(automation: Automation, subject_id: str) -> dict[str, Any]:
    """What would happen for this record now, without doing it."""
    subject = registry.subject(automation.subject_type)
    obj = subject.load(subject_id) if subject is not None else None
    if subject is None or obj is None:
        raise _invalid("subject_id", _("Record not found."))
    context = build_context(subject, obj)
    matched = conditions.evaluate(automation.conditions, context)
    ctx = RunContext(automation=automation, subject=subject, obj=obj, context=context,
                     key="dry-run", author=_author(automation))  # fmt: skip
    return {
        "matched": matched,
        "record": context,
        "steps": _describe_steps(automation.steps, ctx) if matched else [],
    }


# --- schedule and date triggers (T06) -----------------------------------------------------------


def _cron(config: dict[str, Any]) -> list[str]:
    try:
        hour, minute = (int(x) for x in str(config.get("time") or "08:00").split(":"))
    except ValueError as exc:
        raise _invalid("trigger_config", _("Give the time as HH:MM.")) from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise _invalid("trigger_config", _("Give the time as HH:MM."))
    frequency = config.get("frequency") or "daily"
    if frequency == "weekly":
        weekday = int(config.get("weekday") or 0) % 7  # Monday = 0
        return [f"{minute} {hour} * * {(weekday + 1) % 7}"]
    if frequency == "monthly":
        day = min(max(int(config.get("day") or 1), 1), 28)
        return [f"{minute} {hour} {day} * *"]
    return [f"{minute} {hour} * * *"]


def org_today() -> date:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    org = Organisation.objects.get(pk=require_organisation_id())
    return now().astimezone(ZoneInfo(org.timezone)).date()


def due_records(automation: Automation, on: date) -> list[str]:
    """Records a schedule or date trigger picks on ``on`` (before conditions)."""
    subject = registry.subject(automation.subject_type)
    if subject is None:
        return []
    model = subject.model_class()
    qs = model.objects.all()
    if hasattr(model, "archived_at"):
        qs = qs.filter(archived_at__isnull=True)
    config = automation.trigger_config or {}
    if automation.trigger_type == Automation.Trigger.DATE:
        name = str(config["field"])
        target = on - timedelta(days=int(config.get("offset_days") or 0))
        is_datetime = model._meta.get_field(name).get_internal_type() == "DateTimeField"
        lookup = f"{name}__date" if is_datetime else name
        if config.get("anniversary"):
            qs = qs.filter(**{f"{lookup}__month": target.month, f"{lookup}__day": target.day})
        else:
            qs = qs.filter(**{lookup: target})
    return [str(pk) for pk in qs.values_list("pk", flat=True)[:FAN_OUT_LIMIT]]


def fan_out(automation_id: str, on: date | None = None) -> int:
    """A schedule fired: one run per matching record (ids dedupe per day)."""
    automation = Automation.objects.filter(pk=automation_id, enabled=True).first()
    if automation is None:
        return 0
    day = on or org_today()
    started = 0
    for subject_id in due_records(automation, day):
        run = prepare_run(automation, subject_id=subject_id, run_key=f"schedule:{day.isoformat()}")
        if run is not None:
            launch(run)
            started += 1
    return started


def sync_schedule(automation_id: str) -> str | None:
    """Create, update or remove the automation's Temporal Schedule."""
    from tutortrack.core.context import require_organisation_id
    from tutortrack.core.workflows.schedules import delete_schedule, ensure_schedule, schedule_id
    from tutortrack.tenancy.models import Organisation

    from .processes import SCHEDULE_PROCESS, AutomationScheduleWorkflow, ScheduleInput

    org_id = require_organisation_id()
    sid = schedule_id(SCHEDULE_PROCESS, org_id, automation_id)
    automation = Automation.objects.filter(pk=automation_id).first()
    timed = (Automation.Trigger.SCHEDULE, Automation.Trigger.DATE)
    if automation is None or not automation.enabled or automation.trigger_type not in timed:
        delete_schedule(org_id, sid)
        return None
    config = dict(automation.trigger_config or {})
    if automation.trigger_type == Automation.Trigger.DATE:
        config["frequency"] = "daily"
    org = Organisation.objects.get(pk=org_id)
    return ensure_schedule(
        process=SCHEDULE_PROCESS,
        workflow=AutomationScheduleWorkflow,
        input=ScheduleInput(organisation_id=str(org_id), automation_id=str(automation_id)),
        cron=_cron(config),
        timezone=org.timezone,
        parts=(automation_id,),
    )
