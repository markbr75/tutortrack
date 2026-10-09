from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class NoteCreated(DomainEvent):
    event_type: ClassVar[str] = "note.created"
    subject_type: ClassVar[str] = "note"
    target_type: str
    target_id: str
    visibility: str
    mentions: list[str] = field(default_factory=list)  # E13 notifies mentioned staff


@dataclass(frozen=True, kw_only=True)
class TaskCreated(DomainEvent):
    event_type: ClassVar[str] = "task.created"
    subject_type: ClassVar[str] = "task"
    assignee_id: str | None
    due_at: str | None


@dataclass(frozen=True, kw_only=True)
class TaskAssigned(DomainEvent):
    event_type: ClassVar[str] = "task.assigned"
    subject_type: ClassVar[str] = "task"
    assignee_id: str


@dataclass(frozen=True, kw_only=True)
class TaskCompleted(DomainEvent):
    event_type: ClassVar[str] = "task.completed"
    subject_type: ClassVar[str] = "task"


@dataclass(frozen=True, kw_only=True)
class DocumentUploaded(DomainEvent):
    event_type: ClassVar[str] = "document.uploaded"
    subject_type: ClassVar[str] = "document"
    target_type: str
    target_id: str
    category: str
