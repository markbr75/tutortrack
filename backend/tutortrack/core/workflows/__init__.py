"""Durable workflows on Temporal (E32, ADR 0002). See docs/02-architecture.md §9.

Public API:

* ``WorkflowInput``, ``tenant_activity``, ``idempotency_key``: activities (``activities.py``)
* ``register_workflow``: workflow classes (``workflows.py``)
* ``workflow_id``: tenant-prefixed ids
* ``start``/``signal`` (after commit) and ``start_now``/``signal_now``: from Django code
* ``bridge.on``: start/signal from domain events (``handlers.py``)
* ``timers``: tenant-local deadlines; ``schedules``: per-org Temporal Schedules
"""

from .activity import WorkflowInput, idempotency_key, platform_activity, tenant_activity
from .ids import workflow_id
from .ops import cancel_now, signal, signal_now, start, start_now, terminate_now
from .registry import register_workflow

__all__ = [
    "WorkflowInput",
    "cancel_now",
    "idempotency_key",
    "platform_activity",
    "register_workflow",
    "signal",
    "signal_now",
    "start",
    "start_now",
    "tenant_activity",
    "terminate_now",
    "workflow_id",
]
