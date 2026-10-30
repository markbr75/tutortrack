"""Pathway messages on the E13 registry (E34 FR-34-1).

* ``pathway_tasks_opened``: the tutor has new steps to do (one message per stage).
* ``pathway_task_reminder``: a step is due soon, overdue, or staff nudged the tutor.
* ``pathway_task_returned``: staff sent a step back with a reason.
* ``staff_pathway_attention``: a staff step opened, something waits for review, a step is
  overdue, or staff were nudged (to holders of ``pathway.step.complete``).
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.comms import catalogue
from tutortrack.comms.catalogue import SAMPLE_BASE, organisation, tenant_link, tutor_recipient
from tutortrack.comms.defaults import DEFAULTS, SIGN
from tutortrack.comms.registry import Delivery, NotificationType, register

TASKS_LINK = "/portal/tutor/tasks"


def _run_link(run_id: Any) -> str:
    return f"/pathways/runs/{run_id}"


def _notify(type_key: str, subject: Any, key: str) -> None:
    from tutortrack.comms.services import notify_on_commit

    notify_on_commit(type_key, subject, key=key)


# --- senders (called by services) ---------------------------------------------------------------


def tasks_opened(run: Any, stage: str) -> None:
    _notify("pathway_tasks_opened", (str(run.pk), stage), key=f"pathway:{run.pk}:{stage}:opened")


def task_reminder(step: Any, kind: str, unique: str = "") -> None:
    _notify(
        "pathway_task_reminder", (str(step.pk), kind), key=f"pathway-step:{step.pk}:{kind}:{unique}"
    )


def task_returned(step: Any) -> None:
    from tutortrack.core.time import now

    _notify(
        "pathway_task_returned",
        str(step.pk),
        key=f"pathway-step:{step.pk}:returned:{now().isoformat()}",
    )


def staff_attention(step: Any, kind: str, unique: str = "") -> None:
    run = step.run
    who = run.tutor.full_name if run.tutor else _("A tutor")
    title = {
        "open": _("Pathway step for staff: %(step)s"),
        "review": _("Check what was sent: %(step)s"),
        "overdue": _("Pathway step overdue: %(step)s"),
        "due_soon": _("Pathway step due soon: %(step)s"),
        "nudge": _("Reminder: %(step)s"),
    }[kind] % {"step": step.name}
    body = _("%(who)s · %(pathway)s") % {"who": who, "pathway": run.template.name}
    _notify(
        "staff_pathway_attention",
        (title, body, _run_link(run.pk)),
        key=f"pathway-step:{step.pk}:staff:{kind}:{unique}",
    )


# --- resolvers ----------------------------------------------------------------------------------


def _task_base(r: Any, task: dict[str, Any]) -> dict[str, Any]:
    return {
        "organisation": organisation(),
        "recipient": {"name": r.name, "first_name": r.first_name},
        "task": {**task, "link": tenant_link(TASKS_LINK)},
    }


def _opened(payload: Any) -> list[Delivery]:
    from .models import PathwayRun, PathwayStep

    run_id, stage = payload
    run = (
        PathwayRun.objects.select_related("tutor__membership__user", "template", "version")
        .filter(pk=run_id, status=PathwayRun.Status.RUNNING)
        .first()
    )
    if run is None or run.tutor is None:
        return []
    steps = list(
        run.steps.filter(
            stage=stage, assignee="participant", status=PathwayStep.Status.OPEN
        ).order_by("position")
    )
    if not steps:
        return []
    stage_name = next((s["name"] for s in run.version.stages if s["key"] == stage), stage)
    due = [s.due_at for s in steps if s.due_at]
    r = tutor_recipient(run.tutor)
    task = {
        "pathway": run.template.name,
        "stage": stage_name,
        "count": len(steps),
        "steps": ", ".join(s.name for s in steps),
        "due": min(due).date().isoformat() if due else "",
    }
    return [Delivery(r, _task_base(r, task))]


def _step(step_id: str) -> Any:
    from .models import PathwayRun, PathwayStep

    return (
        PathwayStep.objects.select_related("run__tutor__membership__user", "run__template")
        .filter(pk=step_id, run__status=PathwayRun.Status.RUNNING)
        .first()
    )


def _reminder(payload: Any) -> list[Delivery]:
    step_id, kind = payload
    step = _step(step_id)
    if step is None or step.run.tutor is None or step.status != "open":
        return []
    r = tutor_recipient(step.run.tutor)
    task = {
        "name": step.name,
        "pathway": step.run.template.name,
        "due": step.due_at.date().isoformat() if step.due_at else "",
        "overdue": kind == "overdue",
    }
    return [Delivery(r, _task_base(r, task))]


def _returned(step_id: str) -> list[Delivery]:
    step = _step(step_id)
    if step is None or step.run.tutor is None or step.status != "open":
        return []
    r = tutor_recipient(step.run.tutor)
    task = {"name": step.name, "pathway": step.run.template.name, "reason": step.reason}
    return [Delivery(r, _task_base(r, task))]


SAMPLE_TASK = {
    **SAMPLE_BASE,
    "task": {
        "pathway": "Join a job",
        "stage": "Before your first lesson",
        "count": 2,
        "steps": "Sign the job agreement, Read the safeguarding policy",
        "name": "Sign the job agreement",
        "due": "2026-11-06",
        "overdue": False,
        "reason": "The photo of your certificate is blurred.",
        "link": "https://example.com/portal/tutor/tasks",
    },
}

for _key, _label, _resolve, _vars in (
    ("pathway_tasks_opened", gettext_lazy("New pathway steps to do"), _opened,
     ("task.pathway", "task.stage", "task.count", "task.steps", "task.due", "task.link")),
    ("pathway_task_reminder", gettext_lazy("Pathway step reminder"), _reminder,
     ("task.name", "task.pathway", "task.due", "task.overdue", "task.link")),
    ("pathway_task_returned", gettext_lazy("Pathway step sent back"), _returned,
     ("task.name", "task.pathway", "task.reason", "task.link")),
):  # fmt: skip
    register(
        NotificationType(
            key=_key,
            label=str(_label),
            category="account",
            audience="tutor",
            channels=("email", "in_app"),
            default_channels=("email", "in_app"),
            resolve=_resolve,
            load=lambda pk: None,
            related_type="",
            variables=_vars,
            sample=SAMPLE_TASK,
            link=lambda payload: TASKS_LINK,
        )
    )

register(
    NotificationType(
        key="staff_pathway_attention",
        label=str(gettext_lazy("A pathway needs staff")),
        category="staff",
        audience="staff",
        channels=("in_app", "email"),
        default_channels=("in_app",),
        resolve=catalogue._alert("pathway.step.complete"),
        load=lambda pk: None,
        related_type="",
        variables=("alert.title", "alert.body", "alert.link"),
        sample=catalogue.SAMPLE_ALERT,
        link=lambda payload: payload[2],
    )
)

DEFAULTS[("pathway_tasks_opened", "email")] = (
    "{{ task.pathway }}: {{ task.count }} step{% if task.count != 1 %}s{% endif %} to do",
    "Hello {{ recipient.first_name }},\n\n"
    "You have new steps to do in “{{ task.pathway }}” ({{ task.stage }}): {{ task.steps }}."
    "{% if task.due %}\n\nThe first is due on {{ task.due }}.{% endif %}\n\n"
    "Open your tasks: {{ task.link }}" + SIGN,
)
DEFAULTS[("pathway_tasks_opened", "in_app")] = (
    "New steps to do: {{ task.pathway }}",
    "{{ task.steps }}",
)
DEFAULTS[("pathway_task_reminder", "email")] = (
    "{% if task.overdue %}Overdue{% else %}Reminder{% endif %}: {{ task.name }}",
    "Hello {{ recipient.first_name }},\n\n"
    "“{{ task.name }}” in “{{ task.pathway }}” "
    "{% if task.overdue %}was due on {{ task.due }}{% elif task.due %}is due on {{ task.due }}"
    "{% else %}is waiting for you{% endif %}.\n\n"
    "Open your tasks: {{ task.link }}" + SIGN,
)
DEFAULTS[("pathway_task_reminder", "in_app")] = (
    "{% if task.overdue %}Overdue{% else %}Reminder{% endif %}: {{ task.name }}",
    "{{ task.pathway }}{% if task.due %} · due {{ task.due }}{% endif %}",
)
DEFAULTS[("pathway_task_returned", "email")] = (
    "Please do this step again: {{ task.name }}",
    "Hello {{ recipient.first_name }},\n\n"
    "We've sent “{{ task.name }}” in “{{ task.pathway }}” back to you:\n\n"
    "{{ task.reason }}\n\n"
    "Open your tasks: {{ task.link }}" + SIGN,
)
DEFAULTS[("pathway_task_returned", "in_app")] = (
    "Sent back: {{ task.name }}",
    "{{ task.reason }}",
)
DEFAULTS[("staff_pathway_attention", "in_app")] = ("{{ alert.title }}", "{{ alert.body }}")
DEFAULTS[("staff_pathway_attention", "email")] = (
    "{{ alert.title }}",
    "{{ alert.body }}\n\n{{ alert.link }}" + SIGN,
)
