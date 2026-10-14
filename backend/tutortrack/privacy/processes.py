"""Privacy workflows on Temporal (E29-TW1). Task queue: ``privacy``.

* ``DataSubjectRequestWorkflow`` ``dsar:{org}:{request}``: started by
  ``data_request.received``. Escalating deadline reminders (7 days, 2 days, overdue) run
  while it waits for ``identity_verified``; then it compiles the export (or the erasure
  preview) and waits for ``redaction_approved`` (access) or ``erasure_approved``; access
  requests are delivered as a secure link that expires (timer), erasures run
  ``ErasureWorkflow`` as a child. ``deadline_changed`` and ``closed`` signals come from
  staff decisions. Replaces deadline-tracker polling.
* ``ErasureWorkflow`` ``erasure:{org}:{request}``: legal-hold check → each provider
  anonymises its records (one idempotent activity per app) → delete files → revoke logins
  → audit summary.
* ``RetentionPurgeWorkflow``: a per-organisation Temporal Schedule (nightly at 02:00
  organisation time while ``privacy.retention_purge`` is not ``off``), or started by staff
  for a manual run: dry-run report → purge in batches per category → notify admins.
* ``LoneWorkingWorkflow`` ``lone-working:{org}:{visit}``: started by
  ``lone_working.checked_in``; alerts when the tutor hasn't checked out after the grace
  period, escalates to safeguarding leads, ends on ``checked_out``/``resolved``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from tutortrack.core.workflows import (
    WorkflowInput,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step

TIMEOUT = timedelta(minutes=5)
LONG = timedelta(minutes=30)  # compiling an export or erasing across the apps
RETRY = RetryPolicy(maximum_attempts=10, maximum_interval=timedelta(minutes=10))
DSAR_PROCESS = "dsar"
ERASURE_PROCESS = "erasure"
RETENTION_PROCESS = "retention-purge"
LONE_WORKING_PROCESS = "lone-working"
MAX_ROUNDS = 500
MAX_BATCHES = 1000
BATCH = 100


def dsar_workflow_id(org: object, request_id: object) -> str:
    return workflow_id(DSAR_PROCESS, org, request_id)


def erasure_workflow_id(org: object, request_id: object) -> str:
    return workflow_id(ERASURE_PROCESS, org, request_id)


def lone_working_workflow_id(org: object, visit_id: object) -> str:
    return workflow_id(LONE_WORKING_PROCESS, org, visit_id)


@dataclass(frozen=True, kw_only=True)
class RequestInput(WorkflowInput):
    request_id: str


@dataclass(frozen=True, kw_only=True)
class ReminderInput(WorkflowInput):
    request_id: str
    days: int


@dataclass(frozen=True, kw_only=True)
class ErasureOutcomeInput(WorkflowInput):
    request_id: str
    outcome: str


@dataclass(frozen=True, kw_only=True)
class ErasureStep(WorkflowInput):
    record_id: str
    provider: str = ""


@dataclass(frozen=True, kw_only=True)
class RetentionInput(WorkflowInput):
    run_id: str = ""  # set for manual runs (the run row exists already)
    dry_run: bool | None = None  # None: follow privacy.retention_purge


@dataclass(frozen=True, kw_only=True)
class RetentionBatch(WorkflowInput):
    run_id: str
    category: str


@dataclass(frozen=True, kw_only=True)
class VisitInput(WorkflowInput):
    visit_id: str


@dataclass(frozen=True, kw_only=True)
class VisitAlert(WorkflowInput):
    visit_id: str
    escalate: bool


# --- activities: data subject requests ----------------------------------------------------------


@tenant_activity
def dsar_state(input: RequestInput) -> dict[str, Any]:
    from . import dsar

    return dsar.workflow_state(input.request_id)


@tenant_activity
def dsar_reminder(input: ReminderInput) -> str:
    from . import dsar

    return dsar.send_reminder(input.request_id, input.days)


@tenant_activity
def dsar_compile(input: RequestInput) -> dict[str, Any]:
    from . import dsar

    return dsar.compile_for_review(input.request_id)


@tenant_activity
def dsar_deliver(input: RequestInput) -> str:
    from . import dsar

    return dsar.deliver(input.request_id)


@tenant_activity
def dsar_expire_link(input: RequestInput) -> str:
    from . import dsar

    return dsar.expire_link(input.request_id)


@tenant_activity
def dsar_mark_erasing(input: RequestInput) -> str:
    from . import dsar

    return dsar.mark_erasing(input.request_id)


@tenant_activity
def dsar_finish_erasure(input: ErasureOutcomeInput) -> str:
    from . import dsar

    return dsar.finish_erasure(input.request_id, input.outcome)


# --- activities: erasure ------------------------------------------------------------------------


@tenant_activity
def erasure_plan(input: RequestInput) -> dict[str, Any]:
    from . import erasure
    from .models import DataSubjectRequest

    request = DataSubjectRequest.objects.get(pk=input.request_id)
    record = erasure.plan(request.subject_type, request.subject_id, request=request)
    return {
        "record_id": str(record.pk),
        "holds": erasure.check_holds(record),
        "providers": [k for k in erasure.provider_keys() if k not in record.steps_done],
    }


@tenant_activity
def erasure_block(input: ErasureStep) -> str:
    from . import erasure
    from .models import ErasureRecord

    record = ErasureRecord.objects.get(pk=input.record_id)
    erasure.block(record, erasure.check_holds(record))
    return "blocked"


@tenant_activity
def erasure_provider(input: ErasureStep) -> dict[str, Any]:
    from . import erasure
    from .models import ErasureRecord

    return erasure.run_provider(ErasureRecord.objects.get(pk=input.record_id), input.provider)


@tenant_activity
def erasure_files(input: ErasureStep) -> int:
    from . import erasure
    from .models import ErasureRecord

    return erasure.erase_files(ErasureRecord.objects.get(pk=input.record_id))


@tenant_activity
def erasure_revoke(input: ErasureStep) -> int:
    from . import erasure
    from .models import ErasureRecord

    return erasure.revoke_logins(ErasureRecord.objects.get(pk=input.record_id))


@tenant_activity
def erasure_finish(input: ErasureStep) -> str:
    from . import erasure
    from .models import ErasureRecord

    return str(erasure.finish(ErasureRecord.objects.get(pk=input.record_id)).status)


# --- activities: retention ----------------------------------------------------------------------


@tenant_activity
def retention_start(input: RetentionInput) -> dict[str, Any]:
    """The run row: given (manual run) or created once per scheduled workflow."""
    from temporalio import activity

    from tutortrack.tenancy.settings_service import get_setting

    from . import retention
    from .models import RetentionRun

    if input.run_id:
        run = RetentionRun.objects.get(pk=input.run_id)
        return {"run_id": str(run.pk), "dry_run": run.dry_run}
    wid = activity.info().workflow_id or ""
    existing = RetentionRun.objects.filter(workflow_id=wid).first()
    if existing is not None:
        return {"run_id": str(existing.pk), "dry_run": existing.dry_run}
    mode = get_setting("privacy.retention_purge")
    if mode == "off" and input.dry_run is None:
        return {"run_id": "", "dry_run": True}
    dry_run = input.dry_run if input.dry_run is not None else mode != "on"
    run = retention.start_run(dry_run=dry_run, trigger="schedule", workflow_id=wid)
    return {"run_id": str(run.pk), "dry_run": run.dry_run}


@tenant_activity
def retention_report(input: RetentionBatch) -> list[str]:
    from . import retention
    from .models import RetentionRun

    run = RetentionRun.objects.get(pk=input.run_id)
    retention.dry_run_report(run)
    return retention.due_categories(RetentionRun.objects.get(pk=input.run_id))


@tenant_activity
def retention_batch(input: RetentionBatch) -> int:
    from . import retention
    from .models import RetentionRun

    return retention.purge_batch(RetentionRun.objects.get(pk=input.run_id), input.category, BATCH)


@tenant_activity
def retention_finish(input: RetentionBatch) -> dict[str, Any]:
    from . import retention
    from .models import RetentionRun

    run = retention.finish_run(RetentionRun.objects.get(pk=input.run_id))
    return {
        "dry_run": run.dry_run,
        "due": sum(int(v.get("due", 0)) for v in run.report.values()),
        "done": sum(int(v.get("done", 0)) for v in run.report.values()),
    }


# --- activities: lone working -------------------------------------------------------------------


@tenant_activity
def lone_working_state(input: VisitInput) -> dict[str, Any]:
    from . import lone_working

    return lone_working.state(input.visit_id)


@tenant_activity
def lone_working_alert(input: VisitAlert) -> str:
    from . import lone_working

    return lone_working.alert(input.visit_id, escalate=input.escalate)


# --- workflows ----------------------------------------------------------------------------------


@register_workflow(process=ERASURE_PROCESS, task_queue="privacy", cancel_permission=None)
@workflow.defn
class ErasureWorkflow:
    @workflow.run
    async def run(self, input: RequestInput) -> str:
        plan = await workflow.execute_activity(
            erasure_plan, input, start_to_close_timeout=LONG, retry_policy=RETRY
        )
        step = ErasureStep(organisation_id=input.organisation_id, record_id=plan["record_id"])
        if plan["holds"]:
            await workflow.execute_activity(erasure_block, step, start_to_close_timeout=TIMEOUT)
            await report_step(input, "blocked", status="completed")
            return "blocked"
        for key in plan["providers"]:
            await report_step(input, f"erasing:{key}")
            await workflow.execute_activity(
                erasure_provider,
                ErasureStep(
                    organisation_id=input.organisation_id,
                    record_id=plan["record_id"],
                    provider=key,
                ),
                start_to_close_timeout=LONG,
                retry_policy=RETRY,
            )
        await workflow.execute_activity(
            erasure_files, step, start_to_close_timeout=LONG, retry_policy=RETRY
        )
        await workflow.execute_activity(
            erasure_revoke, step, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
        )
        await workflow.execute_activity(
            erasure_finish, step, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
        )
        await report_step(input, "completed", status="completed")
        return "completed"


@register_workflow(
    process=DSAR_PROCESS, task_queue="privacy", cancel_permission="privacy.dsar.manage"
)
@workflow.defn
class DataSubjectRequestWorkflow:
    def __init__(self) -> None:
        self.verified = False
        self.redactions_approved = False
        self.erasure_approved = False
        self.closed = False
        self.changes = 0
        self.seen = 0

    @workflow.signal(name="identity_verified")
    def identity_verified(self) -> None:
        self.verified = True

    @workflow.signal(name="redaction_approved")
    def redaction_approved(self) -> None:
        self.redactions_approved = True

    @workflow.signal(name="erasure_approved")
    def approve_erasure(self) -> None:
        self.erasure_approved = True

    @workflow.signal(name="deadline_changed")
    def deadline_changed(self) -> None:
        self.changes += 1

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.query
    def state(self) -> dict[str, bool]:
        return {
            "verified": self.verified,
            "redactions_approved": self.redactions_approved,
            "erasure_approved": self.erasure_approved,
            "closed": self.closed,
        }

    async def _state(self, input: RequestInput) -> dict[str, Any]:
        return dict(
            await workflow.execute_activity(dsar_state, input, start_to_close_timeout=TIMEOUT)
        )

    async def _wait_for(
        self, input: RequestInput, done: Callable[[], bool], key: str
    ) -> dict[str, Any]:
        """Wait for a decision (signal, or already recorded before the signal arrived) while
        sending the deadline reminders as they fall due."""
        state = await self._state(input)
        for _round in range(MAX_ROUNDS):
            if not state["open"]:
                self.closed = True
                return state
            if done() or state[key]:
                return state
            moment = workflow.now()
            reminders = [
                (datetime.fromisoformat(r["at"]), int(r["days"])) for r in state["reminders"]
            ]
            due = [days for at, days in reminders if at <= moment]
            if due:
                await workflow.execute_activity(
                    dsar_reminder,
                    ReminderInput(
                        organisation_id=input.organisation_id,
                        request_id=input.request_id,
                        days=min(due),  # the latest stage only: no burst of stale reminders
                    ),
                    start_to_close_timeout=TIMEOUT,
                )
                state = await self._state(input)
                continue
            upcoming = [at for at, _days in reminders if at > moment]
            timeout = min(upcoming) - moment if upcoming else None
            self.seen = self.changes
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: done() or self.closed or self.changes != self.seen, timeout=timeout
                )
            state = await self._state(input)
        return state

    async def _finish(self, input: RequestInput, outcome: str) -> str:
        await report_step(input, outcome, status="completed")
        return outcome

    @workflow.run
    async def run(self, input: RequestInput) -> str:
        await report_step(input, "waiting_for_verification")
        state = await self._wait_for(input, lambda: self.verified, "verified")
        if self.closed:
            return await self._finish(input, str(state["status"]))
        await report_step(input, "compiling")
        await workflow.execute_activity(
            dsar_compile, input, start_to_close_timeout=LONG, retry_policy=RETRY
        )
        if state["kind"] == "erasure":
            await report_step(input, "waiting_for_erasure_approval")
            state = await self._wait_for(input, lambda: self.erasure_approved, "erasure_approved")
            if self.closed:
                return await self._finish(input, str(state["status"]))
            await workflow.execute_activity(
                dsar_mark_erasing, input, start_to_close_timeout=TIMEOUT
            )
            await report_step(input, "erasing")
            outcome = await workflow.execute_child_workflow(
                ErasureWorkflow.run,
                input,
                id=erasure_workflow_id(input.organisation_id, input.request_id),
            )
            result = await workflow.execute_activity(
                dsar_finish_erasure,
                ErasureOutcomeInput(
                    organisation_id=input.organisation_id,
                    request_id=input.request_id,
                    outcome=str(outcome),
                ),
                start_to_close_timeout=TIMEOUT,
            )
            return await self._finish(input, str(result))
        await report_step(input, "waiting_for_review")
        state = await self._wait_for(input, lambda: self.redactions_approved, "redactions_approved")
        if self.closed:
            return await self._finish(input, str(state["status"]))
        expires = await workflow.execute_activity(
            dsar_deliver, input, start_to_close_timeout=LONG, retry_policy=RETRY
        )
        await report_step(input, "delivered")
        left = datetime.fromisoformat(str(expires)) - workflow.now()
        if left > timedelta(0):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.closed, timeout=left)
        result = await workflow.execute_activity(
            dsar_expire_link, input, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
        )
        return await self._finish(input, str(result))


@register_workflow(process=RETENTION_PROCESS, task_queue="privacy", cancel_permission=None)
@workflow.defn
class RetentionPurgeWorkflow:
    @workflow.run
    async def run(self, input: RetentionInput) -> str:
        started = await workflow.execute_activity(
            retention_start, input, start_to_close_timeout=TIMEOUT
        )
        if not started["run_id"]:
            await report_step(input, "off", status="completed")
            return "off"
        batch = RetentionBatch(
            organisation_id=input.organisation_id, run_id=started["run_id"], category=""
        )
        await report_step(input, "dry_run")
        due = await workflow.execute_activity(
            retention_report, batch, start_to_close_timeout=LONG, retry_policy=RETRY
        )
        if not started["dry_run"]:
            for category in due:
                await report_step(input, f"purging:{category}")
                for _batch in range(MAX_BATCHES):
                    done = await workflow.execute_activity(
                        retention_batch,
                        RetentionBatch(
                            organisation_id=input.organisation_id,
                            run_id=started["run_id"],
                            category=category,
                        ),
                        start_to_close_timeout=LONG,
                        retry_policy=RETRY,
                    )
                    if int(done) < BATCH:
                        break
        totals = await workflow.execute_activity(
            retention_finish, batch, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
        )
        outcome = f"dry_run:{totals['due']}" if totals["dry_run"] else f"purged:{totals['done']}"
        await report_step(input, outcome, status="completed")
        return outcome


@register_workflow(
    process=LONE_WORKING_PROCESS,
    task_queue="privacy",
    cancel_permission="safeguarding.lone_working.monitor",
)
@workflow.defn
class LoneWorkingWorkflow:
    def __init__(self) -> None:
        self.done = False

    @workflow.signal(name="checked_out")
    def checked_out(self) -> None:
        self.done = True

    @workflow.signal(name="resolved")
    def resolved(self) -> None:
        self.done = True

    @workflow.query
    def state(self) -> dict[str, bool]:
        return {"done": self.done}

    async def _until(self, moment: datetime) -> bool:
        """Wait until ``moment``; True if the visit ended first."""
        left = moment - workflow.now()
        if left > timedelta(0) and not self.done:
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(lambda: self.done, timeout=left)
        return self.done

    async def _alert(self, input: VisitInput, *, escalate: bool) -> str:
        return str(
            await workflow.execute_activity(
                lone_working_alert,
                VisitAlert(
                    organisation_id=input.organisation_id,
                    visit_id=input.visit_id,
                    escalate=escalate,
                ),
                start_to_close_timeout=TIMEOUT,
                retry_policy=RETRY,
            )
        )

    @workflow.run
    async def run(self, input: VisitInput) -> str:
        state = await workflow.execute_activity(
            lone_working_state, input, start_to_close_timeout=TIMEOUT
        )
        if state["done"]:
            return await self._end(input, str(state["status"]))
        await report_step(input, "checked_in")
        if await self._until(datetime.fromisoformat(state["alert_at"])):
            return await self._end(input, "checked_out")
        if await self._alert(input, escalate=False) != "overdue":
            return await self._end(input, "checked_out")
        await report_step(input, "overdue")
        if await self._until(datetime.fromisoformat(state["escalate_at"])):
            return await self._end(input, "resolved")
        await self._alert(input, escalate=True)
        await report_step(input, "escalated")
        try:
            await workflow.wait_condition(lambda: self.done, timeout=timedelta(days=7))
        except TimeoutError:
            return await self._end(input, "unresolved")
        return await self._end(input, "resolved")

    async def _end(self, input: VisitInput, outcome: str) -> str:
        await report_step(input, outcome, status="completed")
        return outcome
