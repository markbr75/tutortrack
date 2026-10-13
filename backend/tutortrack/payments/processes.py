"""Payment workflows (E11-TW1, E32).

* ``PaymentCollectionWorkflow`` ``collect:{org}:{invoice}``: started for auto-pay
  clients by ``invoice.issued`` (or ``POST /invoices/{id}/collect``). Charges the default
  method; a direct debit waits for the ``confirmed``/``failed`` webhook signal; failures
  retry on the setting's schedule (cards +3 and +5 days, debits once); every failure tells
  the client (pay-now link) and the last one tells staff. The running workflow is the
  invoice's collection lock (FR-11-2). ``paid`` (paid some other way) ends it.
* ``DisputeWorkflow`` ``dispute:{org}:{dispute}``: started by ``payment.disputed``;
  reminders 3 days and 1 day before the evidence deadline until ``closed``.

Phase 2:

* ``ProviderMigrationWorkflow`` ``provider-migration:{org}:{migration}``: moves a client
  to another provider (FR-11-2): emails a setup link → waits for ``method_added`` (a
  reminder link after 7 days, gives up after 21) → makes it the default → waits (daily
  checks, up to 14 days) until nothing is being collected with the old method → cancels
  the old mandate or card. ``cancel`` stops it while waiting.
* ``BankFeedSyncWorkflow``: started daily by a **Temporal Schedule** per Open Banking
  connection; pulls new bank transactions and suggests matches.
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


MIGRATION_PROCESS = "provider-migration"
BANK_FEED_PROCESS = "bank-feed"
LINK_REMINDER = timedelta(days=7)
LINK_EXPIRY = timedelta(days=21)
SETTLE_CHECKS = 14


def migration_workflow_id(organisation_id: object, migration_id: object) -> str:
    return workflow_id(MIGRATION_PROCESS, organisation_id, migration_id)


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


# --- Phase 2: provider migration and bank feeds ------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class MigrationInput(WorkflowInput):
    migration_id: str


@dataclass(frozen=True, kw_only=True)
class SwitchInput(WorkflowInput):
    migration_id: str
    method_id: str


@dataclass(frozen=True, kw_only=True)
class FinishInput(WorkflowInput):
    migration_id: str
    status: str


@dataclass(frozen=True, kw_only=True)
class BankFeedInput(WorkflowInput):
    connection_id: str


@tenant_activity
def send_migration_link(input: MigrationInput) -> bool:
    from . import provider_migration

    return provider_migration.send_link(input.migration_id, key=idempotency_key())


@tenant_activity
def switch_migration_default(input: SwitchInput) -> bool:
    from . import provider_migration

    return provider_migration.switch_default(input.migration_id, input.method_id)


@tenant_activity
def migration_in_flight(input: MigrationInput) -> int:
    from . import provider_migration

    return provider_migration.in_flight(input.migration_id)


@tenant_activity
def finish_migration(input: FinishInput) -> str:
    from . import provider_migration

    return provider_migration.finish(input.migration_id, input.status)


@tenant_activity
def sync_bank_feed(input: BankFeedInput) -> int:
    from . import bank

    statement = bank.sync_feed(input.connection_id)
    return int((statement.stats or {}).get("new", 0)) if statement else 0


@register_workflow(
    process=MIGRATION_PROCESS, task_queue="billing", cancel_permission="payments.autopay.manage"
)
@workflow.defn
class ProviderMigrationWorkflow:
    def __init__(self) -> None:
        self.method_id = ""
        self.cancelled = False
        self.step = "waiting"

    @workflow.signal(name="method_added")
    def method_added(self, method_id: str) -> None:
        self.method_id = method_id

    @workflow.signal(name="cancel")
    def cancel(self) -> None:
        self.cancelled = True

    @workflow.query
    def state(self) -> dict[str, Any]:
        return {"step": self.step, "method_id": self.method_id}

    def _woken(self) -> bool:
        return bool(self.method_id) or self.cancelled

    async def _finish(self, input: MigrationInput, status: str) -> str:
        await workflow.execute_activity(
            finish_migration,
            FinishInput(
                organisation_id=input.organisation_id,
                migration_id=input.migration_id,
                status=status,
            ),
            start_to_close_timeout=TIMEOUT,
        )
        self.step = status
        await report_step(input, status, status="completed")
        return status

    @workflow.run
    async def run(self, input: MigrationInput) -> str:
        await report_step(input, self.step)
        await workflow.execute_activity(send_migration_link, input, start_to_close_timeout=TIMEOUT)
        waited = timedelta(0)
        for wait in (LINK_REMINDER, LINK_EXPIRY - LINK_REMINDER):
            with contextlib.suppress(TimeoutError):
                await workflow.wait_condition(self._woken, timeout=wait)
            if self._woken():
                break
            waited += wait
            if waited < LINK_EXPIRY:  # remind with a fresh link
                await workflow.execute_activity(
                    send_migration_link, input, start_to_close_timeout=TIMEOUT
                )
        if self.cancelled:
            return await self._finish(input, "cancelled")
        if not self.method_id:
            return await self._finish(input, "expired")
        switched = await workflow.execute_activity(
            switch_migration_default,
            SwitchInput(
                organisation_id=input.organisation_id,
                migration_id=input.migration_id,
                method_id=self.method_id,
            ),
            start_to_close_timeout=TIMEOUT,
        )
        if not switched:
            return await self._finish(input, "cancelled")
        self.step = "settling"
        await report_step(input, self.step)
        for _check in range(SETTLE_CHECKS):
            busy = await workflow.execute_activity(
                migration_in_flight, input, start_to_close_timeout=TIMEOUT
            )
            if not busy:
                break
            await workflow.sleep(timedelta(days=1))
        return await self._finish(input, "completed")


@register_workflow(process=BANK_FEED_PROCESS, task_queue="billing", cancel_permission=None)
@workflow.defn
class BankFeedSyncWorkflow:
    @workflow.run
    async def run(self, input: BankFeedInput) -> int:
        new = await workflow.execute_activity(
            sync_bank_feed, input, start_to_close_timeout=timedelta(minutes=10)
        )
        await report_step(input, f"synced:{new}", status="completed")
        return int(new)
