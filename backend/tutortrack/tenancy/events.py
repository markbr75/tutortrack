"""Domain events emitted by tenancy (docs/03-domain-model.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class OrganisationCreated(DomainEvent):
    event_type: ClassVar[str] = "organisation.created"
    subject_type: ClassVar[str] = "organisation"

    name: str
    slug: str
    business_type: str
    country: str
    owner_id: str | None


@dataclass(frozen=True, kw_only=True)
class OrganisationUpdated(DomainEvent):
    event_type: ClassVar[str] = "organisation.updated"
    subject_type: ClassVar[str] = "organisation"

    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class OrganisationSettingsUpdated(DomainEvent):
    event_type: ClassVar[str] = "organisation.settings_updated"
    subject_type: ClassVar[str] = "organisation"

    area: str
    branch_id: str | None
    keys: list[str]


@dataclass(frozen=True, kw_only=True)
class OrganisationSuspended(DomainEvent):
    event_type: ClassVar[str] = "organisation.suspended"
    subject_type: ClassVar[str] = "organisation"

    reason: str


@dataclass(frozen=True, kw_only=True)
class OrganisationReactivated(DomainEvent):
    event_type: ClassVar[str] = "organisation.reactivated"
    subject_type: ClassVar[str] = "organisation"


@dataclass(frozen=True, kw_only=True)
class OrganisationClosed(DomainEvent):
    """Starts the closure process: export, 30-day grace, deletion (E02-TW1 / E29)."""

    event_type: ClassVar[str] = "organisation.closed"
    subject_type: ClassVar[str] = "organisation"

    reason: str
    export_requested: bool


@dataclass(frozen=True, kw_only=True)
class BranchCreated(DomainEvent):
    event_type: ClassVar[str] = "branch.created"
    subject_type: ClassVar[str] = "branch"

    name: str
    code: str
    is_default: bool


@dataclass(frozen=True, kw_only=True)
class BranchUpdated(DomainEvent):
    event_type: ClassVar[str] = "branch.updated"
    subject_type: ClassVar[str] = "branch"

    fields: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class BranchArchived(DomainEvent):
    event_type: ClassVar[str] = "branch.archived"
    subject_type: ClassVar[str] = "branch"


def changed_fields(changes: dict[str, Any]) -> list[str]:
    return sorted(changes)
