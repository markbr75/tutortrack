"""Failed and stuck durable processes across organisations (G6, E32 FR-32-10).

The list reads ``WorkflowLink`` rows through the BYPASSRLS ``platform`` connection (only
this app may): failed, timed out and terminated processes, and *stuck* ones (still
running but with an error from a retrying activity, or no progress for
``STUCK_AFTER_DAYS``). Each row carries a deep link to the Temporal Web UI
(``TEMPORAL_UI_URL``).

Actions run inside the process's own organisation (tenant context), need a reason and are
written to that organisation's audit log with the staff member as the actor:

* **terminate**: stop it now;
* **reset**: replay it from its last completed workflow task (Temporal reset), for a
  workflow stuck on a bug that has since been fixed;
* **retry**: start it again with its stored input (ids only), for a failed or terminated
  process.
"""

from __future__ import annotations

import dataclasses
import typing
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.db.models import Q, QuerySet

from tutortrack.core import audit
from tutortrack.core.context import tenant_context
from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.models import WorkflowLink
from tutortrack.core.time import now

STUCK_AFTER_DAYS = 14
FAILED = (
    WorkflowLink.Status.FAILED,
    WorkflowLink.Status.TIMED_OUT,
    WorkflowLink.Status.TERMINATED,
)
ACTIONS = ("terminate", "reset", "retry")


def ui_url(workflow_id: str, run_id: str = "") -> str:
    base = str(getattr(settings, "TEMPORAL_UI_URL", "") or "").rstrip("/")
    if not base:
        return ""
    namespace = quote(str(settings.TEMPORAL["NAMESPACE"]), safe="")
    url = f"{base}/namespaces/{namespace}/workflows/{quote(workflow_id, safe='')}"
    return f"{url}/{quote(run_id, safe='')}/history" if run_id else url


def problems(
    *, state: str = "", process: str = "", organisation_id: str = "", search: str = ""
) -> QuerySet[WorkflowLink]:
    """``state``: failed | stuck | "" (both)."""
    stale = now() - timedelta(days=STUCK_AFTER_DAYS)
    stuck = Q(status=WorkflowLink.Status.RUNNING) & (~Q(last_error="") | Q(updated_at__lt=stale))
    failed = Q(status__in=FAILED)
    condition = {"failed": failed, "stuck": stuck}.get(state, failed | stuck)
    qs = (
        WorkflowLink.all_tenants.using(PLATFORM_DB_ALIAS)
        .filter(condition)
        .select_related("organisation")
    )
    if process:
        qs = qs.filter(process=process)
    if organisation_id:
        qs = qs.filter(organisation_id=organisation_id)
    if search:
        qs = qs.filter(Q(workflow_id__icontains=search) | Q(organisation__name__icontains=search))
    return qs.order_by("-updated_at")


def _link(organisation_id: Any, workflow_id: str) -> WorkflowLink:
    link = WorkflowLink.objects.filter(workflow_id=workflow_id).first()
    if link is None:
        raise NotFound()
    return link


def _input_class(workflow: type) -> Any:
    hints = typing.get_type_hints(workflow.run)  # type: ignore[attr-defined]
    return next(v for k, v in hints.items() if k != "return")


def _restart(link: WorkflowLink) -> None:
    from tutortrack.core.workflows import ops
    from tutortrack.core.workflows.registry import discover

    if link.status == WorkflowLink.Status.RUNNING:
        raise BusinessRuleViolation("The process is still running; terminate or reset it.")
    info = discover().processes.get(link.process)
    if info is None:
        raise BusinessRuleViolation(f"Unknown process {link.process!r}.")
    input_cls = _input_class(info.workflow)
    fields = {f.name for f in dataclasses.fields(input_cls)}
    workflow_input = input_cls(**{k: v for k, v in link.input.items() if k in fields})
    subject = (link.subject_type, link.subject_id) if link.subject_type else None
    started = ops.start_now(
        info.workflow,
        workflow_input,
        id=link.workflow_id,
        subject=subject,
        branch_id=link.branch_id,
    )
    if started is None:
        raise BusinessRuleViolation("The process could not be started again.")


def reset_now(workflow_id: str, reason: str) -> str:
    """Temporal reset to the last completed workflow task; returns the new run id."""
    from temporalio.api.common.v1 import WorkflowExecution
    from temporalio.api.enums.v1 import EventType
    from temporalio.api.workflowservice.v1 import ResetWorkflowExecutionRequest

    from tutortrack.core.workflows import runtime
    from tutortrack.core.workflows.client import get_client

    async def _reset() -> str:
        client = await get_client()
        handle = client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()
        task_done = [
            e.event_id
            for e in history.events
            if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED
        ]
        if not task_done:
            raise BusinessRuleViolation("The process has no completed step to reset to.")
        response = await client.workflow_service.reset_workflow_execution(
            ResetWorkflowExecutionRequest(
                namespace=client.namespace,
                workflow_execution=WorkflowExecution(workflow_id=workflow_id),
                reason=reason,
                workflow_task_finish_event_id=task_done[-1],
                request_id=str(uuid.uuid4()),
            )
        )
        return str(response.run_id)

    return str(runtime.run(_reset()))


def act(organisation_id: str, workflow_id: str, action: str, *, reason: str) -> WorkflowLink:
    from django.db import transaction

    from tutortrack.core.workflows import ops

    if action not in ACTIONS:
        raise BusinessRuleViolation("Unknown action.")
    reason = reason.strip()
    if not reason:
        raise BusinessRuleViolation("Give a reason.", extra={"errors": {"reason": ["Required."]}})
    with tenant_context(organisation_id):
        link = _link(organisation_id, workflow_id)
        if action == "terminate":
            if link.status != WorkflowLink.Status.RUNNING:
                raise BusinessRuleViolation("The process is not running.")
            ops.terminate_now(link.workflow_id, reason)
            with transaction.atomic():
                link.status = WorkflowLink.Status.TERMINATED
                link.last_error = reason
                link.closed_at = now()
                link.save(update_fields=["status", "last_error", "closed_at", "updated_at"])
                audit.record(link, "terminate", {"reason": [None, reason]})
        elif action == "reset":
            run_id = reset_now(link.workflow_id, reason)
            with transaction.atomic():
                link.status = WorkflowLink.Status.RUNNING
                link.run_id = run_id[:64]
                link.last_error = ""
                link.closed_at = None
                link.save(
                    update_fields=["status", "run_id", "last_error", "closed_at", "updated_at"]
                )
                audit.record(link, "reset", {"reason": [None, reason], "run_id": [None, run_id]})
        else:
            _restart(link)
            with transaction.atomic():
                audit.record(link, "restart", {"reason": [None, reason]})
        link.refresh_from_db()
        return link


def refresh(organisation_id: str, workflow_id: str) -> WorkflowLink:
    """Ask Temporal for the current status (Temporal being down leaves the row as it is)."""
    from tutortrack.core.workflows import ops

    with tenant_context(organisation_id):
        link = _link(organisation_id, workflow_id)
        try:
            status, _description = ops.describe_now(link.workflow_id)
        except Exception:
            return link
        if status != link.status:
            link.status = status
            link.save(update_fields=["status", "updated_at"])
        return link
