"""Celery primitives: tenant-aware tasks, per-organisation fan-out and singleton locks.

@shared_task(base=TenantTask, name="tutortrack.billing.tasks.run_invoices")
def run_invoices(*, organisation_id: str) -> None:
    ...  # runs inside tenant_context(organisation_id)

# beat master task:
fan_out_per_org(run_invoices)
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import structlog
from celery import Task, shared_task

from .context import tenant_context
from .exceptions import NoTenantContext
from .models import IdempotencyRecord
from .redis import get_redis
from .time import now

logger = structlog.get_logger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


class TenantTask(Task):
    """Base class for tasks that touch tenant data.

    Requires an ``organisation_id`` keyword argument and runs the task body inside
    ``tenant_context``. (E02 also sets the Postgres RLS variable here.)
    """

    abstract = True
    tenant_required = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        org_id = kwargs.get("organisation_id")
        if org_id is None:
            if self.tenant_required:
                raise NoTenantContext(f"Task {self.name} requires organisation_id=...")
            return super().__call__(*args, **kwargs)
        with tenant_context(org_id):
            structlog.contextvars.bind_contextvars(organisation_id=str(org_id))
            try:
                return super().__call__(*args, **kwargs)
            finally:
                structlog.contextvars.unbind_contextvars("organisation_id")


def fan_out_per_org(task: Task, **kwargs: Any) -> int:
    """Enqueue ``task`` once per operational organisation. Returns the number enqueued."""
    from tutortrack.tenancy.models import Organisation

    statuses = [
        Organisation.Status.TRIAL,
        Organisation.Status.ACTIVE,
        Organisation.Status.PAST_DUE,
    ]
    count = 0
    for org_id in Organisation.objects.filter(status__in=statuses).values_list("id", flat=True):
        task.apply_async(kwargs={**kwargs, "organisation_id": str(org_id)})
        count += 1
    return count


def singleton(lock_name: str, *, timeout: int = 600) -> Callable[[F], F]:
    """Skip the call if another worker holds ``lock_name`` (Redis lock with expiry)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            lock = get_redis().lock(f"lock:{lock_name}", timeout=timeout, blocking=False)
            if not lock.acquire(blocking=False):
                logger.info("task.singleton_skipped", lock=lock_name)
                return None
            try:
                return func(*args, **kwargs)
            finally:
                try:
                    lock.release()
                except Exception:
                    logger.warning("task.singleton_release_failed", lock=lock_name)

        return wrapper  # type: ignore[return-value]

    return decorator


@shared_task(name="tutortrack.core.tasks.purge_expired_idempotency_records", ignore_result=True)
def purge_expired_idempotency_records() -> int:
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lt=now()).delete()
    return deleted


# Register tasks defined in sub-packages with Celery's autodiscovery.
from .events import tasks as _event_tasks  # noqa: E402, F401
from .storage import tasks as _storage_tasks  # noqa: E402, F401
