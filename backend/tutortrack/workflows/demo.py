"""Reference workflow (E32-T12): the pattern later epics copy.

``DemoReminderWorkflow`` waits N days in the tenant's local time (09:00 by default,
respecting quiet hours), then an activity publishes ``demo.reminder_due``. A ``cancel``
signal ends it early; the ``state`` query reports where it is. Remove once enough real
workflows exist to learn from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import ClassVar

from temporalio import workflow
from temporalio.common import RetryPolicy

from tutortrack.core.events import DomainEvent, publish
from tutortrack.core.workflows import (
    WorkflowInput,
    idempotency_key,
    register_workflow,
    tenant_activity,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import (
    BusinessCalendar,
    SettingsSnapshotInput,
    local_now,
    snapshot_settings,
    wait_until_local,
)

# --- event and activity ----------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DemoReminderDue(DomainEvent):
    event_type: ClassVar[str] = "demo.reminder_due"
    subject_type: ClassVar[str] = "demo"

    note: str


@dataclass(frozen=True, kw_only=True)
class DemoReminderInput(WorkflowInput):
    subject_id: str
    days: int = 3
    at: str = "09:00"  # tenant-local time of day
    note: str = ""


@tenant_activity
def publish_demo_reminder(input: DemoReminderInput) -> str:
    """Side effects live in activities: idempotent across retries via the dedupe key."""
    from django.db import transaction

    with transaction.atomic():
        event = publish(
            DemoReminderDue(subject_id=input.subject_id, note=input.note),
            dedupe_key=idempotency_key(),
        )
    return str(event.id)


# --- workflow --------------------------------------------------------------------------------


@register_workflow(process="demo-reminder")
@workflow.defn
class DemoReminderWorkflow:
    def __init__(self) -> None:
        self.cancelled = False
        self.step = "starting"

    @workflow.signal
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"step": self.step}

    @workflow.run
    async def run(self, input: DemoReminderInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(organisation_id=input.organisation_id, keys=[]),
            start_to_close_timeout=timedelta(seconds=30),
        )
        calendar = BusinessCalendar(timezone=settings["timezone"], quiet_start="21:00",
                                    quiet_end="08:00")  # fmt: skip
        # "N days from now at 09:00 local", computed deterministically from workflow time.
        today = local_now(calendar.timezone).date()
        due = datetime.combine(today + timedelta(days=input.days), time.fromisoformat(input.at))

        self.step = "waiting"
        await report_step(input, self.step)
        if await wait_until_local(due, calendar, until=lambda: self.cancelled):
            self.step = "cancelled"
            await report_step(input, self.step, status="completed")
            return "cancelled"

        self.step = "reminding"
        await workflow.execute_activity(
            publish_demo_reminder,
            input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1)),
        )
        self.step = "done"
        await report_step(input, self.step, status="completed")
        return "reminded"
