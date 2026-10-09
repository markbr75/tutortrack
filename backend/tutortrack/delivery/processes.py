"""Lesson delivery workflows (E09-TW1, E32).

``LessonReportSlaWorkflow`` ``report-sla:{org}:{report}``: started by
``lesson_report.requested``. Reminder before the due time → at the due time mark overdue
(``lesson_report.overdue``, optional pay hold) → after M more hours escalate to staff.
Signal ``submitted`` (from ``lesson_report.submitted``) ends it; each step also re-checks
the report, so a missed signal never sends a wrong reminder.

``UnconfirmedLessonWorkflow`` ``unconfirmed:{org}:{lesson}``: started (by a beat task,
see ``tasks.py``) when a lesson's end passes while still planned. After N hours it
auto-completes the lesson or flags it and nudges the tutor (setting). Signal ``resolved``
(lesson completed or cancelled) ends it early.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    idempotency_key,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import SettingsSnapshotInput, snapshot_settings

SLA_PROCESS = "report-sla"
UNCONFIRMED_PROCESS = "unconfirmed-lesson"
TIMEOUT = timedelta(minutes=5)
SLA_SETTINGS = ["delivery.report_reminder_hours", "delivery.report_escalate_hours"]
UNCONFIRMED_SETTINGS = ["delivery.unconfirmed_after_hours"]


def sla_workflow_id(organisation_id: object, report_id: object) -> str:
    return workflow_id(SLA_PROCESS, organisation_id, report_id)


def unconfirmed_workflow_id(organisation_id: object, lesson_id: object) -> str:
    return workflow_id(UNCONFIRMED_PROCESS, organisation_id, lesson_id)


# --- activities -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ReportSlaInput(WorkflowInput):
    report_id: str
    due_at: str  # ISO 8601 UTC


@dataclass(frozen=True, kw_only=True)
class UnconfirmedInput(WorkflowInput):
    lesson_id: str
    end: str  # ISO 8601 UTC


@tenant_activity
def remind_report_due(input: ReportSlaInput) -> bool:
    from . import services

    return services.report_due_reminder(input.report_id, dedupe_key=idempotency_key())


@tenant_activity
def mark_report_overdue(input: ReportSlaInput) -> bool:
    from . import services

    return services.mark_report_overdue(input.report_id, dedupe_key=idempotency_key())


@tenant_activity
def escalate_report(input: ReportSlaInput) -> bool:
    from . import services

    return services.escalate_report(input.report_id, dedupe_key=idempotency_key())


@tenant_activity
def report_is_written(input: ReportSlaInput) -> bool:
    from .models import LessonReport

    report = LessonReport.objects.filter(pk=input.report_id).first()
    return report is None or report.is_written


@tenant_activity
def handle_unconfirmed_lesson(input: UnconfirmedInput) -> str:
    from . import services

    return services.handle_unconfirmed(input.lesson_id, dedupe_key=idempotency_key())


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=SLA_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class LessonReportSlaWorkflow:
    def __init__(self) -> None:
        self.submitted = False
        self.step = "starting"

    @workflow.signal(name="submitted")
    def submitted_signal(self) -> None:
        self.submitted = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    async def _wait_until(self, moment: datetime) -> bool:
        """Sleep until ``moment``; True if the report was submitted meanwhile."""
        delay = moment - workflow.now()
        if delay > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.submitted, timeout=delay)
        if self.submitted:
            return True
        written = await workflow.execute_activity(
            report_is_written, self.input, start_to_close_timeout=TIMEOUT
        )
        return bool(written)

    async def _finish(self, step: str) -> str:
        self.step = step
        await report_step(self.input, step, status="completed")
        return step

    @workflow.run
    async def run(self, input: ReportSlaInput) -> str:
        self.input = input
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(organisation_id=input.organisation_id, keys=SLA_SETTINGS),
            start_to_close_timeout=TIMEOUT,
        )
        due = datetime.fromisoformat(input.due_at)
        remind_at = due - timedelta(hours=int(settings.get(SLA_SETTINGS[0], 4)))
        escalate_at = due + timedelta(hours=int(settings.get(SLA_SETTINGS[1], 24)))

        self.step = "due"
        await report_step(input, self.step)
        if await self._wait_until(remind_at):
            return await self._finish("submitted")
        await workflow.execute_activity(remind_report_due, input, start_to_close_timeout=TIMEOUT)

        if await self._wait_until(due):
            return await self._finish("submitted")
        self.step = "overdue"
        await report_step(input, self.step)
        await workflow.execute_activity(mark_report_overdue, input, start_to_close_timeout=TIMEOUT)

        if await self._wait_until(escalate_at):
            return await self._finish("submitted")
        await workflow.execute_activity(escalate_report, input, start_to_close_timeout=TIMEOUT)
        return await self._finish("escalated")


@register_workflow(process=UNCONFIRMED_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class UnconfirmedLessonWorkflow:
    def __init__(self) -> None:
        self.resolved = False
        self.step = "waiting"

    @workflow.signal(name="resolved")
    def resolved_signal(self) -> None:
        self.resolved = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    @workflow.run
    async def run(self, input: UnconfirmedInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(organisation_id=input.organisation_id, keys=UNCONFIRMED_SETTINGS),
            start_to_close_timeout=TIMEOUT,
        )
        hours = int(settings.get(UNCONFIRMED_SETTINGS[0], 24))
        deadline = datetime.fromisoformat(input.end) + timedelta(hours=hours)
        delay = deadline - workflow.now()
        if delay > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.resolved, timeout=delay)
        if self.resolved:
            self.step = "resolved"
        else:
            self.step = await workflow.execute_activity(
                handle_unconfirmed_lesson, input, start_to_close_timeout=TIMEOUT
            )
        await report_step(input, self.step, status="completed")
        return self.step
