"""Automation writes and the engine's steps (E14).

* Definitions: validated against the registry; editing the trigger, conditions or steps
  makes a new ``AutomationVersion`` (runs keep the version they started on).
* Built-ins (E33 FR-33-2): ``install_builtins`` installs and upgrades the shipped defaults,
  ``reset_to_default`` puts one back; saving marks it ``edited`` so upgrades leave it alone.
* Runs: ``prepare_run`` applies the guardrails (kill switch, per-record daily limit,
  per-organisation hourly limit, loop depth) and the conditions, then ``launch`` starts
  ``AutomationRunWorkflow``. The workflow calls ``execute_step`` / ``evaluate_branch`` /
  ``start_wait`` / ``finish``, which are idempotent per run and step.
"""

from __future__ import annotations

import functools
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from tutortrack.core import audit, entitlements
from tutortrack.core.context import current_organisation_id
from tutortrack.core.events import EventEnvelope, publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.time import now

from . import builtin_workflows, conditions, events, registry
from .actions import RunContext
from .models import Automation, AutomationRun, AutomationRunStep, AutomationVersion

logger = structlog.get_logger(__name__)

MAX_STEPS = 30
MAX_NESTING = 3
MAX_CAUSATION_DEPTH = 3
MAX_WAIT_DAYS = 365
FAN_OUT_LIMIT = 2000
DEFINITION = ("trigger_type", "trigger_config", "conditions", "steps", "stop_when")
MAX_STOP_EVENTS = 3
FREQUENCIES = ("daily", "weekly", "monthly")
UNDER_WAY = (
    AutomationRun.Status.RUNNING, AutomationRun.Status.WAITING, AutomationRun.Status.PAUSED,
)  # fmt: skip


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
        if "minutes" in config:
            _check_near(config, subject)
            return subject.key, ""
        _offsets(config)
        _cron({**config, "frequency": "daily"})
    elif trigger_type != Automation.Trigger.MANUAL:
        raise _invalid("trigger_type", _("Unknown trigger."))
    return subject.key, ""


MAX_OFFSETS = 6


def _offsets(config: dict[str, Any]) -> list[int]:
    """A date start's days before (negative) or after the date: one number, or a list of up
    to six for a reminder on each (E33 T06: 60, 30 and 7 days before a check expires)."""
    raw = config.get("offset_days")
    values = raw if isinstance(raw, list) else [raw or 0]
    try:
        days = [int(d) for d in values]
    except (TypeError, ValueError) as exc:
        raise _invalid("trigger_config", _("Days before or after is a number.")) from exc
    if not 0 < len(days) <= MAX_OFFSETS or any(abs(d) > 366 for d in days):
        raise _invalid("trigger_config", _("Give up to six days, up to a year before or after."))
    return days


# "Near a date" starts (E33 T05): a run per record when its date plus each of ``minutes``
# (negative before, positive after) comes round, e.g. a lesson reminder 24 hours and 1 hour
# before the start. A Temporal Schedule every 15 minutes picks the records whose moment fell
# in the last ``catch_up_minutes`` (60 by default), so a moved lesson is picked at its new
# time and nothing waits for weeks; the run key carries the moment, so each runs once.
NEAR_EVERY_MINUTES = 15
MAX_NEAR_MINUTES = 60 * 24 * 30


def _check_near(config: dict[str, Any], subject: registry.Subject) -> None:
    minutes = config.get("minutes")
    model = subject.model_class()
    field = model._meta.get_field(str(config["field"]))
    if field.get_internal_type() != "DateTimeField":
        raise _invalid("trigger_config", _("Choose a date and time on the record."))
    valid = isinstance(minutes, list) and 0 < len(minutes) <= 6 and all(
        isinstance(m, int) and abs(m) <= MAX_NEAR_MINUTES for m in minutes
    )  # fmt: skip
    if not valid:
        raise _invalid("trigger_config", _("Give up to six times, up to 30 days before or after."))
    catch_up = config.get("catch_up_minutes", 60)
    if not isinstance(catch_up, int) or not NEAR_EVERY_MINUTES <= catch_up <= 24 * 60:
        raise _invalid("trigger_config", _("Catch up between 15 minutes and a day."))


def near_records(automation: Automation, moment: datetime) -> list[tuple[str, str]]:
    """(record id, run key) for each record whose date plus one of the start's minutes fell
    in the catch-up window before ``moment``."""
    subject = registry.subject(automation.subject_type)
    if subject is None:
        return []
    config = automation.trigger_config or {}
    name = str(config["field"])
    catch_up = timedelta(minutes=int(config.get("catch_up_minutes", 60)))
    out: list[tuple[str, str]] = []
    for minutes in config.get("minutes") or []:
        offset = timedelta(minutes=int(minutes))
        rows = (
            subject.model_class()
            .objects.filter(
                **{f"{name}__gt": moment - offset - catch_up, f"{name}__lte": moment - offset}
            )
            .values_list("pk", name)[:FAN_OUT_LIMIT]
        )
        out += [(str(pk), f"schedule:near:{minutes}:{value.isoformat()}") for pk, value in rows]
    return out


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
            if step.get("only_if"):
                errors += [
                    f"{label}: {e}"
                    for e in conditions.validate(step["only_if"], paths, subject=subject.key)
                ]
            if action.key == "start_workflow" and not _same_kind(config, subject.key):
                errors.append(
                    _("Step %(n)s: choose a workflow about the same kind of record.") % {"n": label}
                )
        elif kind == "wait":
            errors += _check_wait(step, label, paths)
        elif kind == "branch":
            errors += [
                f"{label}: {e}"
                for e in conditions.validate(step.get("if"), paths, subject=subject.key)
            ]
            for arm in ("then", "else"):
                more, n = _check_steps(step.get(arm) or [], subject, user, depth + 1)
                errors += more
                count += n
        else:
            errors.append(_("Step %(n)s: unknown step type.") % {"n": label})
    return errors, count


def _same_kind(config: dict[str, Any], subject_type: str) -> bool:
    """ "Start another workflow" needs one about the same kind of record."""
    workflow = str(config.get("workflow") or "")
    try:
        uuid.UUID(workflow)
    except ValueError:
        return False
    return Automation.objects.filter(pk=workflow, subject_type=subject_type).exists()


def _number(value: Any) -> float | None:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return None


def _check_wait(step: dict[str, Any], label: str, paths: Any) -> list[str]:
    """A wait counts from now (``days``/``hours``) or from a date on the record (``until``
    with ``offset_days``/``offset_hours``, negative for before), optionally ``at`` a time of
    day, on a ``business_day`` and outside ``quiet_hours`` (E33 FR-33-1)."""
    from .timing import AT

    errors: list[str] = []
    until = step.get("until")
    if until:
        if until not in paths:
            errors.append(_("Step %(n)s: unknown date field.") % {"n": label})
        days, hours = _number(step.get("offset_days")), _number(step.get("offset_hours"))
        if days is None or hours is None or abs(days + hours / 24) > MAX_WAIT_DAYS:
            errors.append(
                _("Step %(n)s: count up to a year before or after the date.") % {"n": label}
            )
    else:
        days, hours = _number(step.get("days")), _number(step.get("hours"))
        total = None if days is None or hours is None else hours + 24 * days
        # With a time of day, "0 days at 18:00" (today) is fine; otherwise it must wait.
        too_short = total is not None and (total < 0 if step.get("at") else total <= 0)
        if total is None or too_short or total > 24 * MAX_WAIT_DAYS:
            errors.append(_("Step %(n)s: wait between an hour and a year.") % {"n": label})
    if step.get("at") and not AT.match(str(step["at"])):
        errors.append(_("Step %(n)s: give the time as HH:MM, like 09:00.") % {"n": label})
    for flag in ("business_day", "quiet_hours"):
        if flag in step and not isinstance(step[flag], bool):
            errors.append(_("Step %(n)s is not valid.") % {"n": label})
    return errors


def _check_stop_when(stop_when: Any, subject_type: str) -> list[str]:
    """Stop-when events must be about the same kind of record as the run."""
    if not isinstance(stop_when, list) or not all(isinstance(e, str) for e in stop_when):
        return [_("Choose events to stop on.")]
    if len(stop_when) > MAX_STOP_EVENTS:
        return [_("Stop on at most %(n)s events.") % {"n": MAX_STOP_EVENTS}]
    errors = []
    for event in stop_when:
        trigger = registry.trigger(event)
        if trigger is None or trigger.subject != subject_type:
            errors.append(_("“%(e)s” can't stop this workflow.") % {"e": event})
    return errors


def _may(user: Any, codename: str) -> bool:
    from tutortrack.core.permissions import has_perm

    return has_perm(user, codename)


def validate_definition(
    *, trigger_type: str, trigger_config: dict[str, Any], conditions_: dict[str, Any],
    steps: list[dict[str, Any]], user: Any = None, stop_when: list[str] | None = None,
) -> tuple[str, str]:  # fmt: skip
    subject_type, trigger_key = _subject_for(trigger_type, trigger_config or {})
    subject = registry.subject(subject_type)
    if subject is None:
        raise _invalid("trigger_config", _("This kind of record isn't supported yet."))
    problems = conditions.validate(conditions_, subject.field_paths(), subject=subject.key)
    if problems:
        raise _invalid("conditions", problems)
    stopping = _check_stop_when(stop_when or [], subject_type)
    if stopping:
        raise _invalid("stop_when", stopping)
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
        stop_when=automation.stop_when,
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
    stop_when: list[str] | None = None,
    user: Any = None,
    builtin: builtin_workflows.BuiltinWorkflow | None = None,
) -> Automation:
    """A custom workflow (counted against the plan's ``automation_rules``), or with
    ``builtin`` the organisation's copy of a built-in one (on every plan)."""
    subject_type, trigger_key = validate_definition(
        trigger_type=trigger_type, trigger_config=trigger_config,
        conditions_=conditions_ or {}, steps=steps, user=user, stop_when=stop_when,
    )  # fmt: skip
    if builtin is None:
        used = Automation.objects.filter(kind=Automation.Kind.CUSTOM).count()
        entitlements.require_capacity("automation_rules", used=used)
    automation = Automation.objects.create(
        name=name,
        description=description,
        trigger_type=trigger_type,
        trigger_key=trigger_key,
        trigger_config=trigger_config,
        subject_type=subject_type,
        conditions=conditions_ or {},
        steps=steps,
        stop_when=stop_when or [],
        enabled=enabled,
        max_runs_per_record=max_runs_per_record,
        recipe_key=recipe_key,
        webhook_secret=secrets.token_urlsafe(32),
        kind=Automation.Kind.BUILTIN if builtin else Automation.Kind.CUSTOM,
        builtin_key=builtin.key if builtin else "",
        builtin_version=builtin.version if builtin else None,
    )
    if builtin is not None:
        automation.edited = _differs_from_default(automation, builtin)
        automation.save(update_fields=["edited"])
    _snapshot(automation)
    audit.record_create(automation)
    _saved(automation)
    return automation


def update_automation(automation: Automation, *, user: Any = None, **changes: Any) -> Automation:
    """Edit; a changed trigger, conditions or steps make a new version. A built-in keeps
    its name, description and kind of record, and is marked edited when its definition no
    longer matches the default."""
    return _update(automation, user=user, changes=changes)


@transaction.atomic
def _update(
    automation: Automation, *, user: Any, changes: dict[str, Any],
    default: builtin_workflows.BuiltinWorkflow | None = None, action: str = "update",
) -> Automation:  # fmt: skip
    """``default``: the built-in's default is being applied (reset or upgrade)."""
    automation = Automation.objects.select_for_update().get(pk=automation.pk)
    if "conditions_" in changes:
        changes["conditions"] = changes.pop("conditions_")
    builtin = _builtin_of(automation) if automation.kind == Automation.Kind.BUILTIN else None
    if automation.kind == Automation.Kind.BUILTIN:
        changes.pop("name", None)
        changes.pop("description", None)
        if (
            "enabled" in changes and not changes["enabled"] and automation.enabled
            and builtin is not None and not builtin.can_switch_off
        ):  # fmt: skip
            raise BusinessRuleViolation(
                _("“%(name)s” can't be switched off. Change its steps or pause it instead.")
                % {"name": automation.name}
            )
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
            stop_when=changes.get("stop_when", automation.stop_when),
        )
        if automation.kind == Automation.Kind.BUILTIN and subject_type != automation.subject_type:
            raise _invalid(
                "trigger_config", _("A built-in workflow keeps the kind of record it is about.")
            )
        changes |= {"subject_type": subject_type, "trigger_key": trigger_key}
    allowed = {"name", "description", "enabled", "max_runs_per_record", *DEFINITION,
               "subject_type", "trigger_key"}  # fmt: skip
    with audit.track(automation, action=action):
        for key, value in changes.items():
            if key in allowed:
                setattr(automation, key, value)
        if definition_changed:
            automation.version += 1
        if default is not None:
            automation.builtin_version = default.version
            automation.name = str(_(default.name))
            automation.description = str(_(default.description))
        if builtin is not None:
            automation.edited = _differs_from_default(automation, builtin)
        automation.save()
    if definition_changed:
        _snapshot(automation)
    _saved(automation)
    return automation


def set_enabled(automation: Automation, enabled: bool, *, user: Any = None) -> Automation:
    return update_automation(automation, enabled=enabled, user=user)


@transaction.atomic
def pause(automation: Automation, *, user: Any = None) -> Automation:
    """No new runs start; runs under way hold before their next action (E33 FR-33-3)."""
    automation = Automation.objects.select_for_update().get(pk=automation.pk)
    with audit.track(automation, action="pause"):
        automation.paused = True
        automation.save(update_fields=["paused", "updated_at"])
    return automation


@transaction.atomic
def resume(automation: Automation, *, user: Any = None) -> Automation:
    """Carry on: held runs continue from the action they stopped before."""
    from tutortrack.core.workflows import signal

    automation = Automation.objects.select_for_update().get(pk=automation.pk)
    with audit.track(automation, action="resume"):
        automation.paused = False
        automation.save(update_fields=["paused", "updated_at"])
    held = AutomationRun.objects.filter(
        automation=automation, status=AutomationRun.Status.PAUSED
    ).exclude(workflow_id="")
    for run in held:
        signal(run.workflow_id, "resume")
    return automation


@transaction.atomic
def delete_automation(automation: Automation) -> None:
    if automation.kind == Automation.Kind.BUILTIN:
        raise BusinessRuleViolation(
            _("Built-in workflows can't be deleted. Switch it off or reset it to the default.")
        )
    audit.record(automation, "delete")
    publish(events.AutomationDeleted(subject_id=automation.pk))
    automation.enabled = False
    automation.save(update_fields=["enabled", "updated_at"])
    automation.delete()


# --- built-in workflows (E33 T03) ---------------------------------------------------------------


def _builtin_of(automation: Automation) -> builtin_workflows.BuiltinWorkflow | None:
    return builtin_workflows.builtin(automation.builtin_key) if automation.builtin_key else None


def _differs_from_default(
    automation: Automation, builtin: builtin_workflows.BuiltinWorkflow
) -> bool:
    default = builtin.definition()
    return any(
        getattr(automation, key) != default[key] for key in builtin_workflows.DEFINITION_KEYS
    )


def update_available(automation: Automation) -> bool:
    """An edited built-in whose default TutorTrack has improved since (offer compare and reset)."""
    builtin = _builtin_of(automation)
    return bool(
        builtin and automation.edited and (automation.builtin_version or 0) < builtin.version
    )


def install_builtins() -> dict[str, int]:
    """Install the built-ins the organisation doesn't have yet, from its current settings,
    and move unedited ones to a newer default. Edited ones are left as they are
    (``update_available``). Idempotent: runs at sign-up and on every deploy."""
    existing = {a.builtin_key: a for a in Automation.objects.filter(kind=Automation.Kind.BUILTIN)}
    counts = {"installed": 0, "upgraded": 0}
    for builtin in builtin_workflows.all_builtins():
        found = existing.get(builtin.key)
        try:
            if found is None:
                with transaction.atomic():
                    definition, enabled = builtin.first()
                    create_automation(
                        name=str(_(builtin.name)), description=str(_(builtin.description)),
                        trigger_type=definition["trigger_type"],
                        trigger_config=definition["trigger_config"],
                        conditions_=definition["conditions"], steps=definition["steps"],
                        stop_when=definition["stop_when"], enabled=enabled,
                        max_runs_per_record=builtin.max_runs_per_record, builtin=builtin,
                    )  # fmt: skip
                counts["installed"] += 1
            elif not found.edited and (found.builtin_version or 0) < builtin.version:
                _update(found, user=None, changes=builtin.definition(), default=builtin,
                        action="upgrade")  # fmt: skip
                counts["upgraded"] += 1
        except (BusinessRuleViolation, IntegrityError) as exc:  # a broken default, or a race
            logger.error("automation.builtin_install_failed", key=builtin.key, error=str(exc))
            continue
        if builtin.retire is not None:  # idempotent, so a failed retirement is tried again
            org_id = current_organisation_id()
            transaction.on_commit(functools.partial(_retire, org_id, builtin))
    return counts


def _retire(organisation_id: Any, builtin: builtin_workflows.BuiltinWorkflow) -> None:
    """Remove what an installed built-in replaced (after the commit, so in the
    organisation's context again)."""
    from tutortrack.core.context import tenant_context

    if builtin.retire is None:
        return
    with tenant_context(organisation_id):
        try:
            builtin.retire()
        except Exception as exc:  # Temporal unreachable: the next sync tries again
            logger.warning("automation.builtin_retire_failed", key=builtin.key, error=str(exc))


def reset_to_default(automation: Automation, *, user: Any = None) -> Automation:
    """Put a built-in back to TutorTrack's current default. Runs under way finish on their
    version; saving still needs the permission of every action in it (ADR 0014 §6)."""
    builtin = _builtin_of(automation)
    if automation.kind != Automation.Kind.BUILTIN:
        raise BusinessRuleViolation(_("Only built-in workflows have a default to reset to."))
    if builtin is None:
        raise BusinessRuleViolation(_("TutorTrack no longer ships this built-in workflow."))
    definition = builtin.definition()
    validate_definition(
        trigger_type=definition["trigger_type"], trigger_config=definition["trigger_config"],
        conditions_=definition["conditions"], steps=definition["steps"], user=user,
        stop_when=definition["stop_when"],
    )  # fmt: skip
    return _update(automation, user=user, changes=definition, default=builtin, action="reset")


def builtin_notices() -> list[dict[str, Any]]:
    """Built-ins Home mentions: switched off when they're on by default (and what happens
    instead), or with a newer default than the organisation's edited version (FR-33-5)."""
    out = []
    for automation in Automation.objects.filter(kind=Automation.Kind.BUILTIN).order_by("name"):
        builtin = _builtin_of(automation)
        if builtin is None:
            continue
        row = {"id": automation.pk, "name": automation.name, "message": ""}
        if not automation.enabled and builtin.enabled:
            off_means = str(_(builtin.off_means)) if builtin.off_means else ""
            out.append({**row, "notice": "off", "message": off_means})
        elif update_available(automation):
            out.append({**row, "notice": "update"})
    return out


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
    depth: int | None = None,
) -> AutomationRun | None:
    """Guardrails and conditions; returns the new run, or ``None`` when it shouldn't run.
    ``depth`` is how many workflows deep it is when another workflow started it."""
    if automation.paused or (not manual and not automation.enabled):
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
        # Schedules pick a bounded set of records once a slot and can't loop, so the hourly
        # limit (a guard against workflows triggering each other) leaves them out.
        hourly = AutomationRun.objects.filter(started_at__gte=current - timedelta(hours=1)).exclude(
            run_key__startswith="schedule:"
        )
        scheduled = run_key.startswith("schedule:")
        if not scheduled and hourly.count() >= int(_setting("automations.max_runs_per_hour")):
            logger.warning("automation.rate_limited", automation_id=str(automation.pk))
            return None
    version = automation.versions.get(version=automation.version)
    depth = _depth_of(event) if depth is None else depth
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
    stop_runs(event)  # before starting new runs, so a run never stops on its own trigger
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


def stop_runs(event: EventEnvelope) -> int:
    """Signal the runs under way for this record whose version stops on this event."""
    from tutortrack.core.workflows import signal

    trigger = registry.trigger(event.type)
    if trigger is None:
        return 0
    runs = AutomationRun.objects.filter(
        status__in=[AutomationRun.Status.RUNNING, AutomationRun.Status.WAITING],
        subject_type=trigger.subject,
        subject_id=str(event.subject["id"]),
        version__stop_when__contains=[event.type],
    ).exclude(workflow_id="")
    count = 0
    for run in runs:
        signal(run.workflow_id, "stop", event.type)
        count += 1
    return count


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


def _authorised(automation: Automation, author: Any, codename: str) -> bool:
    """Whose permission a step runs with: an unedited built-in is TutorTrack's own default,
    so it runs with the platform's authority; anything else with its author's."""
    if automation.kind == Automation.Kind.BUILTIN and not automation.edited:
        return True
    return author is not None and _may(author, codename)


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
            if run.automation.paused:
                AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.PAUSED)
                return {"status": "paused"}
            if run.status == AutomationRun.Status.PAUSED:  # resumed
                AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.RUNNING)
            if step.get("only_if") and not conditions.evaluate(
                step["only_if"], build_context(subject, obj)
            ):
                _record(run, key, "action", AutomationRunStep.Status.SKIPPED,
                        result={"skipped": "only_if"}, error="")  # fmt: skip
                return {"status": "skipped"}
            author = _author(run.automation)
            if action.permission and not _authorised(run.automation, author, action.permission):
                raise BusinessRuleViolation(
                    _("The automation's author no longer has permission for “%(a)s”.")
                    % {"a": action.label}
                )
            ctx = RunContext(
                automation=run.automation, subject=subject, obj=obj,
                context=build_context(subject, obj), key=f"automation:{run.pk}:{key}",
                author=author, run=run,
            )  # fmt: skip
            result = action.run(ctx, step.get("config") or {})
            if isinstance(result.get("skipped"), str):  # "skipped: invoice already paid"
                _record(run, key, "action", AutomationRunStep.Status.SKIPPED, result=result,
                        error="")  # fmt: skip
                return {"status": "skipped", "result": result}
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
    from . import timing

    run, subject, obj = _run_parts(run_id)
    start = datetime.fromisoformat(from_iso)
    anchor = None
    if step.get("until"):
        value = conditions.resolve(build_context(subject, obj), str(step["until"]))
        anchor = _anchor(value)
    calendar = timing.calendar_for(obj, start.date())
    resume = timing.resume_at(start=start, step=step, calendar=calendar, anchor=anchor)
    _record(run, key, "wait", AutomationRunStep.Status.WAITING, resume_at=resume)
    AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.WAITING)
    return resume.isoformat()


def _anchor(value: Any) -> datetime | date | None:
    """A record's date or time; plain dates stay dates (their local midnight)."""
    if isinstance(value, datetime | date):
        return value
    if isinstance(value, str):
        from django.utils.dateparse import parse_date, parse_datetime

        moment = parse_datetime(value)
        if moment is not None:
            return moment
        return parse_date(value)
    return None


def end_wait(run_id: str, key: str) -> None:
    run = AutomationRun.objects.get(pk=run_id)
    _record(run, key, "wait", AutomationRunStep.Status.COMPLETED)
    AutomationRun.objects.filter(pk=run.pk).update(status=AutomationRun.Status.RUNNING)


@transaction.atomic
def finish(run_id: str, status: str, error: str = "", reason: str = "") -> None:
    run = AutomationRun.objects.select_for_update().get(pk=run_id)
    if run.finished_at is not None and run.status == status:
        return
    if status == AutomationRun.Status.STOPPED:
        # The wait it was in never finished: it ended early.
        run.steps.filter(status=AutomationRunStep.Status.WAITING).update(
            status=AutomationRunStep.Status.SKIPPED
        )
        run.stop_reason = reason[:80]
    if status == AutomationRun.Status.FAILED and not error:
        failed = run.steps.filter(status=AutomationRunStep.Status.FAILED).first()
        error = failed.error if failed else ""
    run.status = status
    run.error = error[:2000]
    run.finished_at = now()
    run.save(update_fields=["status", "error", "finished_at", "stop_reason", "updated_at"])
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
            if step.get("only_if") and not conditions.evaluate(step["only_if"], ctx.context):
                out.append({"key": key, "type": "action", "ok": True, "skipped": True,
                            "description": _("Skipped: its “only if” isn't met")})  # fmt: skip
                continue
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
            out.append({"key": key, "type": "wait", "description": describe_wait(step),
                        "ok": True})  # fmt: skip
        elif kind == "branch":
            matched = conditions.evaluate(step.get("if"), ctx.context)
            arm = "then" if matched else "else"
            out.append({"key": key, "type": "branch", "ok": True,
                        "description": _("Condition is %(v)s") % {"v": matched}})  # fmt: skip
            out += _describe_steps(step.get(arm) or [], ctx, f"{key}.{arm}.")
    return out


def describe_wait(step: dict[str, Any]) -> str:
    """A wait in words: "Wait 2 days, at 09:00, on a business day"."""
    if step.get("until"):
        days = float(step.get("offset_days") or 0) + float(step.get("offset_hours") or 0) / 24
        if days == 0:
            text = _("Wait until %(f)s") % {"f": step["until"]}
        elif days < 0:
            text = _("Wait until %(n)s days before %(f)s") % {"n": f"{-days:g}", "f": step["until"]}
        else:
            text = _("Wait until %(n)s days after %(f)s") % {"n": f"{days:g}", "f": step["until"]}
    else:
        hours = float(step.get("hours") or 0) + 24 * float(step.get("days") or 0)
        days = int(hours // 24)
        text = (
            ngettext("Wait %(n)s day", "Wait %(n)s days", days) % {"n": days}
            if hours and hours % 24 == 0
            else _("Wait %(h)s hours") % {"h": f"{hours:g}"}
        )
    parts = [text]
    if step.get("at"):
        parts.append(_("at %(t)s") % {"t": step["at"]})
    if step.get("business_day"):
        parts.append(_("on a business day"))
    if step.get("quiet_hours"):
        parts.append(_("outside quiet hours"))
    return ", ".join(parts)


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
    from .catalogue import SCHEDULE_RECORDS

    config = automation.trigger_config or {}
    picker = SCHEDULE_RECORDS.get(str(config.get("start") or ""))
    if automation.trigger_type == Automation.Trigger.SCHEDULE and picker is not None:
        return picker(on)
    model = subject.model_class()
    qs = model.objects.all()
    if hasattr(model, "archived_at"):
        qs = qs.filter(archived_at__isnull=True)
    if automation.trigger_type == Automation.Trigger.DATE:
        name = str(config["field"])
        targets = [on - timedelta(days=days) for days in _offsets(config)]
        is_datetime = model._meta.get_field(name).get_internal_type() == "DateTimeField"
        lookup = f"{name}__date" if is_datetime else name
        if config.get("anniversary"):
            target = targets[0]
            qs = qs.filter(**{f"{lookup}__month": target.month, f"{lookup}__day": target.day})
        else:
            qs = qs.filter(**{f"{lookup}__in": targets})
    return [str(pk) for pk in qs.values_list("pk", flat=True)[:FAN_OUT_LIMIT]]


def fan_out(automation_id: str, on: date | None = None) -> int:
    """A schedule fired: one run per matching record (ids dedupe per day)."""
    automation = Automation.objects.filter(pk=automation_id, enabled=True).first()
    if automation is None:
        return 0
    started = 0
    if automation.trigger_type == Automation.Trigger.DATE and "minutes" in (
        automation.trigger_config or {}
    ):
        for subject_id, run_key in near_records(automation, now()):
            run = prepare_run(automation, subject_id=subject_id, run_key=run_key)
            if run is not None:
                launch(run)
                started += 1
        return started
    day = on or org_today()
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
    near = automation.trigger_type == Automation.Trigger.DATE and "minutes" in config
    org = Organisation.objects.get(pk=org_id)
    return ensure_schedule(
        process=SCHEDULE_PROCESS,
        workflow=AutomationScheduleWorkflow,
        input=ScheduleInput(organisation_id=str(org_id), automation_id=str(automation_id)),
        cron=[f"*/{NEAR_EVERY_MINUTES} * * * *"] if near else _cron(config),
        timezone=org.timezone,
        parts=(automation_id,),
    )
