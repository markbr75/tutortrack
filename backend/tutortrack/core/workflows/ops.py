"""Starting, signalling and controlling workflows from Django code (E32 FR-32-4/5).

* ``start(...)`` / ``signal(...)``: deferred with ``transaction.on_commit`` so a workflow
  never sees uncommitted state. Use these from services.
* ``start_now`` / ``signal_now``: immediate (outbox handlers, which run after commit).

Starts are idempotent by workflow id: a duplicate start returns ``None``. Signals to
workflows that have already finished are ignored.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any

import structlog
from django.conf import settings
from django.db import transaction
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import (
    SearchAttributeKey,
    SearchAttributePair,
    TypedSearchAttributes,
    WorkflowIDReusePolicy,
)
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from ..context import tenant_context
from ..events.base import to_json_safe
from . import runtime
from .client import get_client
from .registry import ProcessInfo, registry

logger = structlog.get_logger(__name__)

ORG = SearchAttributeKey.for_keyword("OrganisationId")
BRANCH = SearchAttributeKey.for_keyword("BranchId")
SUBJECT_TYPE = SearchAttributeKey.for_keyword("SubjectType")
SUBJECT_ID = SearchAttributeKey.for_keyword("SubjectId")
PROCESS = SearchAttributeKey.for_keyword("TutorTrackProcess")
SEARCH_ATTRIBUTES = (ORG, BRANCH, SUBJECT_TYPE, SUBJECT_ID, PROCESS)

STATUS_MAP = {
    WorkflowExecutionStatus.RUNNING: "running",
    WorkflowExecutionStatus.COMPLETED: "completed",
    WorkflowExecutionStatus.FAILED: "failed",
    WorkflowExecutionStatus.CANCELED: "cancelled",
    WorkflowExecutionStatus.TERMINATED: "terminated",
    WorkflowExecutionStatus.TIMED_OUT: "timed_out",
    WorkflowExecutionStatus.CONTINUED_AS_NEW: "running",
}


def process_info(workflow: type) -> ProcessInfo:
    for info in registry.processes.values():
        if info.workflow is workflow:
            return info
    raise LookupError(f"{workflow.__name__} is not registered with @register_workflow")


def _search_attributes(
    info: ProcessInfo, organisation_id: str, subject: tuple[str, str] | None, branch_id: Any
) -> TypedSearchAttributes:
    if not settings.TEMPORAL["SEARCH_ATTRIBUTES"]:
        return TypedSearchAttributes.empty
    pairs = [
        SearchAttributePair(ORG, str(organisation_id)),
        SearchAttributePair(PROCESS, info.process),
    ]
    if subject:
        pairs += [
            SearchAttributePair(SUBJECT_TYPE, subject[0]),
            SearchAttributePair(SUBJECT_ID, str(subject[1])),
        ]
    if branch_id:
        pairs.append(SearchAttributePair(BRANCH, str(branch_id)))
    return TypedSearchAttributes(pairs)


async def astart(
    workflow: type,
    input: Any,
    *,
    id: str,
    subject: tuple[str, str] | None = None,
    branch_id: Any = None,
    client: Client | None = None,
) -> str | None:
    info = process_info(workflow)
    client = client or await get_client()
    try:
        handle = await client.start_workflow(
            workflow.run,  # type: ignore[attr-defined]
            input,
            id=id,
            task_queue=info.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            search_attributes=_search_attributes(info, input.organisation_id, subject, branch_id),
        )
    except WorkflowAlreadyStartedError:
        logger.info("workflow.already_started", workflow_id=id)
        return None
    return handle.result_run_id


def start_now(
    workflow: type,
    input: Any,
    *,
    id: str,
    subject: tuple[str, str] | None = None,
    branch_id: Any = None,
) -> str | None:
    """Start immediately; records a ``WorkflowLink``. Returns the run id (None if running)."""
    run_id = runtime.run(astart(workflow, input, id=id, subject=subject, branch_id=branch_id))
    if run_id is not None:
        _link(workflow, input, id, run_id, subject, branch_id)
    return run_id


def start(
    workflow: type,
    input: Any,
    *,
    id: str,
    subject: tuple[str, str] | None = None,
    branch_id: Any = None,
) -> None:
    """Start after the current transaction commits (use from services)."""
    transaction.on_commit(
        lambda: start_now(workflow, input, id=id, subject=subject, branch_id=branch_id)
    )


def _link(
    workflow: type, input: Any, workflow_id: str, run_id: str,
    subject: tuple[str, str] | None, branch_id: Any,
) -> None:  # fmt: skip
    from ..models import WorkflowLink

    info = process_info(workflow)
    with tenant_context(input.organisation_id):
        WorkflowLink.objects.update_or_create(
            workflow_id=workflow_id,
            defaults={
                "run_id": run_id,
                "workflow_type": workflow.__name__,
                "process": info.process,
                "task_queue": info.task_queue,
                "subject_type": subject[0] if subject else "",
                "subject_id": str(subject[1]) if subject else "",
                "branch_id": branch_id,
                "status": "running",
                "current_step": "",
                "closed_at": None,
                "last_error": "",
                "input": to_json_safe(dataclasses.asdict(input)),
                "started_at": datetime.now(UTC),
            },
        )


async def asignal(workflow_id: str, signal: str, arg: Any = None) -> bool:
    client = await get_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        if arg is None:
            await handle.signal(signal)
        else:
            await handle.signal(signal, arg)
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            logger.debug("workflow.signal_ignored", workflow_id=workflow_id, signal=signal)
            return False
        raise
    return True


def signal_now(workflow_id: str, signal: str, arg: Any = None) -> bool:
    """Signal a running workflow; returns False if it does not exist or has finished."""
    return runtime.run(asignal(workflow_id, signal, arg))


def signal(workflow_id: str, signal_name: str, arg: Any = None) -> None:
    transaction.on_commit(lambda: signal_now(workflow_id, signal_name, arg))


async def _describe(workflow_id: str) -> tuple[str, Any]:
    client = await get_client()
    description = await client.get_workflow_handle(workflow_id).describe()
    status = STATUS_MAP.get(description.status, "running") if description.status else "running"
    return status, description


def describe_now(workflow_id: str) -> tuple[str, Any]:
    return runtime.run(_describe(workflow_id))


def query_now(workflow_id: str, query: str) -> Any:
    async def _query() -> Any:
        client = await get_client()
        return await client.get_workflow_handle(workflow_id).query(query)

    return runtime.run(_query())


def cancel_now(workflow_id: str) -> None:
    async def _cancel() -> None:
        client = await get_client()
        await client.get_workflow_handle(workflow_id).cancel()

    runtime.run(_cancel())


def terminate_now(workflow_id: str, reason: str) -> None:
    async def _terminate() -> None:
        client = await get_client()
        await client.get_workflow_handle(workflow_id).terminate(reason=reason)

    runtime.run(_terminate())
