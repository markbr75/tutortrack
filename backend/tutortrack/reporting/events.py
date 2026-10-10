"""Domain events published by reporting (E26)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from tutortrack.core.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ReportExported(DomainEvent):
    """Someone downloaded a report (also an ``export`` audit entry)."""

    event_type: ClassVar[str] = "report.exported"
    subject_type: ClassVar[str] = "report_run"
    report_key: str
    format: str
    rows: int


@dataclass(frozen=True, kw_only=True)
class SavedReportCreated(DomainEvent):
    event_type: ClassVar[str] = "saved_report.created"
    subject_type: ClassVar[str] = "saved_report"
    report_key: str
    shared: bool


@dataclass(frozen=True, kw_only=True)
class SavedReportDeleted(DomainEvent):
    event_type: ClassVar[str] = "saved_report.deleted"
    subject_type: ClassVar[str] = "saved_report"
    report_key: str


@dataclass(frozen=True, kw_only=True)
class ScheduledReportSaved(DomainEvent):
    """Creates, updates or pauses the report's Temporal Schedule (handlers.py)."""

    event_type: ClassVar[str] = "scheduled_report.saved"
    subject_type: ClassVar[str] = "scheduled_report"
    frequency: str
    enabled: bool


@dataclass(frozen=True, kw_only=True)
class ScheduledReportDeleted(DomainEvent):
    event_type: ClassVar[str] = "scheduled_report.deleted"
    subject_type: ClassVar[str] = "scheduled_report"


@dataclass(frozen=True, kw_only=True)
class ReportRunDelivered(DomainEvent):
    event_type: ClassVar[str] = "report_run.delivered"
    subject_type: ClassVar[str] = "report_run"
    scheduled_report_id: str
    recipients: int
    rows: int


@dataclass(frozen=True, kw_only=True)
class ReportRunFailed(DomainEvent):
    event_type: ClassVar[str] = "report_run.failed"
    subject_type: ClassVar[str] = "report_run"
    scheduled_report_id: str
    error: str
