"""Tenant-local timers for workflow code (E32 FR-32-6).

Deadlines are expressed in the tenant's local time ("09:00 on the due date in
Europe/London") and converted to durable timers with ``workflow.now()`` (deterministic).
Quiet hours (E13) and holidays (E06) shift a reminder to the next allowed moment; both are
read once through ``snapshot_settings`` at workflow start and kept in workflow state, so a
settings change does not alter in-flight processes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from temporalio import workflow

from .activity import WorkflowInput, tenant_activity


@dataclass(frozen=True)
class BusinessCalendar:
    """Snapshot of when the tenant may be contacted."""

    timezone: str
    quiet_start: str | None = None  # "21:00"
    quiet_end: str | None = None  # "08:00"
    closed_weekdays: tuple[int, ...] = ()  # 0 = Monday
    holidays: tuple[str, ...] = ()  # ISO dates

    def _quiet(self, local: datetime) -> bool:
        if self.quiet_start is None or self.quiet_end is None:
            return False
        start, end = time.fromisoformat(self.quiet_start), time.fromisoformat(self.quiet_end)
        now_t = local.time()
        return (start <= now_t or now_t < end) if start > end else (start <= now_t < end)

    def _closed_day(self, day: date) -> bool:
        return day.weekday() in self.closed_weekdays or day.isoformat() in self.holidays

    def next_allowed(self, local: datetime) -> datetime:
        """The first moment at or after ``local`` outside quiet hours and closed days."""
        candidate = local
        for _ in range(400):  # bounded: a year of closed days at most
            if self._closed_day(candidate.date()):
                opening = time.fromisoformat(self.quiet_end) if self.quiet_end else time(0)
                candidate = datetime.combine(candidate.date() + timedelta(days=1), opening)
                continue
            if self._quiet(candidate) and self.quiet_end is not None:
                end = time.fromisoformat(self.quiet_end)
                day = (
                    candidate.date() if candidate.time() < end else candidate.date() + timedelta(1)
                )
                candidate = datetime.combine(day, end)
                continue
            return candidate
        return candidate


def local_now(tz: str) -> datetime:
    """Workflow time as a naive wall-clock datetime in ``tz`` (deterministic)."""
    return workflow.now().astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def to_utc(local_naive: datetime, tz: str) -> datetime:
    """Wall-clock time in ``tz`` → aware UTC (gaps resolve forward, folds to the first)."""
    zone = ZoneInfo(tz)
    aware = local_naive.replace(tzinfo=zone, fold=0)
    return aware.astimezone(ZoneInfo("UTC"))


def delay_until_local(
    now_utc: datetime, local_naive: datetime, calendar: BusinessCalendar
) -> timedelta:
    target = to_utc(calendar.next_allowed(local_naive), calendar.timezone)
    return max(target - now_utc, timedelta(0))


async def wait_until_local(
    local_naive: datetime,
    calendar: BusinessCalendar,
    *,
    until: Callable[[], bool] | None = None,
) -> bool:
    """Sleep (durably) until the local deadline. With ``until``, wake early when it turns
    true (e.g. a cancel signal) and return True; returns False when the time came."""
    delay = delay_until_local(workflow.now(), local_naive, calendar)
    if until is None:
        if delay > timedelta(0):
            await workflow.sleep(delay)
        return False
    try:
        await workflow.wait_condition(until, timeout=delay if delay > timedelta(0) else None)
    except TimeoutError:
        return False
    return True


# --- settings snapshot (activity) --------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SettingsSnapshotInput(WorkflowInput):
    keys: list[str] = field(default_factory=list)
    branch_id: str | None = None


@tenant_activity
def snapshot_settings(input: SettingsSnapshotInput) -> dict[str, Any]:
    """Current values of registered settings (unknown keys are skipped) plus the
    organisation's timezone under ``"timezone"``."""
    from tutortrack.tenancy.models import Branch, Organisation
    from tutortrack.tenancy.settings_registry import registry
    from tutortrack.tenancy.settings_service import get_setting

    branch = Branch.objects.filter(pk=input.branch_id).first() if input.branch_id else None
    values: dict[str, Any] = {}
    for key in input.keys:
        try:
            registry.get(key)
        except KeyError:
            continue
        values[key] = get_setting(key, branch=branch)
    org = Organisation.objects.get(pk=input.organisation_id)
    values["timezone"] = branch.timezone if branch else org.timezone
    return values
