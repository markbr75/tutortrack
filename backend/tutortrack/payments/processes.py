"""Payment workflows (E11-TW1, E32).

* ``PaymentCollectionWorkflow`` ``collect:{org}:{invoice}``: started for auto-pay
  clients by ``invoice.issued`` (or ``POST /invoices/{id}/collect``). Charges the default
  method; a direct debit waits for the ``confirmed``/``failed`` webhook signal; failures
  retry on the setting's schedule (cards +3 and +5 days, debits once); every failure tells
  the client (pay-now link) and the last one tells staff. The running workflow is the
  invoice's collection lock (FR-11-2). ``paid`` (paid some other way) ends it.
* ``DisputeWorkflow`` ``dispute:{org}:{dispute}``: started by ``payment.disputed``;
  reminders 3 days and 1 day before the evidence deadline until ``closed``.

Provider migration (moving clients between GoCardless and Stripe) arrives with the
GoCardless provider in Phase 2; choosing the default method is the switch today.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

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

COLLECT_PROCESS = "collect"
DISPUTE_PROCESS = "dispute"
TIMEOUT = timedelta(minutes=5)
DEBIT_WAIT = timedelta(days=10)


def collect_workflow_id(organisation_id: object, invoice_id: object) -> str:
    return workflow_id(COLLECT_PROCESS, organisation_id, invoice_id)


def dispute_workflow_id(organisation_id: object, dispute_id: object) -> str:
    return workflow_id(DISPUTE_PROCESS, organisation_id, dispute_id)


@dataclass(frozen=True, kw_only=True)
class CollectInput(WorkflowInput):
    invoice_id: str


@dataclass(frozen=True, kw_only=True)
class AttemptInput(WorkflowInput):
    invoice_id: str
    number: int
    final: bool = False


@dataclass(frozen=True, kw_only=True)
class DisputeInput(WorkflowInput):
    dispute_id: str
    evidence_due_by: str  # ISO datetime or ""


@tenant_activity
def charge_invoice(input: AttemptInput) -> str:
    from . import services

    return services.attempt_collection(input.invoice_id, input.number, idempotency_key())


@tenant_activity
def is_debit(input: CollectInput) -> bool:
    from . import services

    return services.method_is_debit(input.invoice_id)


@tenant_activity
def report_failure(input: AttemptInput) -> None:
    from . import services

    services.collection_failed(
        input.invoice_id, input.number, final=input.final, dedupe_key=idempotency_key()
    )


@tenant_activity
def remind_dispute(input: DisputeInput) -> bool:
    from django.db import transaction

    from tutortrack.core.events import publish

    from .events import DisputeEvidenceDue
    from .models import Dispute

    dispute = Dispute.objects.select_related("payment").filter(pk=input.dispute_id).first()
    if dispute is None or dispute.closed_at:
        return False
    with transaction.atomic():
        publish(
            DisputeEvidenceDue(
                subject_id=dispute.payment_id,
                client_id=str(dispute.payment.client_id),
                amount=dispute.amount.to_dict(),
                dispute_id=str(dispute.pk),
                evidence_due_by=input.evidence_due_by or None,
            ),
            dedupe_key=idempotency_key(),
        )
    return True


@register_workflow(
    process=COLLECT_PROCESS, task_queue="billing", cancel_permission="payments.payment.record"
)
@workflow.defn
class PaymentCollectionWorkflow:
    def __init__(self) -> None:
        self.outcome = ""  # "confirmed" | "failed" (debit webhooks)
        self.paid = False
        self.attempts: list[str] = []

    @workflow.signal(name="confirmed")
    def confirmed(self) -> None:
        self.outcome = "confirmed"

    @workflow.signal(name="failed")
    def failed(self) -> None:
        self.outcome = "failed"

    @workflow.signal(name="paid")
    def paid_elsewhere(self) -> None:
        self.paid = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"attempts": self.attempts, "paid": self.paid}

    @workflow.run
    async def run(self, input: CollectInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(
                organisation_id=input.organisation_id,
                keys=["payments.card_retry_days", "payments.debit_retry_days"],
            ),
            start_to_close_timeout=TIMEOUT,
        )
        debit = await workflow.execute_activity(is_debit, input, start_to_close_timeout=TIMEOUT)
        key = "payments.debit_retry_days" if debit else "payments.card_retry_days"
        retries = [int(d) for d in settings.get(key) or []]
        waits = [0, *retries]
        for number, days in enumerate(waits, start=1):
            if days:
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(lambda: self.paid, timeout=timedelta(days=days))
            if self.paid:
                break
            await report_step(input, f"attempt_{number}")
            attempt = AttemptInput(
                organisation_id=input.organisation_id, invoice_id=input.invoice_id, number=number
            )
            status = await workflow.execute_activity(
                charge_invoice, attempt, start_to_close_timeout=TIMEOUT
            )
            if status == "processing":
                self.outcome = ""
                with contextlib.suppress(TimeoutError):
                    await workflow.wait_condition(
                        lambda: bool(self.outcome) or self.paid, timeout=DEBIT_WAIT
                    )
                status = "succeeded" if self.outcome == "confirmed" or self.paid else "failed"
            self.attempts.append(status)
            if status in {"succeeded", "settled", "no_method"}:
                break
            final = number == len(waits)
            await workflow.execute_activity(
                report_failure,
                AttemptInput(
                    organisation_id=input.organisation_id,
                    invoice_id=input.invoice_id,
                    number=number,
                    final=final,
                ),
                start_to_close_timeout=TIMEOUT,
            )
        result = self.attempts[-1] if self.attempts else "paid"
        await report_step(input, result, status="completed")
        return result


@register_workflow(process=DISPUTE_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class DisputeWorkflow:
    def __init__(self) -> None:
        self.closed = False

    @workflow.signal(name="closed")
    def close(self) -> None:
        self.closed = True

    @workflow.run
    async def run(self, input: DisputeInput) -> str:
        reminders = 0
        if input.evidence_due_by:
            due = datetime.fromisoformat(input.evidence_due_by)
            for before in (timedelta(days=3), timedelta(days=1)):
                delay = due - before - workflow.now()
                if delay > timedelta(0):
                    with contextlib.suppress(TimeoutError):
                        await workflow.wait_condition(lambda: self.closed, timeout=delay)
                if self.closed:
                    break
                if await workflow.execute_activity(
                    remind_dispute, input, start_to_close_timeout=TIMEOUT
                ):
                    reminders += 1
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(lambda: self.closed, timeout=timedelta(days=120))
        await report_step(input, "closed" if self.closed else "expired", status="completed")
        return f"reminders:{reminders}"
