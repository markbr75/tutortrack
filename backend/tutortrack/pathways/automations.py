"""Pathway runs as a record type for workflows (E33), so businesses add their own emails and
nudges around a pathway (E34 FR-34-1 "Workflows hook in")."""

from __future__ import annotations

from typing import Any

from tutortrack.automations.builtins import _d, _tutors, tutor_ctx
from tutortrack.automations.conditions import register_predicate
from tutortrack.automations.registry import FieldDef as F
from tutortrack.automations.registry import Subject, register_subject, register_trigger
from tutortrack.core.events import subscribe


def run_ctx(run: Any) -> dict[str, Any]:
    return {
        "id": str(run.pk),
        "pathway": run.template.name,
        "kind": run.template.kind,
        "status": run.status,
        "stage": run.stage,
        "gates": list(run.gates),
        "record_type": run.subject_type,
        "started_at": _d(run.started_at),
        "finished_at": _d(run.finished_at),
        "tutor": tutor_ctx(run.tutor) if run.tutor else {},
    }


register_subject(
    Subject(
        key="pathway_run", label="Pathway", model="pathways.PathwayRun",
        fields=(
            F("pathway_run.pathway", "Pathway"),
            F("pathway_run.kind", "Kind", "choice", ("apply", "join", "finish", "custom")),
            F("pathway_run.status", "Status", "choice",
              ("running", "completed", "rejected", "cancelled")),
            F("pathway_run.stage", "Stage"),
            F("pathway_run.started_at", "Started", "datetime"),
            F("pathway_run.tutor.full_name", "Tutor"),
        ),
        context=run_ctx,
        recipients={"tutor": lambda run: _tutors([run.tutor] if run.tutor else [])},
        owner=lambda run: run.owner,
        date_fields=("started_at",),
    )
)  # fmt: skip

TRIGGERS = (
    ("pathway.started", "Pathway started"),
    ("pathway.step_completed", "Pathway step done"),
    ("pathway.stage_completed", "Pathway stage done"),
    ("pathway.completed", "Pathway finished"),
    ("pathway.cancelled", "Pathway cancelled"),
)
for _event, _label in TRIGGERS:
    register_trigger(_event, _label, "pathway_run")


def _subscribe_engine() -> None:
    """``automations`` subscribes the engine to the triggers registered before it loads;
    this app loads later, so it subscribes its own (same subscriber name)."""
    from tutortrack.automations.handlers import run_matching_automations

    subscribe(*[e for e, _label in TRIGGERS], name="automations.on_event")(run_matching_automations)


_subscribe_engine()

register_predicate(
    "pathway_run.in_progress",
    "The pathway is still in progress",
    lambda c: (c.get("pathway_run") or {}).get("status") == "running",
    subject="pathway_run",
)
