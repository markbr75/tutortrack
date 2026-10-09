"""``OrganisationClosureWorkflow`` (E02-TW1, FR-02-8, built with E32).

Started by ``organisation.closed`` (bridge in ``tenancy/handlers.py``):

1. pause the organisation's schedules and request a data export (E28 handles
   ``organisation.export_requested``),
2. email the owners what happens next,
3. wait the grace period (``privacy.closure_grace_days``, 30 by default); a ``reactivate``
   signal (platform staff) reopens the account instead,
4. delete the schedules and publish ``organisation.deletion_due``; E29's retention purge
   deletes the data.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

from django.db import transaction
from temporalio import workflow

from tutortrack.core import audit
from tutortrack.core.events import DomainEvent, publish
from tutortrack.core.workflows import (
    WorkflowInput,
    idempotency_key,
    register_workflow,
    tenant_activity,
    workflow_id,
)
from tutortrack.core.workflows.links import report_step
from tutortrack.core.workflows.timers import SettingsSnapshotInput, snapshot_settings

PROCESS = "org-closure"
GRACE_SETTING = "privacy.closure_grace_days"  # registered in tenancy/org_settings.py


def closure_workflow_id(organisation_id: object) -> str:
    return workflow_id(PROCESS, organisation_id)


# --- events -----------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OrganisationExportRequested(DomainEvent):
    event_type: ClassVar[str] = "organisation.export_requested"
    subject_type: ClassVar[str] = "organisation"

    reason: str


@dataclass(frozen=True, kw_only=True)
class OrganisationDeletionDue(DomainEvent):
    event_type: ClassVar[str] = "organisation.deletion_due"
    subject_type: ClassVar[str] = "organisation"


# --- activities -------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ClosureInput(WorkflowInput):
    export_requested: bool = True


@tenant_activity
def prepare_closure(input: ClosureInput) -> None:
    from tutortrack.core.workflows.schedules import pause_organisation_schedules

    pause_organisation_schedules(input.organisation_id, note="organisation closed")
    if input.export_requested:
        with transaction.atomic():
            publish(
                OrganisationExportRequested(subject_id=input.organisation_id, reason="closure"),
                dedupe_key=idempotency_key(),
            )


@tenant_activity
def notify_closure(input: ClosureInput) -> None:
    from .tasks import send_closure_notice

    send_closure_notice(organisation_id=input.organisation_id)


@tenant_activity
def reopen_organisation(input: ClosureInput) -> None:
    from tutortrack.core.workflows.schedules import unpause_organisation_schedules

    from .events import OrganisationReactivated
    from .models import Organisation

    with transaction.atomic():
        org = Organisation.objects.select_for_update().get(pk=input.organisation_id)
        if org.status == Organisation.Status.CANCELLED:
            with audit.track(org, action="reopen"):
                org.status = Organisation.Status.ACTIVE
                org.closed_at = None
                org.save(update_fields=["status", "closed_at", "updated_at"])
            publish(
                OrganisationReactivated(subject_id=org.pk),
                organisation_id=org.pk,
                dedupe_key=idempotency_key(),
            )
    unpause_organisation_schedules(input.organisation_id, note="organisation reopened")


@tenant_activity
def finalise_closure(input: ClosureInput) -> None:
    from tutortrack.core.workflows.schedules import delete_organisation_schedules

    delete_organisation_schedules(input.organisation_id)
    with transaction.atomic():
        publish(
            OrganisationDeletionDue(subject_id=input.organisation_id),
            dedupe_key=idempotency_key(),
        )


# --- workflow ---------------------------------------------------------------------------------

TIMEOUT = timedelta(minutes=5)


@register_workflow(process=PROCESS, task_queue="privacy", cancel_permission=None)
@workflow.defn
class OrganisationClosureWorkflow:
    def __init__(self) -> None:
        self.reactivate_requested = False
        self.step = "starting"
        self.deletion_due_at = ""
        self.grace_days = 0

    @workflow.signal
    def reactivate(self) -> None:
        self.reactivate_requested = True

    @workflow.query
    def state(self) -> dict[str, str]:
        return {
            "step": self.step,
            "deletion_due_at": self.deletion_due_at,
            "grace_days": str(self.grace_days),
        }

    @workflow.run
    async def run(self, input: ClosureInput) -> str:
        settings = await workflow.execute_activity(
            snapshot_settings,
            SettingsSnapshotInput(organisation_id=input.organisation_id, keys=[GRACE_SETTING]),
            start_to_close_timeout=TIMEOUT,
        )
        self.grace_days = int(settings.get(GRACE_SETTING, 30))
        grace = timedelta(days=self.grace_days)
        self.deletion_due_at = (workflow.now() + grace).isoformat()

        self.step = "exporting"
        await report_step(input, self.step)
        await workflow.execute_activity(prepare_closure, input, start_to_close_timeout=TIMEOUT)
        await workflow.execute_activity(notify_closure, input, start_to_close_timeout=TIMEOUT)

        self.step = "grace_period"
        await report_step(input, self.step)
        with contextlib.suppress(TimeoutError):  # the grace period ran out
            await workflow.wait_condition(lambda: self.reactivate_requested, timeout=grace)

        if self.reactivate_requested:
            self.step = "reopened"
            await workflow.execute_activity(
                reopen_organisation, input, start_to_close_timeout=TIMEOUT
            )
            await report_step(input, self.step, status="completed")
            return "reopened"

        self.step = "deletion_due"
        await workflow.execute_activity(finalise_closure, input, start_to_close_timeout=TIMEOUT)
        await report_step(input, self.step, status="completed")
        return "deletion_due"
