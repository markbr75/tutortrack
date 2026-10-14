"""Warehouse export events (E26-T09)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class WarehouseDestinationSaved(DomainEvent):
    """Syncs the destination's nightly Temporal Schedule."""

    event_type: ClassVar[str] = "warehouse_destination.saved"
    subject_type: ClassVar[str] = "warehouse_destination"
    kind: str


@dataclass(frozen=True, kw_only=True)
class WarehouseDestinationDeleted(DomainEvent):
    event_type: ClassVar[str] = "warehouse_destination.deleted"
    subject_type: ClassVar[str] = "warehouse_destination"


@dataclass(frozen=True, kw_only=True)
class WarehouseExportFinished(DomainEvent):
    event_type: ClassVar[str] = "warehouse_export.finished"
    subject_type: ClassVar[str] = "warehouse_export"
    status: str
    rows: int
