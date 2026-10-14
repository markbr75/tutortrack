"""``XeroPayrollSyncWorkflow`` ``xero-payroll:{org}:{pay_run}:{attempt}`` (E23-T10).

Started by ``pay_run.approved`` when Xero Payroll is connected and the run has employed
tutors' hours, or by finance retrying from the accounting page. The sync activity is
idempotent and retried with backoff through Xero's rate limits and outages (up to about
two hours); a sync that keeps failing is marked failed for the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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

TIMEOUT = timedelta(minutes=10)
PAYROLL_PROCESS = "xero-payroll"
RETRY = RetryPolicy(
    initial_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=30),
    maximum_attempts=7,
)


def payroll_sync_workflow_id(org: object, pay_run_id: object, attempt: object = 0) -> str:
    return workflow_id(PAYROLL_PROCESS, org, pay_run_id, attempt)


@dataclass(frozen=True, kw_only=True)
class PayrollSyncInput(WorkflowInput):
    pay_run_id: str


@tenant_activity
def sync_xero_payroll(input: PayrollSyncInput) -> str:
    from . import payroll_sync

    return str(payroll_sync.sync_pay_run(input.pay_run_id))


@tenant_activity
def fail_xero_payroll(input: PayrollSyncInput) -> None:
    from . import payroll_sync

    payroll_sync.mark_failed(input.pay_run_id, "Xero Payroll kept failing; retry later.")


@register_workflow(process=PAYROLL_PROCESS, task_queue="integrations", cancel_permission=None)
@workflow.defn
class XeroPayrollSyncWorkflow:
    @workflow.run
    async def run(self, input: PayrollSyncInput) -> str:
        try:
            result = await workflow.execute_activity(
                sync_xero_payroll, input, start_to_close_timeout=TIMEOUT, retry_policy=RETRY
            )
        except ActivityError:
            await workflow.execute_activity(
                fail_xero_payroll, input, start_to_close_timeout=TIMEOUT
            )
            result = "error"
        await report_step(input, result, status="completed")
        return result
