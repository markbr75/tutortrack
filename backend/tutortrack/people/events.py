"""Domain events emitted by people (docs/03-domain-model.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ClientCreated(DomainEvent):
    event_type: ClassVar[str] = "client.created"
    subject_type: ClassVar[str] = "client"
    display_name: str


@dataclass(frozen=True, kw_only=True)
class ClientUpdated(DomainEvent):
    event_type: ClassVar[str] = "client.updated"
    subject_type: ClassVar[str] = "client"
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class ClientArchived(DomainEvent):
    event_type: ClassVar[str] = "client.archived"
    subject_type: ClassVar[str] = "client"


@dataclass(frozen=True, kw_only=True)
class ContactCreated(DomainEvent):
    event_type: ClassVar[str] = "contact.created"
    subject_type: ClassVar[str] = "contact"
    client_id: str


@dataclass(frozen=True, kw_only=True)
class ContactUpdated(DomainEvent):
    event_type: ClassVar[str] = "contact.updated"
    subject_type: ClassVar[str] = "contact"
    client_id: str
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class StudentCreated(DomainEvent):
    event_type: ClassVar[str] = "student.created"
    subject_type: ClassVar[str] = "student"
    client_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class StudentUpdated(DomainEvent):
    event_type: ClassVar[str] = "student.updated"
    subject_type: ClassVar[str] = "student"
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class StudentStatusChanged(DomainEvent):
    """``waiting`` feeds the waitlist (E17/E20)."""

    event_type: ClassVar[str] = "student.status_changed"
    subject_type: ClassVar[str] = "student"
    old_status: str
    new_status: str


@dataclass(frozen=True, kw_only=True)
class TutorCreated(DomainEvent):
    event_type: ClassVar[str] = "tutor.created"
    subject_type: ClassVar[str] = "tutor"
    email: str


@dataclass(frozen=True, kw_only=True)
class TutorUpdated(DomainEvent):
    event_type: ClassVar[str] = "tutor.updated"
    subject_type: ClassVar[str] = "tutor"
    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class TutorStatusChanged(DomainEvent):
    event_type: ClassVar[str] = "tutor.status_changed"
    subject_type: ClassVar[str] = "tutor"
    old_status: str
    new_status: str
