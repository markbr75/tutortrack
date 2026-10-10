"""Temporal workflows for recruitment and compliance (E18-TW1).

* ``TutorApplicationWorkflow`` ``application:{org}:{id}``: reminds the recruiters when an
  application sits in a stage longer than its reminder days; signals ``stage_changed`` and
  ``closed`` (approved or rejected).
* ``ReferenceRequestWorkflow`` ``reference:{org}:{id}``: reminds the referee after 3 and 7
  days and gives up after ``recruitment.reference_days``; signal ``received``.
* ``TutorOnboardingWorkflow`` ``onboarding:{org}:{tutor}``: re-checks the checklist when an
  item is done (signal ``item_done``) and every 3 days (with a reminder to the tutor), and
  activates the tutor once the mandatory items are complete.
* ``ComplianceRecordWorkflow`` ``compliance:{org}:{record}:{expiry}``: reminders 60/30/7 days
  before expiry, then expires the record (restricting the tutor). A renewal signals
  ``renewed`` to the old run and starts a new one for the new expiry.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import (
    BusinessCalendar,
    delay_until_local,
    wait_until_local,
)

TIMEOUT = timedelta(minutes=5)
APPLICATION_PROCESS = "application"
REFERENCE_PROCESS = "reference"
ONBOARDING_PROCESS = "onboarding"
COMPLIANCE_PROCESS = "compliance"
ONBOARDING_CHECK = timedelta(days=3)
MAX_ROUNDS = 40


def application_workflow_id(org: object, application_id: object) -> str:
    return workflow_id(APPLICATION_PROCESS, org, application_id)


def reference_workflow_id(org: object, reference_id: object) -> str:
    return workflow_id(REFERENCE_PROCESS, org, reference_id)


def onboarding_workflow_id(org: object, tutor_id: object) -> str:
    return workflow_id(ONBOARDING_PROCESS, org, tutor_id)


def compliance_workflow_id(org: object, record_id: object, expiry: str) -> str:
    return workflow_id(COMPLIANCE_PROCESS, org, record_id, expiry.replace("-", ""))


@dataclass(frozen=True, kw_only=True)
class ApplicationInput(WorkflowInput):
    application_id: str


@dataclass(frozen=True, kw_only=True)
class ReferenceInput(WorkflowInput):
    reference_id: str


@dataclass(frozen=True, kw_only=True)
class OnboardingInput(WorkflowInput):
    tutor_id: str


@dataclass(frozen=True, kw_only=True)
class ComplianceInput(WorkflowInput):
    record_id: str
    expiry: str  # ISO date
    timezone: str
    reminder_days: list[int] = field(default_factory=lambda: [60, 30, 7])


@dataclass(frozen=True, kw_only=True)
class ReminderInput(WorkflowInput):
    record_id: str
    expiry: str
    days: int


# --- activities -----------------------------------------------------------------------------


@tenant_activity
def application_reminder_days(input: ApplicationInput) -> int:
    from . import services

    return services.stage_reminder_days(input.application_id)


@tenant_activity
def remind_recruiters(input: ApplicationInput) -> bool:
    from . import services

    return services.stuck_reminder(input.application_id)


@tenant_activity
def reference_days(input: ReferenceInput) -> int:
    from . import services

    return services.reference_days()


@tenant_activity
def remind_referee(input: ReferenceInput) -> bool:
    from . import services

    return services.remind_referee(input.reference_id)


@tenant_activity
def expire_reference(input: ReferenceInput) -> bool:
    from . import services

    return services.expire_reference(input.reference_id)


@tenant_activity
def check_onboarding(input: OnboardingInput) -> str:
    from . import services

    return services.check_onboarding(input.tutor_id)


@tenant_activity
def remind_onboarding(input: OnboardingInput) -> bool:
    from . import services

    return services.remind_onboarding(input.tutor_id)


@tenant_activity
def remind_expiry(input: ReminderInput) -> bool:
    from . import compliance

    return compliance.remind(input.record_id, input.days, input.expiry)


@tenant_activity
def expire_record(input: ComplianceInput) -> bool:
    from . import compliance

    # The workflow wakes on the expiry date, which is the first day it isn't valid.
    return compliance.expire(input.record_id, on=date.fromisoformat(input.expiry))


# --- workflows ------------------------------------------------------------------------------


@register_workflow(process=APPLICATION_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class TutorApplicationWorkflow:
    def __init__(self) -> None:
        self.changes = 0
        self.closed = False

    @workflow.signal(name="stage_changed")
    def stage_changed(self) -> None:
        self.changes += 1

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.run
    async def run(self, input: ApplicationInput) -> str:
        reminders = 0
        for _round in range(MAX_ROUNDS):
            days = await workflow.execute_activity(
                application_reminder_days, input, start_to_close_timeout=TIMEOUT
            )
            if self.closed or not days:
                break
            seen = self.changes
            try:
                await workflow.wait_condition(
                    lambda seen=seen: self.closed or self.changes != seen,  # type: ignore[misc]
                    timeout=timedelta(days=days),
                )
            except TimeoutError:
                if await workflow.execute_activity(
                    remind_recruiters, input, start_to_close_timeout=TIMEOUT
                ):
                    reminders += 1
        await report_step(input, "finished", status="completed")
        return f"reminders:{reminders}"


@register_workflow(process=REFERENCE_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class ReferenceRequestWorkflow:
    def __init__(self) -> None:
        self.received = False

    @workflow.signal(name="received")
    def receive(self) -> None:
        self.received = True

    @workflow.run
    async def run(self, input: ReferenceInput) -> str:
        total = await workflow.execute_activity(
            reference_days, input, start_to_close_timeout=TIMEOUT
        )
        waited = 0
        for at in (3, 7):
            if at >= total:
                break
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.received, timeout=timedelta(days=at - waited)
                )
            waited = at
            if self.received:
                break
            await workflow.execute_activity(remind_referee, input, start_to_close_timeout=TIMEOUT)
        if not self.received:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.received, timeout=timedelta(days=total - waited)
                )
        if self.received:
            result = "received"
        else:
            await workflow.execute_activity(expire_reference, input, start_to_close_timeout=TIMEOUT)
            result = "expired"
        await report_step(input, result, status="completed")
        return result


@register_workflow(process=ONBOARDING_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class TutorOnboardingWorkflow:
    def __init__(self) -> None:
        self.events = 0

    @workflow.signal(name="item_done")
    def item_done(self) -> None:
        self.events += 1

    @workflow.run
    async def run(self, input: OnboardingInput) -> str:
        for _round in range(MAX_ROUNDS):
            state = await workflow.execute_activity(
                check_onboarding, input, start_to_close_timeout=TIMEOUT
            )
            if state in ("complete", "done"):
                await report_step(input, state, status="completed")
                return state
            seen = self.events
            try:
                await workflow.wait_condition(
                    lambda seen=seen: self.events != seen,  # type: ignore[misc]
                    timeout=ONBOARDING_CHECK,
                )
            except TimeoutError:
                await workflow.execute_activity(
                    remind_onboarding, input, start_to_close_timeout=TIMEOUT
                )
        await report_step(input, "gave_up", status="completed")
        return "gave_up"


@register_workflow(process=COMPLIANCE_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class ComplianceRecordWorkflow:
    def __init__(self) -> None:
        self.renewed = False

    @workflow.signal(name="renewed")
    def renew(self) -> None:
        self.renewed = True

    @workflow.run
    async def run(self, input: ComplianceInput) -> str:
        calendar = BusinessCalendar(timezone=input.timezone)
        expiry = date.fromisoformat(input.expiry)
        for days in sorted({int(d) for d in input.reminder_days}, reverse=True):
            moment = datetime.combine(expiry - timedelta(days=days), time(9, 0))
            if delay_until_local(workflow.now(), moment, calendar) <= timedelta(0):
                continue  # verified after this reminder would have gone out
            if await wait_until_local(moment, calendar, until=lambda: self.renewed):
                break
            await workflow.execute_activity(
                remind_expiry,
                ReminderInput(
                    organisation_id=input.organisation_id,
                    record_id=input.record_id,
                    expiry=input.expiry,
                    days=days,
                ),
                start_to_close_timeout=TIMEOUT,
            )
        if not self.renewed:
            await wait_until_local(
                datetime.combine(expiry, time(0, 5)), calendar, until=lambda: self.renewed
            )
        result: Any = "renewed"
        if not self.renewed:
            expired = await workflow.execute_activity(
                expire_record, input, start_to_close_timeout=TIMEOUT
            )
            result = "expired" if expired else "still_valid"
        await report_step(input, result, status="completed")
        return str(result)
