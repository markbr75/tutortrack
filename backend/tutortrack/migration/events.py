"""Domain events published by imports, migration projects and exports (E28)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _ImportEvent(DomainEvent):
    subject_type: ClassVar[str] = "import"
    entity: str
    source: str


@dataclass(frozen=True, kw_only=True)
class ImportSubmitted(_ImportEvent):
    """Mapping done: ``ImportWorkflow`` starts (validation and dry run first)."""

    event_type: ClassVar[str] = "import.submitted"


@dataclass(frozen=True, kw_only=True)
class ImportValidated(_ImportEvent):
    event_type: ClassVar[str] = "import.validated"
    stats: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ImportCompleted(_ImportEvent):
    event_type: ClassVar[str] = "import.completed"
    stats: dict[str, object] = field(default_factory=dict)
    rollback_until: str = ""


@dataclass(frozen=True, kw_only=True)
class ImportFailed(_ImportEvent):
    event_type: ClassVar[str] = "import.failed"
    error: str = ""


@dataclass(frozen=True, kw_only=True)
class ImportRolledBack(_ImportEvent):
    event_type: ClassVar[str] = "import.rolled_back"
    reverted: int = 0
    kept: int = 0


@dataclass(frozen=True, kw_only=True)
class ImportFinalised(_ImportEvent):
    """The rollback window closed."""

    event_type: ClassVar[str] = "import.finalised"


@dataclass(frozen=True, kw_only=True)
class MigrationProjectStarted(DomainEvent):
    event_type: ClassVar[str] = "migration_project.started"
    subject_type: ClassVar[str] = "migration_project"
    source: str
    cutover_date: str


@dataclass(frozen=True, kw_only=True)
class MigrationStepCompleted(DomainEvent):
    event_type: ClassVar[str] = "migration_project.step_completed"
    subject_type: ClassVar[str] = "migration_project"
    step: str
    skipped: bool = False


@dataclass(frozen=True, kw_only=True)
class MigrationProjectCompleted(DomainEvent):
    event_type: ClassVar[str] = "migration_project.completed"
    subject_type: ClassVar[str] = "migration_project"
    source: str


@dataclass(frozen=True, kw_only=True)
class ExportRequested(DomainEvent):
    """``TenantExportWorkflow`` starts."""

    event_type: ClassVar[str] = "export.requested"
    subject_type: ClassVar[str] = "export"
    kind: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class ExportReady(DomainEvent):
    event_type: ClassVar[str] = "export.ready"
    subject_type: ClassVar[str] = "export"
    size_bytes: int
    expires_at: str


@dataclass(frozen=True, kw_only=True)
class ExportExpired(DomainEvent):
    event_type: ClassVar[str] = "export.expired"
    subject_type: ClassVar[str] = "export"


@dataclass(frozen=True, kw_only=True)
class ExportDownloaded(DomainEvent):
    event_type: ClassVar[str] = "export.downloaded"
    subject_type: ClassVar[str] = "export"
    count: int
