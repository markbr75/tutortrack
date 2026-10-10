"""Domain events published by automations (E14). They never trigger automations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class AutomationSaved(DomainEvent):
    """Created, edited, enabled or disabled: keeps its Temporal Schedule in step."""

    event_type: ClassVar[str] = "automation.saved"
    subject_type: ClassVar[str] = "automation"
    trigger_type: str
    enabled: bool
    automation_version: int


@dataclass(frozen=True, kw_only=True)
class AutomationDeleted(DomainEvent):
    event_type: ClassVar[str] = "automation.deleted"
    subject_type: ClassVar[str] = "automation"


@dataclass(frozen=True, kw_only=True)
class AutomationRunFailed(DomainEvent):
    event_type: ClassVar[str] = "automation.run_failed"
    subject_type: ClassVar[str] = "automation_run"
    automation_id: str
    error: str
