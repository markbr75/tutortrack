"""Tenant-aware activities and workflow input conventions (E32 FR-32-3).

    @dataclass(frozen=True)
    class DunningInput(WorkflowInput):
        invoice_id: str

    @tenant_activity(task_queue="billing")
    def send_reminder(input: DunningInput) -> None:
        billing_services.send_reminder(input.invoice_id, idempotency_key=idempotency_key())

Every activity runs inside ``tenant_context(input.organisation_id)`` (so the ORM and
Postgres RLS are scoped) with the workflow as the actor, and must be idempotent.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db import close_old_connections
from temporalio import activity

from ..context import request_context, tenant_context
from .registry import ALL_QUEUES, register_activity


@dataclass(frozen=True, kw_only=True)
class WorkflowInput:
    """Base for every workflow/activity input. Carry ids and small values, never documents."""

    organisation_id: str


def idempotency_key() -> str:
    """Stable across retries of the current activity: ``workflow_id/activity_id``."""
    info = activity.info()
    return f"{info.workflow_id}/{info.activity_id}"


def tenant_activity[F: Callable[..., Any]](
    fn: F | None = None, *, name: str | None = None, task_queue: str = ALL_QUEUES
) -> Any:
    """Activities run on the task queue of the workflow that calls them, so by default
    they are registered on every queue's worker; pass ``task_queue`` to pin one."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(input: Any, *args: Any) -> Any:
            organisation_id = getattr(input, "organisation_id", None)
            if not organisation_id:
                raise ValueError(f"{func.__name__}: input needs an organisation_id")
            info = activity.info()
            close_old_connections()
            try:
                with (
                    tenant_context(organisation_id),
                    request_context(
                        workflow_id=info.workflow_id,
                        request_id=f"{info.workflow_id}/{info.activity_id}"[:64],
                        user_id=None,
                    ),
                ):
                    return func(input, *args)
            finally:
                close_old_connections()

        defined = activity.defn(name=name or func.__name__)(wrapper)
        register_activity(defined, task_queue)
        return defined  # type: ignore[return-value]

    return decorator(fn) if fn is not None else decorator


def platform_activity[F: Callable[..., Any]](
    fn: F | None = None, *, name: str | None = None, task_queue: str = ALL_QUEUES
) -> Any:
    """An activity without a tenant (rare: platform housekeeping)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any) -> Any:
            close_old_connections()
            try:
                with request_context(workflow_id=activity.info().workflow_id):
                    return func(*args)
            finally:
                close_old_connections()

        defined = activity.defn(name=name or func.__name__)(wrapper)
        register_activity(defined, task_queue)
        return defined  # type: ignore[return-value]

    return decorator(fn) if fn is not None else decorator
