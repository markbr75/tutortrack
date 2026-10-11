"""Domain events published by accounting integrations (E23 §4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _SyncEvent(DomainEvent):
    subject_type: ClassVar[str] = "accounting_record"
    provider: str
    object_type: str
    object_id: str


@dataclass(frozen=True, kw_only=True)
class AccountingSyncSucceeded(_SyncEvent):
    event_type: ClassVar[str] = "accounting.sync_succeeded"
    external_id: str
    outcome: str  # created | updated | voided


@dataclass(frozen=True, kw_only=True)
class AccountingSyncFailed(_SyncEvent):
    event_type: ClassVar[str] = "accounting.sync_failed"
    error_code: str
    error: str


@dataclass(frozen=True, kw_only=True)
class AccountingConnectionError(DomainEvent):
    """The ledger connection broke (revoked, or the provider keeps failing)."""

    event_type: ClassVar[str] = "accounting.connection_error"
    subject_type: ClassVar[str] = "accounting_connection"
    provider: str
    status: str
    error: str
