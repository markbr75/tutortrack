"""Domain events published by pathways (E34 §Events). Ids and keys only: answers, files
and signatures stay on the run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class PathwayStarted(DomainEvent):
    event_type: ClassVar[str] = "pathway.started"
    subject_type: ClassVar[str] = "pathway_run"
    template_key: str
    kind: str
    record_type: str
    record_id: str
    tutor_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class PathwayStepCompleted(DomainEvent):
    """A step finished: ``outcome`` is ``done`` or ``skipped``."""

    event_type: ClassVar[str] = "pathway.step_completed"
    subject_type: ClassVar[str] = "pathway_run"
    step: str
    step_type: str
    stage: str
    outcome: str


@dataclass(frozen=True, kw_only=True)
class PathwayStageCompleted(DomainEvent):
    """Every step in a stage is done or skipped; ``gate`` names the gate it reached."""

    event_type: ClassVar[str] = "pathway.stage_completed"
    subject_type: ClassVar[str] = "pathway_run"
    stage: str
    gate: str = ""
    record_type: str
    record_id: str


@dataclass(frozen=True, kw_only=True)
class PathwayCompleted(DomainEvent):
    """The run finished: ``outcome`` is ``completed`` or ``rejected`` (a staff review said
    no)."""

    event_type: ClassVar[str] = "pathway.completed"
    subject_type: ClassVar[str] = "pathway_run"
    template_key: str
    kind: str
    outcome: str
    record_type: str
    record_id: str
    tutor_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class PathwayCancelled(DomainEvent):
    event_type: ClassVar[str] = "pathway.cancelled"
    subject_type: ClassVar[str] = "pathway_run"
    template_key: str
    record_type: str
    record_id: str
