"""Temporal workflows for accounting sync (E23-TW1).

* ``AccountingSyncWorkflow`` ``acct-sync:{org}:{type}:{id}:{event}``: started by the
  financial event (``invoice.issued``, ``payment.succeeded``...). It plans the record
  (``plan_sync``), syncs what it depends on first as child workflows (contact → invoice →
  payment), then pushes it with rate-limit-aware retries (a 429 or our own per-company
  budget sets the next retry delay). A record that needs a person (archived account,
  missing mapping, locked period) is shown on the sync dashboard and the workflow waits
  for ``retry`` (after re-mapping) or ``skip``, for up to 30 days. Child workflows don't
  wait: their parent does. Replaces the ``AccountingSyncJob`` queue and retry job.
* ``AccountingBackfillWorkflow`` ``acct-backfill:{org}:{connection}:{run}``: started when
  sync is switched on with a backfill date. Pages through history in batches with a
  checkpoint and a pause between batches (pacing); continues as new every 100 batches and
  can be cancelled with ``cancel``.
* ``AccountingDailyWorkflow``: a per-organisation Temporal Schedule (03:30 local) that
  posts yesterday's summary journal (summary mode), checks recently synced invoice
  balances against the ledger, and sends finance the error digest.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from tutortrack.core.workflows import WorkflowInput, register_workflow, tenant_activity
from tutortrack.core.workflows.links import report_step

SYNC_PROCESS = "acct-sync"
BACKFILL_PROCESS = "acct-backfill"
DAILY_PROCESS = "acct-daily"
QUEUE = "integrations"
QUICK = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)
PUSH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,
    non_retryable_error_types=["AuthError", "ConfigurationError", "LedgerRejected"],
)
BATCH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=10,
)
RETRY_WAIT_DAYS = 30


@dataclass(frozen=True, kw_only=True)
class SyncInput(WorkflowInput):
    object_type: str
    object_id: str
    wait_for_retry: bool = True
    retry_wait_days: int = RETRY_WAIT_DAYS


@dataclass(frozen=True, kw_only=True)
class FailureInput(WorkflowInput):
    object_type: str
    object_id: str
    error: str = ""


@dataclass(frozen=True, kw_only=True)
class BackfillInput(WorkflowInput):
    connection_id: str
    since: str  # ISO date
    checkpoint: dict[str, Any] = field(default_factory=dict)
    batch_size: int = 25
    pace_seconds: int = 5
    max_batches: int = 100


@dataclass(frozen=True, kw_only=True)
class DailyInput(WorkflowInput):
    connection_id: str
    day: str = ""  # ISO date; empty = yesterday


def _rate_limited(exc: Any) -> ApplicationError:
    """Hand the provider's (or our budget's) wait to Temporal as the next retry delay."""
    return ApplicationError(
        str(exc),
        type="RateLimited",
        next_retry_delay=timedelta(seconds=max(float(getattr(exc, "retry_after", 60)), 1)),
    )


# --- activities ----------------------------------------------------------------------------------


@tenant_activity
def plan_sync(input: SyncInput) -> dict[str, Any]:
    from . import services

    return services.plan(
        input.object_type, input.object_id, workflow_id=activity.info().workflow_id or ""
    )


@tenant_activity
def push_record(input: SyncInput) -> str:
    from tutortrack.integrations.providers import RateLimited

    from . import services

    try:
        return services.sync(input.object_type, input.object_id)
    except RateLimited as exc:
        raise _rate_limited(exc) from exc


@tenant_activity
def record_blocked(input: SyncInput) -> bool:
    from . import services

    services.record_blocked(input.object_type, input.object_id)
    return True


@tenant_activity
def record_failure(input: FailureInput) -> bool:
    from . import services

    services.final_failure(input.object_type, input.object_id, input.error)
    return True


@tenant_activity
def backfill_step(input: BackfillInput) -> dict[str, Any]:
    from tutortrack.integrations.providers import RateLimited

    from . import services

    try:
        return services.backfill_batch(
            input.connection_id, date.fromisoformat(input.since), input.checkpoint, input.batch_size
        )
    except RateLimited as exc:
        raise _rate_limited(exc) from exc


@tenant_activity
def backfill_finished(input: BackfillInput) -> bool:
    from django.db import transaction

    from .models import AccountingConnection

    with transaction.atomic():
        conn = AccountingConnection.objects.select_for_update().get(pk=input.connection_id)
        if conn.backfill.get("status") == "running":
            conn.backfill = {**conn.backfill, "status": "cancelled"}
            conn.save(update_fields=["backfill", "updated_at"])
    return True


@tenant_activity
def run_daily(input: DailyInput) -> dict[str, Any]:
    from tutortrack.integrations.providers import RateLimited

    from . import services

    try:
        return services.daily(
            input.connection_id, date.fromisoformat(input.day) if input.day else None
        )
    except RateLimited as exc:
        raise _rate_limited(exc) from exc


# --- workflows -----------------------------------------------------------------------------------


@register_workflow(
    process=SYNC_PROCESS, task_queue=QUEUE, cancel_permission="integrations.accounting.manage"
)
@workflow.defn
class AccountingSyncWorkflow:
    def __init__(self) -> None:
        self.retry_requested = False
        self.skip_requested = False
        self.status = "starting"

    @workflow.signal(name="retry")
    def on_retry(self) -> None:
        self.retry_requested = True

    @workflow.signal(name="skip")
    def on_skip(self) -> None:
        self.skip_requested = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {"status": self.status}

    async def _attempt(self, input: SyncInput, attempt: int) -> str:
        plan = await workflow.execute_activity(
            plan_sync, input, start_to_close_timeout=timedelta(minutes=1), retry_policy=QUICK
        )
        if plan["status"] != "ready":
            return str(plan["status"])
        blocked = False
        for object_type, object_id in plan["prerequisites"]:
            result = await workflow.execute_child_workflow(
                AccountingSyncWorkflow.run,
                SyncInput(
                    organisation_id=input.organisation_id,
                    object_type=object_type,
                    object_id=object_id,
                    wait_for_retry=False,
                ),
                id=f"{workflow.info().workflow_id}/{attempt}/{object_type}:{object_id}",
            )
            blocked = blocked or result == "error"
        if not plan["push"]:
            return "error" if blocked else "synced"
        if blocked:
            await workflow.execute_activity(
                record_blocked, input, start_to_close_timeout=timedelta(minutes=1)
            )
            return "error"
        try:
            return str(
                await workflow.execute_activity(
                    push_record,
                    input,
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=PUSH_RETRY,
                )
            )
        except ActivityError as exc:
            cause = exc.cause if exc.cause is not None else exc
            await workflow.execute_activity(
                record_failure,
                FailureInput(
                    organisation_id=input.organisation_id,
                    object_type=input.object_type,
                    object_id=input.object_id,
                    error=str(cause)[:300],
                ),
                start_to_close_timeout=timedelta(minutes=1),
            )
            return "error"

    @workflow.run
    async def run(self, input: SyncInput) -> str:
        attempt = 0
        while True:
            self.status = await self._attempt(input, attempt)
            if self.status != "error" or not input.wait_for_retry:
                if input.wait_for_retry:
                    await report_step(input, self.status, status="completed")
                return self.status
            await report_step(input, "needs_attention")
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.retry_requested or self.skip_requested,
                    timeout=timedelta(days=input.retry_wait_days),
                )
            if self.skip_requested:
                await report_step(input, "skipped", status="completed")
                return "skipped"
            if not self.retry_requested:
                await report_step(input, "gave_up", status="completed")
                return "error"
            self.retry_requested = False
            attempt += 1
            await report_step(input, "retrying")


@register_workflow(
    process=BACKFILL_PROCESS, task_queue=QUEUE, cancel_permission="integrations.accounting.manage"
)
@workflow.defn
class AccountingBackfillWorkflow:
    def __init__(self) -> None:
        self.cancelled = False
        self.progress: dict[str, int] = {"synced": 0, "errors": 0, "skipped": 0, "batches": 0}

    @workflow.signal(name="cancel")
    def on_cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, int]:
        return self.progress

    @workflow.run
    async def run(self, input: BackfillInput) -> dict[str, int]:
        checkpoint = dict(input.checkpoint)
        batches = 0
        if not checkpoint:
            await report_step(input, "backfilling")
        while not self.cancelled:
            result = await workflow.execute_activity(
                backfill_step,
                replace(input, checkpoint=checkpoint),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=BATCH_RETRY,
            )
            for key in ("synced", "errors", "skipped"):
                self.progress[key] += int(result.get(key, 0))
            batches += 1
            self.progress["batches"] = batches
            checkpoint = dict(result["checkpoint"])
            if result["done"]:
                await report_step(input, "done", status="completed")
                return self.progress
            if batches >= input.max_batches:
                workflow.continue_as_new(replace(input, checkpoint=checkpoint))
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda: self.cancelled, timeout=timedelta(seconds=input.pace_seconds)
                )
        await workflow.execute_activity(
            backfill_finished, input, start_to_close_timeout=timedelta(minutes=1)
        )
        await report_step(input, "cancelled", status="completed")
        return self.progress


@register_workflow(process=DAILY_PROCESS, task_queue=QUEUE, cancel_permission=None)
@workflow.defn
class AccountingDailyWorkflow:
    @workflow.run
    async def run(self, input: DailyInput) -> dict[str, Any]:
        result: dict[str, Any] = await workflow.execute_activity(
            run_daily,
            input,
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=BATCH_RETRY,
        )
        return result


def ensure_daily_schedule(organisation_id: Any, connection_id: Any) -> str:
    """The organisation's daily accounting run, at 03:30 in its timezone."""
    from tutortrack.core.context import tenant_context
    from tutortrack.core.workflows.schedules import ensure_schedule
    from tutortrack.tenancy.models import Organisation

    from . import services

    with tenant_context(organisation_id):
        org = Organisation.objects.get(pk=organisation_id)
        sid = ensure_schedule(
            process=DAILY_PROCESS,
            workflow=AccountingDailyWorkflow,
            input=DailyInput(
                organisation_id=str(organisation_id), connection_id=str(connection_id)
            ),
            cron=["30 3 * * *"],
            timezone=org.timezone,
            parts=(connection_id,),
        )
        services.record_schedule(connection_id, sid)
    return sid
