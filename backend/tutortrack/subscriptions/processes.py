"""Temporal workflows for our own subscription (E04-TW1).

* ``TrialLifecycleWorkflow`` ``trial:{org}:lifecycle``: started by ``subscription.started``.
  Welcome straight away, checklist on day 7, reminders 7 and 2 days before the end, then
  expiry: carry on with the chosen plan or lock read-only. Signals: ``converted`` (a card
  was added: no more reminders), ``extended(days)`` (platform admin).
* ``SubscriptionDunningWorkflow`` ``sub-dunning:{org}:{invoice}``: started by
  ``subscription.past_due``. Notices on days 0/3/7/14, read-only on day 21. Signal
  ``paid`` (``subscription.changed`` with ``payment_recovered``) ends it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
TRIAL_PROCESS = "trial"
DUNNING_PROCESS = "sub-dunning"
LATE = timedelta(hours=1)  # a notice whose moment passed longer ago than this is skipped


def trial_workflow_id(organisation_id: object) -> str:
    return workflow_id(TRIAL_PROCESS, organisation_id, "lifecycle")


def dunning_workflow_id(organisation_id: object, invoice_id: object) -> str:
    return workflow_id(DUNNING_PROCESS, organisation_id, invoice_id)


# --- activities -----------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TrialInput(WorkflowInput):
    trial_ends_at: str  # ISO datetime (UTC)
    welcome: bool = True


@dataclass(frozen=True, kw_only=True)
class NoticeInput(WorkflowInput):
    stage: str


@dataclass(frozen=True, kw_only=True)
class FinishInput(WorkflowInput):
    at: str  # the workflow's clock (ISO)


@dataclass(frozen=True, kw_only=True)
class DunningInput(WorkflowInput):
    invoice_id: str
    notice_days: list[int] = field(default_factory=lambda: [0, 3, 7, 14])
    suspend_after_days: int = 21


@dataclass(frozen=True, kw_only=True)
class DunningNoticeInput(WorkflowInput):
    day: int
    suspend_after_days: int


@tenant_activity
def send_trial_notice(input: NoticeInput) -> bool:
    from . import services

    return services.trial_notice(input.stage)


@tenant_activity
def finish_trial(input: FinishInput) -> str:
    from . import services

    return services.end_trial(datetime.fromisoformat(input.at))


@tenant_activity
def send_dunning_notice(input: DunningNoticeInput) -> bool:
    from . import services

    return services.dunning_notice(input.day, input.suspend_after_days)


@tenant_activity
def suspend_unpaid(input: WorkflowInput) -> bool:
    from . import services

    return services.suspend_for_non_payment()


# --- workflows ------------------------------------------------------------------------------


@register_workflow(
    process=TRIAL_PROCESS, task_queue="billing", cancel_permission="subscription.manage"
)
@workflow.defn
class TrialLifecycleWorkflow:
    def __init__(self) -> None:
        self.converted = False
        self.extra_days = 0
        self.sent: list[str] = []

    @workflow.signal(name="converted")
    def convert(self) -> None:
        self.converted = True

    @workflow.signal(name="extended")
    def extend(self, days: int) -> None:
        self.extra_days += int(days)

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"sent": self.sent, "converted": self.converted, "extra_days": self.extra_days}

    async def _until(self, target: Callable[[], datetime]) -> None:
        """Sleep until ``target()``, re-reading it whenever the trial is extended."""
        while True:
            remaining = target() - workflow.now()
            if remaining <= timedelta(0):
                return
            marker = self.extra_days
            try:
                await workflow.wait_condition(
                    lambda marker=marker: self.extra_days != marker,  # type: ignore[misc]
                    timeout=remaining,
                )
            except TimeoutError:
                return

    @workflow.run
    async def run(self, input: TrialInput) -> str:
        started = workflow.now()
        ends_at = datetime.fromisoformat(input.trial_ends_at)

        def end() -> datetime:
            return ends_at + timedelta(days=self.extra_days)

        stages: list[tuple[str, Callable[[], datetime]]] = [
            ("reminder", lambda: end() - timedelta(days=7)),
            ("last_chance", lambda: end() - timedelta(days=2)),
        ]
        if input.welcome:
            stages = [
                ("welcome", lambda: started),
                ("checklist", lambda: started + timedelta(days=6)),
                *stages,
            ]
        for stage, moment in stages:
            await self._until(moment)
            if self.converted or workflow.now() - moment() > LATE:
                continue
            if await workflow.execute_activity(
                send_trial_notice,
                NoticeInput(organisation_id=input.organisation_id, stage=stage),
                start_to_close_timeout=TIMEOUT,
            ):
                self.sent.append(stage)
        await self._until(end)
        result = ""
        for _attempt in range(12):  # the trial can be extended without a signal reaching us
            result = await workflow.execute_activity(
                finish_trial,
                FinishInput(organisation_id=input.organisation_id, at=workflow.now().isoformat()),
                start_to_close_timeout=TIMEOUT,
            )
            if not result.startswith("extended:"):
                break
            target = datetime.fromisoformat(result.split(":", 1)[1])
            await self._until(lambda target=target: target)  # type: ignore[misc]
        await report_step(input, result, status="completed")
        return result


@register_workflow(
    process=DUNNING_PROCESS, task_queue="billing", cancel_permission="subscription.manage"
)
@workflow.defn
class SubscriptionDunningWorkflow:
    def __init__(self) -> None:
        self.paid = False
        self.sent: list[int] = []

    @workflow.signal(name="paid")
    def pay(self) -> None:
        self.paid = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"sent": self.sent, "paid": self.paid}

    async def _wait(self, until: datetime) -> bool:
        """True if paid before ``until``."""
        remaining = until - workflow.now()
        if remaining > timedelta(0) and not self.paid:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.paid, timeout=remaining)
        return self.paid

    @workflow.run
    async def run(self, input: DunningInput) -> str:
        started = workflow.now()
        result = ""
        for day in sorted(set(input.notice_days)):
            if await self._wait(started + timedelta(days=day)):
                result = "paid"
                break
            if not await workflow.execute_activity(
                send_dunning_notice,
                DunningNoticeInput(
                    organisation_id=input.organisation_id,
                    day=day,
                    suspend_after_days=input.suspend_after_days,
                ),
                start_to_close_timeout=TIMEOUT,
            ):
                result = "recovered"
                break
            self.sent.append(day)
        if not result:
            if await self._wait(started + timedelta(days=input.suspend_after_days)):
                result = "paid"
            else:
                suspended = await workflow.execute_activity(
                    suspend_unpaid,
                    WorkflowInput(organisation_id=input.organisation_id),
                    start_to_close_timeout=TIMEOUT,
                )
                result = "suspended" if suspended else "recovered"
        await report_step(input, result, status="completed")
        return result
