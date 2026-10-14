"""``BackgroundCheckWorkflow`` ``bg-check:{org}:{check}`` (E18-T11).

Initiate the check at the provider → wait for ``updated`` (webhook, staff outcome) or the
provider's polling interval, whichever comes first, and fetch its state → until it
completes, is cancelled (``cancel`` signal) or the tutor hasn't finished it within
``compliance.check_invite_days`` (the invitation expires). DBS Update Service checks are
then re-run every ``compliance.dbs_update_recheck_days``; new information ends the loop.

Deterministic: the deadline uses ``workflow.now()``; every side effect is an activity
calling ``recruitment.background_checks``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
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
CHECK_PROCESS = "bg-check"
OPEN = ("requested", "invited", "in_progress")
MAX_RECHECKS = 20


def check_workflow_id(org: object, check_id: object) -> str:
    return workflow_id(CHECK_PROCESS, org, check_id)


@dataclass(frozen=True, kw_only=True)
class BackgroundCheckInput(WorkflowInput):
    check_id: str


@tenant_activity
def initiate_check(input: BackgroundCheckInput) -> str:
    from . import background_checks

    return str(background_checks.initiate(input.check_id))


@tenant_activity
def check_settings(input: BackgroundCheckInput) -> dict[str, Any]:
    from . import background_checks

    return background_checks.settings_for(input.check_id)


@tenant_activity
def poll_check(input: BackgroundCheckInput) -> str:
    from . import background_checks

    return str(background_checks.poll(input.check_id))


@tenant_activity
def expire_check(input: BackgroundCheckInput) -> str:
    from . import background_checks

    return str(background_checks.expire(input.check_id))


@tenant_activity
def recheck_update_service(input: BackgroundCheckInput) -> str:
    from . import background_checks

    return str(background_checks.recheck(input.check_id))


@register_workflow(process=CHECK_PROCESS, task_queue="default", cancel_permission=None)
@workflow.defn
class BackgroundCheckWorkflow:
    def __init__(self) -> None:
        self.updates = 0
        self.cancelled = False
        self.step = "starting"

    @workflow.signal(name="updated")
    def update(self) -> None:
        self.updates += 1

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "updates": self.updates, "cancelled": self.cancelled}

    @workflow.run
    async def run(self, input: BackgroundCheckInput) -> str:
        status = await workflow.execute_activity(
            initiate_check, input, start_to_close_timeout=TIMEOUT
        )
        if status == "failed":
            await report_step(input, "failed", status="completed")
            return "failed"
        config = await workflow.execute_activity(
            check_settings, input, start_to_close_timeout=TIMEOUT
        )
        deadline = workflow.now() + timedelta(days=int(config["invite_days"]))
        poll_every = timedelta(hours=int(config["poll_hours"]))
        self.step = "waiting"
        await report_step(input, "waiting")
        while status in OPEN:
            seen = self.updates
            wait = min(poll_every, max(deadline - workflow.now(), timedelta(seconds=1)))
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(
                    lambda seen=seen: self.updates != seen or self.cancelled,  # type: ignore[misc]
                    timeout=wait,
                )
            if self.cancelled:
                await report_step(input, "cancelled", status="completed")
                return "cancelled"
            status = await workflow.execute_activity(
                poll_check, input, start_to_close_timeout=TIMEOUT
            )
            if status in OPEN and workflow.now() >= deadline and status != "in_progress":
                status = await workflow.execute_activity(
                    expire_check, input, start_to_close_timeout=TIMEOUT
                )
        result = status
        recheck_days = int(config["recheck_days"])
        if status == "completed" and recheck_days:
            self.step = "monitoring"
            await report_step(input, "monitoring")
            for _ in range(MAX_RECHECKS):
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(
                        lambda: self.cancelled, timeout=timedelta(days=recheck_days)
                    )
                if self.cancelled:
                    break
                outcome = await workflow.execute_activity(
                    recheck_update_service, input, start_to_close_timeout=TIMEOUT
                )
                if outcome not in ("clear", "unavailable"):
                    result = f"completed:{outcome}"
                    break
        self.step = result
        await report_step(input, result, status="completed")
        return result
