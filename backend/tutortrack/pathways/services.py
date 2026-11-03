"""Pathway templates and runs (E34 FR-34-1, T01; ready-made pathways and automatic starts T02).

The run's state lives here. Finishing, skipping or turning down a step moves the run on in
the same transaction: when every step in a stage is done or skipped, the stage completes
(and reaches its gate, if it has one) and the next stage opens. ``PathwayRunWorkflow`` holds
the clock: services signal it after each change, and it calls ``tick`` when a reminder or a
deadline is due, or once a day to re-check open steps that TutorTrack checks.

What a pathway does to its record lives in ``_outcome``: a Join run marks the tutor ready on
the job at its ``ready`` gate (or when it completes), and an Apply run that completes chooses
the applicant on the job board (turned down: not chosen). Pathways start on their own only
when the business has picked a default for the kind (``pathways.default_templates``) or the
job or posting names one (``start_for``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

import structlog
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permissions import has_perm
from tutortrack.core.time import now
from tutortrack.core.workflows import signal, start

from . import builtin_pathways, events
from .models import PathwayRun, PathwayStep, PathwayTemplate, PathwayTemplateVersion
from .pathway_steps import FAMILY, PARTICIPANT, STAFF, SYSTEM, Completion, step_type

KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_STAGES, MAX_STEPS_PER_STAGE, MAX_STEPS = 10, 20, 60
STAFF_ROLES = ("owner", "admin", "branch_manager", "coordinator", "finance")
CLOSED = (PathwayStep.Status.DONE, PathwayStep.Status.SKIPPED, PathwayStep.Status.REJECTED)
RECHECK = timedelta(days=1)  # how often open system steps are checked again
JOB_KINDS = (PathwayTemplate.Kind.APPLY, PathwayTemplate.Kind.JOIN, PathwayTemplate.Kind.FINISH)

logger = structlog.get_logger(__name__)


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
    builtin: builtin_pathways.BuiltinPathway | None = None,
) -> PathwayTemplate:
    """Create or change a template. Changed stages make a new version; runs already started
    keep theirs (FR-34-1 AC). ``builtin`` installs, upgrades or resets a ready-made pathway
    to its default (not counted as an edit)."""
    _record_type(subject_type)
    if template is not None and template.subject_type != subject_type and template.runs.exists():
        raise BusinessRuleViolation(_("A pathway that has runs can't change its kind of record."))
    cleaned = clean_stages(stages, subject_type)
    if template is None:
        template = PathwayTemplate.objects.create(
            key=_unique_key(builtin.key if builtin else name), name=name,
            description=description, kind=kind, subject_type=subject_type, active=active,
            builtin_key=builtin.key if builtin else "",
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
        template.edited = builtin is None and (bool(template.builtin_key) or template.edited)
        template.save(update_fields=["current_version", "edited", "updated_at"])
        if current is not None:
            audit.record(template, "new_version", {"version": [current.version, version.version]})
    if builtin is not None and (template.edited or template.builtin_version != builtin.version):
        template.edited, template.builtin_version = False, builtin.version
        template.save(update_fields=["edited", "builtin_version", "updated_at"])
    return template


# --- ready-made pathways (T02) ------------------------------------------------------------------

TEXT_KEYS = frozenset({"name", "title", "text", "label", "question", "help", "instructions"})


def _translated(value: Any) -> Any:
    """A built-in's stages with their ``gettext_noop`` texts translated."""
    if isinstance(value, list):
        return [_translated(v) for v in value]
    if isinstance(value, dict):
        return {
            k: str(_(v)) if k in TEXT_KEYS and isinstance(v, str) and v else _translated(v)
            for k, v in value.items()
        }
    return value


def _save_builtin(
    template: PathwayTemplate | None, builtin: builtin_pathways.BuiltinPathway
) -> PathwayTemplate:
    definition = builtin.definition()
    return save_template(
        template,
        name=template.name if template else str(_(builtin.name)),
        description=template.description if template else str(_(builtin.description)),
        subject_type=definition["record_type"],
        stages=_translated(definition["stages"]),
        kind=builtin.kind,
        active=template.active if template else True,
        builtin=builtin,
    )


def install_builtins() -> dict[str, int]:
    """Install the ready-made pathways the organisation doesn't have yet and move unedited
    ones to a newer default; edited ones are left alone (``update_available``). Idempotent:
    runs at sign-up and on every deploy (``sync_builtin_pathways``)."""
    existing = {
        t.builtin_key: t
        for t in PathwayTemplate.objects.exclude(builtin_key="").select_related("current_version")
    }
    counts = {"installed": 0, "upgraded": 0}
    for builtin in builtin_pathways.all_builtins():
        found = existing.get(builtin.key)
        try:
            with transaction.atomic():
                if found is None:
                    _save_builtin(None, builtin)
                    counts["installed"] += 1
                elif not found.edited and (found.builtin_version or 0) < builtin.version:
                    _save_builtin(found, builtin)
                    counts["upgraded"] += 1
        except (BusinessRuleViolation, IntegrityError) as exc:  # a broken default, or a race
            logger.error("pathways.builtin_install_failed", key=builtin.key, error=str(exc))
    return counts


def update_available(template: PathwayTemplate) -> bool:
    """An edited ready-made pathway whose default TutorTrack has improved since."""
    builtin = builtin_pathways.builtin(template.builtin_key) if template.builtin_key else None
    return bool(builtin and template.edited and (template.builtin_version or 0) < builtin.version)


@transaction.atomic
def reset_to_default(template: PathwayTemplate) -> PathwayTemplate:
    """Put a ready-made pathway back to TutorTrack's current default; runs under way keep
    their version."""
    builtin = builtin_pathways.builtin(template.builtin_key) if template.builtin_key else None
    if not template.builtin_key:
        raise BusinessRuleViolation(_("Only ready-made pathways have a default to reset to."))
    if builtin is None:
        raise BusinessRuleViolation(_("TutorTrack no longer ships this pathway."))
    template = _save_builtin(template, builtin)
    version = template.current_version.version if template.current_version else None
    audit.record(template, "reset", {"version": [None, version]})
    return template


# --- which pathway starts on its own (T02) ------------------------------------------------------


def _defaults() -> dict[str, str]:
    from tutortrack.tenancy.settings_service import get_setting

    return dict(get_setting("pathways.default_templates") or {})


def used_by_default(template: PathwayTemplate) -> bool:
    return _defaults().get(template.kind) == template.key


@transaction.atomic
def set_used_by_default(template: PathwayTemplate, used: bool) -> None:
    """Make ``template`` the one that starts on its own for its kind (or stop that)."""
    from tutortrack.tenancy.settings_service import update_settings

    if template.kind not in JOB_KINDS:
        raise BusinessRuleViolation(
            _("Only Apply, Join and Finish pathways start on their own; start others by hand.")
        )
    if used and not template.active:
        raise BusinessRuleViolation(_("Switch the pathway on first."))
    defaults = _defaults()
    if used:
        defaults[template.kind] = template.key
    elif defaults.get(template.kind) == template.key:
        defaults.pop(template.kind)
    else:
        return
    update_settings("pathways", {"pathways.default_templates": defaults})
    audit.record(template, "default", {"used_by_default": [not used, used]})


def template_for(kind: str, *, job: Any = None, posting: Any = None) -> PathwayTemplate | None:
    """The pathway of ``kind`` that starts for a job (or job posting): the one the posting
    or job names, else the business default, else none."""
    chosen = None
    if kind == PathwayTemplate.Kind.APPLY and posting is not None:
        chosen = posting.apply_template_id
    elif kind == PathwayTemplate.Kind.JOIN and job is not None:
        chosen = job.join_template_id
    templates = PathwayTemplate.objects.filter(
        kind=kind, active=True, current_version__isnull=False
    )
    if chosen:
        found = templates.filter(pk=chosen).first()
        if found is not None:
            return found
    key = _defaults().get(kind)
    return templates.filter(key=key).first() if key else None


def _running(kind: str, job_id: Any, tutor_id: Any) -> Any:
    return PathwayRun.objects.filter(
        template__kind=kind, subject_type="job", subject_id=str(job_id), tutor_id=tutor_id,
        status=PathwayRun.Status.RUNNING,
    )  # fmt: skip


def start_for(
    kind: str, *, job_id: Any, tutor_id: Any, posting_id: Any = None
) -> PathwayRun | None:
    """Start the job's pathway of ``kind`` for a tutor, if one applies and none is under way
    (event handlers call this, so it is safe to call twice)."""
    from tutortrack.jobs.models import Job
    from tutortrack.people.models import TutorProfile

    job = Job.objects.filter(pk=job_id).first()
    tutor = TutorProfile.objects.filter(pk=tutor_id).first()
    if job is None or tutor is None or _running(kind, job.pk, tutor.pk).exists():
        return None
    posting = None
    if posting_id:
        from tutortrack.matching.models import JobPosting

        posting = JobPosting.objects.filter(pk=posting_id).first()
    template = template_for(kind, job=job, posting=posting)
    if template is None or template.subject_type != "job":
        return None
    with transaction.atomic():
        if kind == PathwayTemplate.Kind.JOIN:
            from tutortrack.jobs import services as jobs

            jobs.set_join_status(job, tutor, "joining")
        return start_run(template, record_id=job.pk, tutor=tutor, owner=job.account_manager)


def cancel_for(kinds: tuple[str, ...], *, job_id: Any, tutor_id: Any = None, reason: str) -> int:
    """Cancel the job's running pathways of ``kinds`` (for one tutor, or all)."""
    runs = PathwayRun.objects.filter(
        template__kind__in=kinds, subject_type="job", subject_id=str(job_id),
        status=PathwayRun.Status.RUNNING,
    )  # fmt: skip
    if tutor_id is not None:
        runs = runs.filter(tutor_id=tutor_id)
    count = 0
    for run in runs:
        cancel_run(run, user=None, reason=reason)
        count += 1
    return count


def recheck(runs: Any) -> int:
    """Check the open steps of running pathways again (an event that may finish one came in);
    returns how many pathways moved on."""
    moved = 0
    for run_id in list(runs.filter(status=PathwayRun.Status.RUNNING).values_list("pk", flat=True)):
        with transaction.atomic():
            run = (
                PathwayRun.objects.select_for_update()
                .select_related("version", "template")
                .filter(pk=run_id, status=PathwayRun.Status.RUNNING)
                .first()
            )
            if run is None:
                continue
            before = (run.stage, run.status, run.steps.filter(status__in=CLOSED).count())
            _advance(run)
            if before != (run.stage, run.status, run.steps.filter(status__in=CLOSED).count()):
                moved += 1
                _signal(run)
    return moved


def _outcome(run: PathwayRun, what: str, gate: str = "") -> None:
    """What a pathway about a job does to it: Join marks the tutor ready (at its ``ready``
    gate or when it completes; cancelling it stops holding lessons back), and Apply chooses
    the applicant when it completes or turns them down when it is turned down."""
    if run.subject_type != "job" or run.tutor_id is None:
        return
    kind = run.template.kind
    if kind == PathwayTemplate.Kind.JOIN:
        from tutortrack.jobs import services as jobs

        if (what == "gate" and gate == "ready") or what == PathwayRun.Status.COMPLETED:
            jobs.set_join_status(run.subject_id, run.tutor_id, "ready")
        elif what == PathwayRun.Status.CANCELLED:
            jobs.set_join_status(run.subject_id, run.tutor_id, None, only_if="joining")
    elif kind == PathwayTemplate.Kind.APPLY and what in (
        PathwayRun.Status.COMPLETED, PathwayRun.Status.REJECTED,
    ):  # fmt: skip
        from tutortrack.matching import selectors as matching_selectors
        from tutortrack.matching import services as matching

        application = matching_selectors.open_application(run.subject_id, run.tutor_id)
        if application is None:
            return
        try:
            with transaction.atomic():
                if what == PathwayRun.Status.COMPLETED:
                    matching.select_applicant(application)
                else:
                    matching.reject_applicant(application)
        except BusinessRuleViolation as exc:  # the posting closed, the tutor can't take it...
            logger.info("pathways.apply_outcome_skipped", run=str(run.pk), error=str(exc))


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
                _outcome(run, "gate", meta["gate"])
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
        if step.assignee in (STAFF, FAMILY):  # staff share the shortlist for family steps
            notifications.staff_attention(step, "open")


def _run_checks(run: PathwayRun, steps: list[PathwayStep]) -> bool:
    """Check the open steps TutorTrack can check; True if any finished (or the pathway was
    turned down)."""
    for step in steps:
        if step.status not in (PathwayStep.Status.OPEN, PathwayStep.Status.REVIEW):
            continue
        kind = step_type(step.type)
        if kind is None or kind.check is None:
            continue
        outcome = kind.check(step)
        if outcome == "rejected":
            reason = _("Turned down: %(step)s") % {"step": step.name}
            _close(step, PathwayStep.Status.REJECTED, user=None, reason=reason)
            _finish(run, PathwayRun.Status.REJECTED, reason)
            return True
        if outcome is True:
            _close(step, PathwayStep.Status.DONE, user=None,
                   result={**step.result, "checked": True})  # fmt: skip
            return True
    return False


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
    _outcome(run, status)
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
        if kind.accept is not None:
            kind.accept(step, user)
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
        kind = step_type(step.type)
        if kind is not None and kind.send_back is not None:
            kind.send_back(step, user, reason)
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
    _outcome(run, PathwayRun.Status.CANCELLED)
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


def provision_call(step_id: Any) -> str:
    """Create the online meeting for a booked call (after the booking commits). Idempotent:
    a link already set is kept."""
    from tutortrack.calendar_sync import meetings
    from tutortrack.tenancy.models import Organisation

    from .pathway_steps import call_host

    step = PathwayStep.objects.select_related("run__tutor", "run__owner").filter(pk=step_id).first()
    if step is None or step.type != "book_call" or not step.result.get("start"):
        return "skipped"
    if step.result.get("meeting_url"):
        return "kept"
    host = call_host(step)
    if host is None:
        return "none"
    start_at = datetime.fromisoformat(step.result["start"])
    who = step.run.tutor.full_name if step.run.tutor else ""
    provider, info = meetings.create_standalone_meeting(
        key=f"pathway-call-{step.pk}",
        topic=f"{step.config['title']}: {who}" if who else step.config["title"],
        start=start_at,
        end=start_at + timedelta(minutes=int(step.result.get("minutes") or 30)),
        timezone=Organisation.objects.get(pk=step.organisation_id).timezone,
        host_user_id=host.pk,
        host_name=host.get_full_name() or host.email,
    )
    if info is None:
        return "none"
    with transaction.atomic():
        step = PathwayStep.objects.select_for_update().get(pk=step.pk)
        if step.result.get("meeting_url"):
            return "kept"
        step.result = {
            **step.result, "meeting_url": info.join_url[:1000],
            "host_url": (info.host_url or info.join_url)[:1000], "provider": provider,
        }  # fmt: skip
        step.save(update_fields=["result", "updated_at"])
    return "created"


def _due_notice(step: PathwayStep, kind: str, notifications: Any) -> None:
    if step.assignee == PARTICIPANT:
        notifications.task_reminder(step, kind)
    if step.assignee == STAFF or kind == "overdue":
        notifications.staff_attention(step, kind)


def _next_wake(run: PathwayRun, moment: datetime, days: int) -> str | None:
    times: list[datetime] = []
    for step in run.steps.filter(status__in=(PathwayStep.Status.OPEN, PathwayStep.Status.REVIEW)):
        kind = step_type(step.type)
        if kind is not None and kind.check is not None:
            times.append(moment + RECHECK)
        if step.assignee == SYSTEM or step.status == PathwayStep.Status.REVIEW:
            continue
        remind_at = _remind_at(step, days)
        if remind_at is not None and step.reminded_at is None and remind_at > moment:
            times.append(remind_at)
        if step.due_at is not None and step.overdue_at is None:
            times.append(max(step.due_at, moment))
    return min(times).isoformat() if times else None
