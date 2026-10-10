"""Temporal workflows for calendar connections and online meetings (E22-TW1).

* ``CalendarConnectionWorkflow`` ``calendar:{org}:{connection}``: started by
  ``integration.connected`` for calendar providers. Long-running: each loop refreshes the
  token, initialises calendars and renews push channels before they expire (``prepare``),
  then syncs incrementally. It waits for a ``changed`` signal (provider push webhooks,
  settings changes) or the polling fallback timer (5 minutes, CalDAV 10), whichever comes
  first. Failures back off exponentially (up to an hour); a revoked grant waits for
  ``reconnected``. ``disconnect`` ends it (channels stopped, busy blocks removed). After
  ``max_loops`` iterations it continues as new to keep the history short. Replaces the
  watch-renewal and polling beat jobs.
* ``OnlineMeetingProvisioningWorkflow`` ``online-meeting:{org}:{subject}:{event}``: one
  per lesson (or series) change. Reconciles each lesson's meeting with retries and
  backoff; when a lesson ultimately fails, it is marked failed and staff are told. The id
  includes the triggering event because Temporal ids can't be reused after completion.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

CALENDAR_PROCESS = "calendar"
MEETING_PROCESS = "online-meeting"
TIMEOUT = timedelta(minutes=5)
QUICK_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
    non_retryable_error_types=["AuthError", "ConfigurationError"],
)
MAX_BACKOFF = timedelta(hours=1)
RECONNECT_WAIT = timedelta(days=7)


def calendar_workflow_id(org: object, connection_id: object) -> str:
    return workflow_id(CALENDAR_PROCESS, org, connection_id)


def meeting_workflow_id(org: object, subject_id: object, event_id: object) -> str:
    return workflow_id(MEETING_PROCESS, org, subject_id, event_id)


@dataclass(frozen=True, kw_only=True)
class CalendarInput(WorkflowInput):
    connection_id: str
    failures: int = 0
    max_loops: int = 200


@dataclass(frozen=True, kw_only=True)
class MeetingInput(WorkflowInput):
    lesson_ids: list[str] = field(default_factory=list)
    attempts: int = 6


@dataclass(frozen=True, kw_only=True)
class LessonMeetingInput(WorkflowInput):
    lesson_id: str
    error: str = ""


# --- activities ----------------------------------------------------------------------------------


@tenant_activity
def prepare_connection(input: CalendarInput) -> dict[str, Any]:
    from . import services

    return services.prepare(input.connection_id)


@tenant_activity
def sync_connection(input: CalendarInput) -> dict[str, Any]:
    from . import services

    return services.sync_connection(input.connection_id)


@tenant_activity
def backfill_connection(input: CalendarInput) -> int:
    from tutortrack.integrations.models import IntegrationConnection

    from . import services

    connection = IntegrationConnection.objects.get(pk=input.connection_id)
    return services.backfill(connection)


@tenant_activity
def teardown_connection(input: CalendarInput) -> bool:
    from tutortrack.integrations.models import IntegrationConnection

    from . import services

    connection = IntegrationConnection.objects.get(pk=input.connection_id)
    services.clear(connection)
    return True


@tenant_activity
def provision_meeting(input: LessonMeetingInput) -> str:
    from . import meetings

    return meetings.reconcile(input.lesson_id)


@tenant_activity
def meeting_failed(input: LessonMeetingInput) -> bool:
    from . import meetings

    return meetings.mark_failed(input.lesson_id, input.error)


# --- workflows -----------------------------------------------------------------------------------


@register_workflow(process=CALENDAR_PROCESS, task_queue="integrations", cancel_permission=None)
@workflow.defn
class CalendarConnectionWorkflow:
    def __init__(self) -> None:
        self.changed = False
        self.disconnected = False
        self.reconnected = False

    @workflow.signal(name="changed")
    def on_changed(self) -> None:
        self.changed = True

    @workflow.signal(name="disconnect")
    def on_disconnect(self) -> None:
        self.disconnected = True

    @workflow.signal(name="reconnected")
    def on_reconnected(self) -> None:
        self.reconnected = True

    @workflow.query
    def state(self) -> dict[str, bool]:
        return {"changed": self.changed, "disconnected": self.disconnected}

    async def _pause(self, timeout: timedelta, *, wake_on_change: bool) -> None:
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: self.disconnected or self.reconnected or (wake_on_change and self.changed),
                timeout=timeout,
            )

    @workflow.run
    async def run(self, input: CalendarInput) -> str:
        failures = input.failures
        backfilled = False
        for _loop in range(input.max_loops):
            if self.disconnected:
                break
            try:
                plan = await workflow.execute_activity(
                    prepare_connection,
                    input,
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=QUICK_RETRY,
                )
                if plan["status"] == "disconnected":
                    self.disconnected = True
                    break
                if plan["status"] == "needs_reconnect":
                    await report_step(input, "needs_reconnect")
                    self.reconnected = False
                    await self._pause(RECONNECT_WAIT, wake_on_change=False)
                    self.reconnected = False
                    continue
                if not backfilled:
                    await workflow.execute_activity(
                        backfill_connection,
                        input,
                        start_to_close_timeout=TIMEOUT * 6,
                        retry_policy=QUICK_RETRY,
                    )
                    backfilled = True
                    await report_step(input, "syncing")
                self.changed = False
                result = await workflow.execute_activity(
                    sync_connection,
                    input,
                    start_to_close_timeout=TIMEOUT,
                    retry_policy=QUICK_RETRY,
                )
                if result["status"] == "needs_reconnect":
                    continue
                if failures:
                    await report_step(input, "syncing")
                failures = 0
            except ActivityError:
                failures += 1
                if failures == 1:
                    await report_step(input, "backing_off")
                backoff = min(timedelta(minutes=2 ** min(failures, 6)), MAX_BACKOFF)
                await self._pause(backoff, wake_on_change=False)
                self.reconnected = False
                continue
            wait = min(int(plan["poll_seconds"]), int(plan["renew_in_seconds"]))
            await self._pause(timedelta(seconds=max(wait, 30)), wake_on_change=True)
            self.reconnected = False
        if self.disconnected:
            await workflow.execute_activity(
                teardown_connection, input, start_to_close_timeout=TIMEOUT
            )
            await report_step(input, "disconnected", status="completed")
            return "disconnected"
        workflow.continue_as_new(replace(input, failures=failures))


@register_workflow(process=MEETING_PROCESS, task_queue="integrations", cancel_permission=None)
@workflow.defn
class OnlineMeetingProvisioningWorkflow:
    @workflow.run
    async def run(self, input: MeetingInput) -> dict[str, str]:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=10),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(minutes=10),
            maximum_attempts=max(input.attempts, 1),
            non_retryable_error_types=["ConfigurationError", "AuthError"],
        )
        results: dict[str, str] = {}
        for lesson_id in input.lesson_ids:
            one = LessonMeetingInput(organisation_id=input.organisation_id, lesson_id=lesson_id)
            try:
                results[lesson_id] = await workflow.execute_activity(
                    provision_meeting,
                    one,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=retry,
                )
            except ActivityError as exc:
                error = str(exc.cause) if exc.cause is not None else str(exc)
                await workflow.execute_activity(
                    meeting_failed, replace(one, error=error[:300]), start_to_close_timeout=TIMEOUT
                )
                results[lesson_id] = "failed"
        failed = any(r == "failed" for r in results.values())
        await report_step(input, "failed" if failed else "done", status="completed")
        return results
