"""Pathway templates and runs (E34 FR-34-1, T01).

The run's state lives here. Finishing, skipping or turning down a step moves the run on in
the same transaction: when every step in a stage is done or skipped, the stage completes
(and reaches its gate, if it has one) and the next stage opens. ``PathwayRunWorkflow`` holds
the clock: services signal it after each change, and it calls ``tick`` when a reminder or a
deadline is due, or once a day to re-check open system steps.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils.text import slugify
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.core.workflows import signal, start

from . import events
from .models import PathwayRun, PathwayStep, PathwayTemplate, PathwayTemplateVersion
from .pathway_steps import PARTICIPANT, STAFF, SYSTEM, Completion, step_type

KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_STAGES, MAX_STEPS_PER_STAGE, MAX_STEPS = 10, 20, 60
STAFF_ROLES = ("owner", "admin", "branch_manager", "coordinator", "finance")
CLOSED = (PathwayStep.Status.DONE, PathwayStep.Status.SKIPPED, PathwayStep.Status.REJECTED)
RECHECK = timedelta(days=1)  # how often open system steps are checked again


# --- templates ----------------------------------------------------------------------------------


def _record_type(key: str) -> Any:
    from tutortrack.automations import registry

    subject = registry.subject(key)
    if subject is None:
        raise BusinessRuleViolation(_("Unknown kind of record: %(k)s") % {"k": key})
    return subject


def clean_stages(raw: Any, record_type: str) -> list[dict[str, Any]]:
    """Validate a template's stages and each step's settings (through its step type)."""
    if not isinstance(raw, list) or not raw:
        raise BusinessRuleViolation(_("A pathway needs at least one stage."))
    if len(raw) > MAX_STAGES:
        raise BusinessRuleViolation(
            _("A pathway can have at most %(n)s stages.") % {"n": MAX_STAGES}
        )
    stage_keys: set[str] = set()
    step_keys: set[str] = set()
    stages: list[dict[str, Any]] = []
    for stage in raw:
        if not isinstance(stage, dict):
            raise BusinessRuleViolation(_("Each stage needs a key, a name and its steps."))
        key = str(stage.get("key", ""))
        if not KEY.fullmatch(key) or key in stage_keys:
            raise BusinessRuleViolation(_("Stage keys must be unique, lower-case words."))
        stage_keys.add(key)
        gate = str(stage.get("gate") or "")
        if gate and not KEY.fullmatch(gate):
            raise BusinessRuleViolation(_("A gate's name must be a lower-case word."))
        name = str(stage.get("name") or "").strip()
        if not name or len(name) > 120:
            raise BusinessRuleViolation(_("Give each stage a name (up to 120 characters)."))
        steps = stage.get("steps")
        if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS_PER_STAGE:
            raise BusinessRuleViolation(
                _("Each stage needs between 1 and %(n)s steps.") % {"n": MAX_STEPS_PER_STAGE}
            )
        stages.append(
            {
                "key": key,
                "name": name,
                "gate": gate,
                "steps": [_clean_step(s, step_keys, record_type) for s in steps],
            }
        )
    if len(step_keys) > MAX_STEPS:
        raise BusinessRuleViolation(_("A pathway can have at most %(n)s steps.") % {"n": MAX_STEPS})
    return stages


def _clean_step(raw: Any, keys: set[str], record_type: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BusinessRuleViolation(_("Each step needs a key, a name and a type."))
    key = str(raw.get("key", ""))
    if not KEY.fullmatch(key) or key in keys:
        raise BusinessRuleViolation(_("Step keys must be unique, lower-case words."))
    keys.add(key)
    kind = step_type(str(raw.get("type", "")))
    if kind is None:
        raise BusinessRuleViolation(_("Unknown kind of step: %(t)s") % {"t": raw.get("type")})
    assignee = str(raw.get("assignee") or kind.assignees[0])
    if assignee not in kind.assignees:
        raise BusinessRuleViolation(
            _("A “%(type)s” step can't be done by %(who)s.") % {"type": kind.label, "who": assignee}
        )
    name = str(raw.get("name") or "").strip() or str(kind.label)
    if len(name) > 160:
        raise BusinessRuleViolation(_("Step names can be up to 160 characters."))
    role = str(raw.get("role") or "")
    if role and (assignee != STAFF or role not in STAFF_ROLES):
        raise BusinessRuleViolation(
            _("Only staff steps can name a role, and it must be a staff role.")
        )
    due_days = raw.get("due_days")
    if due_days is not None and (
        assignee == SYSTEM
        or not isinstance(due_days, int)
        or isinstance(due_days, bool)
        or not 1 <= due_days <= 365
    ):
        raise BusinessRuleViolation(_("Due dates are 1 to 365 days after a step opens."))
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise BusinessRuleViolation(_("A step's settings must be an object."))
    return {
        "key": key,
        "type": kind.key,
        "name": name,
        "assignee": assignee,
        "role": role,
        "due_days": due_days,
        "config": kind.clean(config, record_type),
    }


def _unique_key(name: str) -> str:
    base = (slugify(name) or "pathway")[:50]
    key, n = base, 2
    while PathwayTemplate.objects.filter(key=key).exists():
        key, n = f"{base}-{n}", n + 1
    return key


@transaction.atomic
def save_template(
    template: PathwayTemplate | None = None,
    *,
    name: str,
    subject_type: str,
    stages: Any,
    kind: str = PathwayTemplate.Kind.CUSTOM,
    description: str = "",
    active: bool = True,
) -> PathwayTemplate:
    """Create or change a template. Changed stages make a new version; runs already started
    keep theirs (FR-34-1 AC)."""
    _record_type(subject_type)
    if template is not None and template.subject_type != subject_type and template.runs.exists():
        raise BusinessRuleViolation(_("A pathway that has runs can't change its kind of record."))
    cleaned = clean_stages(stages, subject_type)
    if template is None:
        template = PathwayTemplate.objects.create(
            key=_unique_key(name), name=name, description=description, kind=kind,
            subject_type=subject_type, active=active,
        )  # fmt: skip
        audit.record_create(template)
    else:
        template = PathwayTemplate.objects.select_for_update().get(pk=template.pk)
        with audit.track(template):
            template.name, template.description, template.kind = name, description, kind
            template.subject_type, template.active = subject_type, active
            template.save()
    current = template.current_version
    if current is None or current.stages != cleaned:
        version = PathwayTemplateVersion.objects.create(
            template=template,
            version=(current.version + 1) if current else 1,
            stages=cleaned,
        )
        template.current_version = version
        template.edited = bool(template.builtin_key) or template.edited
        template.save(update_fields=["current_version", "edited", "updated_at"])
        if current is not None:
            audit.record(template, "new_version", {"version": [current.version, version.version]})
    return template


# --- runs ---------------------------------------------------------------------------------------


def _signal(run: PathwayRun) -> None:
    signal(run.workflow_id, "changed")


@transaction.atomic
def start_run(
    template: PathwayTemplate, *, record_id: Any, tutor: Any, owner: Any = None
) -> PathwayRun:
    """Start ``template`` for a tutor about one record (a job, an application...)."""
    from .processes import PathwayRunInput, PathwayRunWorkflow

    if not template.active or template.current_version is None:
        raise BusinessRuleViolation(_("This pathway is switched off."))
    if tutor is None:
        raise BusinessRuleViolation(_("Choose the tutor who follows this pathway."))
    record = _record_type(template.subject_type).load(record_id)
    if record is None:
        raise BusinessRuleViolation(_("That record wasn't found."))
    version = template.current_version
    run = PathwayRun(
        template=template,
        version=version,
        subject_type=template.subject_type,
        subject_id=str(record.pk),
        tutor=tutor,
        owner=owner,
        started_at=now(),
    )
    branch_id = getattr(record, "branch_id", None)
    if branch_id:
        run.branch_id = branch_id
    run.save()
    position = 0
    for stage in version.stages:
        for step in stage["steps"]:
            PathwayStep.objects.create(
                run=run, stage=stage["key"], key=step["key"], position=position,
                type=step["type"], name=step["name"], assignee=step["assignee"],
                role=step.get("role", ""), due_days=step.get("due_days"), config=step["config"],
            )  # fmt: skip
            position += 1
    audit.record_create(run)
    publish(
        events.PathwayStarted(
            subject_id=run.pk, template_key=template.key, kind=template.kind,
            record_type=run.subject_type, record_id=run.subject_id, tutor_id=str(tutor.pk),
        ),
        branch_id=run.branch_id,
    )  # fmt: skip
    _advance(run)
    start(
        PathwayRunWorkflow,
        PathwayRunInput(organisation_id=str(require_organisation_id()), run_id=str(run.pk)),
        id=run.workflow_id,
        subject=(run.subject_type, run.subject_id),
        branch_id=run.branch_id,
    )
    return run


def _locked(run: PathwayRun) -> PathwayRun:
    return (
        PathwayRun.objects.select_for_update().select_related("version", "template").get(pk=run.pk)
    )


def _stage_meta(run: PathwayRun) -> list[dict[str, Any]]:
    return [
        {"key": s["key"], "name": s["name"], "gate": s.get("gate", "")} for s in run.version.stages
    ]


def _advance(run: PathwayRun) -> None:
    """Move ``run`` on as far as it can go: complete finished stages, open the next one and
    check its system steps. Call with the run locked, inside the transaction."""
    stages = _stage_meta(run)
    order = [s["key"] for s in stages]
    while run.status == PathwayRun.Status.RUNNING:
        steps = list(run.steps.order_by("position"))
        current = [s for s in steps if s.stage == run.stage]
        if not run.stage:
            _open_stage(run, order[0], steps)
            continue
        if all(s.status in (PathwayStep.Status.DONE, PathwayStep.Status.SKIPPED) for s in current):
            meta = next(s for s in stages if s["key"] == run.stage)
            if meta["gate"]:
                run.gates = [*run.gates, meta["gate"]]
            publish(
                events.PathwayStageCompleted(
                    subject_id=run.pk, stage=run.stage, gate=meta["gate"],
                    record_type=run.subject_type, record_id=run.subject_id,
                ),
                branch_id=run.branch_id,
            )  # fmt: skip
            index = order.index(run.stage)
            if index + 1 == len(order):
                _finish(run, PathwayRun.Status.COMPLETED)
                break
            _open_stage(run, order[index + 1], steps)
            continue
        if not _run_checks(run, current):
            break


def _open_stage(run: PathwayRun, stage: str, steps: list[PathwayStep]) -> None:
    from . import notifications

    moment = now()
    run.stage = stage
    run.save(update_fields=["stage", "gates", "updated_at"])
    opened: list[PathwayStep] = []
    for step in steps:
        if step.stage != stage or step.status != PathwayStep.Status.WAITING:
            continue
        step.status = PathwayStep.Status.OPEN
        step.opened_at = moment
        step.due_at = moment + timedelta(days=step.due_days) if step.due_days else None
        step.save(update_fields=["status", "opened_at", "due_at", "updated_at"])
        opened.append(step)
    if any(s.assignee == PARTICIPANT for s in opened):
        notifications.tasks_opened(run, stage)
    for step in opened:
        if step.assignee == STAFF:
            notifications.staff_attention(step, "open")


def _run_checks(run: PathwayRun, steps: list[PathwayStep]) -> bool:
    """Check open system steps; True if any finished."""
    changed = False
    for step in steps:
        if step.status != PathwayStep.Status.OPEN or step.assignee != SYSTEM:
            continue
        kind = step_type(step.type)
        if kind is not None and kind.check is not None and kind.check(step):
            _close(step, PathwayStep.Status.DONE, user=None, result={"checked": True})
            changed = True
    return changed


def _close(
    step: PathwayStep, status: str, *, user: Any, result: dict[str, Any] | None = None,
    reason: str = "",
) -> None:  # fmt: skip
    step.status = status
    step.completed_at = now()
    step.completed_by = user
    if result is not None:
        step.result = result
    step.reason = reason
    step.save(
        update_fields=["status", "completed_at", "completed_by", "result", "reason", "updated_at"]
    )
    audit.record(step.run, f"step_{status}", {"step": [None, step.key]})
    if status in (PathwayStep.Status.DONE, PathwayStep.Status.SKIPPED):
        publish(
            events.PathwayStepCompleted(
                subject_id=step.run_id, step=step.key, step_type=step.type, stage=step.stage,
                outcome=status,
            ),
            branch_id=step.run.branch_id,
        )  # fmt: skip


def _finish(run: PathwayRun, status: str, reason: str = "") -> None:
    run.status = status
    run.finished_at = now()
    run.reason = reason
    run.save(update_fields=["status", "finished_at", "reason", "gates", "stage", "updated_at"])
    audit.record(run, "finish", {"status": [PathwayRun.Status.RUNNING, status]})
    publish(
        events.PathwayCompleted(
            subject_id=run.pk, template_key=run.template.key, kind=run.template.kind,
            outcome=status, record_type=run.subject_type, record_id=run.subject_id,
            tutor_id=str(run.tutor_id) if run.tutor_id else None,
        ),
        branch_id=run.branch_id,
    )  # fmt: skip


# --- who may do what ----------------------------------------------------------------------------


def is_participant(run: PathwayRun, user: Any) -> bool:
    tutor = run.tutor
    membership = getattr(tutor, "membership", None) if tutor else None
    return bool(
        membership is not None
        and membership.status == "active"
        and membership.user_id == getattr(user, "pk", None)
    )


def _may_do_staff_step(step: PathwayStep, user: Any) -> bool:
    from tutortrack.identity.selectors import membership_for

    if not has_perm(user, "pathway.step.complete"):
        return False
    if not step.role or getattr(user, "is_superuser", False):
        return True
    membership = membership_for(user, step.organisation_id)
    return membership is not None and membership.role in (step.role, "owner", "admin")


def _step(step: PathwayStep) -> tuple[PathwayRun, PathwayStep]:
    run = _locked(step.run)
    step = PathwayStep.objects.select_related("run__tutor__membership").get(pk=step.pk)
    if run.finished:
        raise BusinessRuleViolation(_("This pathway has finished."))
    return run, step


# --- doing steps --------------------------------------------------------------------------------


@transaction.atomic
def complete_step(
    step: PathwayStep, *, user: Any, payload: dict[str, Any] | None = None
) -> PathwayStep:
    """The person a step names finishes it. A tutor's answer to a step that staff check
    waits for review; staff finishing a step under review accept what the tutor sent."""
    from . import notifications

    run, step = _step(step)
    payload = payload or {}
    kind = step_type(step.type)
    if kind is None:
        raise BusinessRuleViolation(_("This kind of step is no longer available."))
    if step.status == PathwayStep.Status.REVIEW:
        if not has_perm(user, "pathway.step.complete"):
            raise PermissionDenied(_("Only staff can accept what was sent."))
        _close(step, PathwayStep.Status.DONE, user=user)
    elif step.status != PathwayStep.Status.OPEN:
        raise BusinessRuleViolation(_("This step isn't open."))
    elif step.assignee == PARTICIPANT:
        if not is_participant(run, user):
            raise PermissionDenied(_("Only the tutor following this pathway can do this step."))
        result = kind.complete(Completion(step, user, payload)) if kind.complete else {}
        if kind.review(step.config):
            step.status = PathwayStep.Status.REVIEW
            step.submitted_at = now()
            step.result = result
            step.reason = ""
            step.save(update_fields=["status", "submitted_at", "result", "reason", "updated_at"])
            audit.record(run, "step_submitted", {"step": [None, step.key]})
            notifications.staff_attention(step, "review")
        else:
            _close(step, PathwayStep.Status.DONE, user=user, result=result)
    elif step.assignee == STAFF:
        if not _may_do_staff_step(step, user):
            raise PermissionDenied(_("This step is for staff with the right role."))
        result = kind.complete(Completion(step, user, payload)) if kind.complete else {}
        _close(step, PathwayStep.Status.DONE, user=user, result=result)
    else:
        raise BusinessRuleViolation(_("Nobody can finish this step by hand."))
    _advance(run)
    _signal(run)
    step.refresh_from_db()
    return step


def _reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise BusinessRuleViolation(_("Say why."))
    return reason[:2000]


@transaction.atomic
def skip_step(step: PathwayStep, *, user: Any, reason: str) -> PathwayStep:
    """Staff skip a step that hasn't finished, with a reason (it counts as finished)."""
    run, step = _step(step)
    if not has_perm(user, "pathway.step.complete"):
        raise PermissionDenied(_("Only staff can skip steps."))
    if step.status in CLOSED:
        raise BusinessRuleViolation(_("This step has already finished."))
    _close(step, PathwayStep.Status.SKIPPED, user=user, reason=_reason(reason))
    _advance(run)
    _signal(run)
    step.refresh_from_db()
    return step


@transaction.atomic
def reject_step(step: PathwayStep, *, user: Any, reason: str) -> PathwayStep:
    """Staff turn a step down. What a tutor sent for review goes back to them to do again;
    a staff review that says no ends the run as turned down."""
    from . import notifications

    run, step = _step(step)
    reason = _reason(reason)
    if step.status == PathwayStep.Status.REVIEW:
        if not has_perm(user, "pathway.step.complete"):
            raise PermissionDenied(_("Only staff can send a step back."))
        step.status = PathwayStep.Status.OPEN
        step.submitted_at = None
        step.result = {}
        step.reason = reason
        step.save(update_fields=["status", "submitted_at", "result", "reason", "updated_at"])
        audit.record(run, "step_returned", {"step": [None, step.key]})
        notifications.task_returned(step)
    elif step.status == PathwayStep.Status.OPEN and step.type == "staff_review":
        if not _may_do_staff_step(step, user):
            raise PermissionDenied(_("This step is for staff with the right role."))
        _close(step, PathwayStep.Status.REJECTED, user=user, result={"decision": "rejected"},
               reason=reason)  # fmt: skip
        _finish(run, PathwayRun.Status.REJECTED, reason)
    else:
        raise BusinessRuleViolation(
            _("Only a staff review, or something sent for review, can be turned down.")
        )
    _signal(run)
    step.refresh_from_db()
    return step


@transaction.atomic
def remind_step(step: PathwayStep, *, user: Any) -> PathwayStep:
    """Staff nudge whoever has to do an open step now."""
    from . import notifications

    run, step = _step(step)
    if step.status not in (PathwayStep.Status.OPEN, PathwayStep.Status.REVIEW):
        raise BusinessRuleViolation(_("This step isn't waiting for anyone."))
    if step.status == PathwayStep.Status.REVIEW or step.assignee == STAFF:
        notifications.staff_attention(step, "nudge", unique=now().isoformat())
    elif step.assignee == PARTICIPANT:
        notifications.task_reminder(step, "nudge", unique=now().isoformat())
    else:
        raise BusinessRuleViolation(_("TutorTrack does this step itself."))
    audit.record(run, "step_reminded", {"step": [None, step.key]})
    return step


@transaction.atomic
def cancel_run(run: PathwayRun, *, user: Any, reason: str = "") -> PathwayRun:
    run = _locked(run)
    if run.finished:
        raise BusinessRuleViolation(_("This pathway has finished."))
    run.status = PathwayRun.Status.CANCELLED
    run.finished_at = now()
    run.reason = (reason or "").strip()[:2000]
    run.save(update_fields=["status", "finished_at", "reason", "updated_at"])
    audit.record(run, "cancel", {"status": [PathwayRun.Status.RUNNING, run.status]})
    publish(
        events.PathwayCancelled(
            subject_id=run.pk, template_key=run.template.key, record_type=run.subject_type,
            record_id=run.subject_id,
        ),
        branch_id=run.branch_id,
    )  # fmt: skip
    _signal(run)
    return run


# --- the clock (called by PathwayRunWorkflow) ---------------------------------------------------


def _reminder_days() -> int:
    from tutortrack.tenancy.settings_service import get_setting

    return int(get_setting("pathways.reminder_days") or 0)


def _remind_at(step: PathwayStep, days: int) -> datetime | None:
    if not days or step.due_at is None or step.opened_at is None:
        return None
    moment = step.due_at - timedelta(days=days)
    return moment if moment > step.opened_at else None


@transaction.atomic
def tick(run_id: str, *, at: datetime | None = None) -> dict[str, Any]:
    """Send reminders and overdue notices that are due, re-check system steps, and say when
    the run next needs waking (``wake_at``, or None to wait for a change)."""
    from . import notifications

    run = PathwayRun.objects.select_for_update().select_related("version", "template").filter(
        pk=run_id
    ).first()  # fmt: skip
    if run is None:
        return {"finished": True, "status": "missing", "stage": "", "wake_at": None}
    moment = at or now()
    days = _reminder_days()
    if not run.finished:
        for step in run.steps.filter(status=PathwayStep.Status.OPEN, due_at__isnull=False):
            remind_at = _remind_at(step, days)
            if step.due_at is not None and step.due_at <= moment and step.overdue_at is None:
                step.overdue_at = moment
                step.reminded_at = step.reminded_at or moment
                step.save(update_fields=["overdue_at", "reminded_at", "updated_at"])
                _due_notice(step, "overdue", notifications)
            elif remind_at is not None and remind_at <= moment and step.reminded_at is None:
                step.reminded_at = moment
                step.save(update_fields=["reminded_at", "updated_at"])
                _due_notice(step, "due_soon", notifications)
        _advance(run)
    return {
        "finished": run.finished,
        "status": run.status,
        "stage": run.stage,
        "wake_at": None if run.finished else _next_wake(run, moment, days),
    }


def _due_notice(step: PathwayStep, kind: str, notifications: Any) -> None:
    if step.assignee == PARTICIPANT:
        notifications.task_reminder(step, kind)
    if step.assignee == STAFF or kind == "overdue":
        notifications.staff_attention(step, kind)


def _next_wake(run: PathwayRun, moment: datetime, days: int) -> str | None:
    times: list[datetime] = []
    for step in run.steps.filter(status=PathwayStep.Status.OPEN):
        if step.assignee == SYSTEM:
            times.append(moment + RECHECK)
            continue
        remind_at = _remind_at(step, days)
        if remind_at is not None and step.reminded_at is None and remind_at > moment:
            times.append(remind_at)
        if step.due_at is not None and step.overdue_at is None:
            times.append(max(step.due_at, moment))
    return min(times).isoformat() if times else None
