"""Worker construction shared by ``manage.py temporal_worker`` and the test harness."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from .registry import discover

# Our modules (and Django) are imported once, outside the sandbox: workflow code must
# still not *call* anything non-deterministic (ORM, network, clock); use activities.
PASSTHROUGH = (
    "django", "tutortrack", "structlog", "rest_framework", "babel", "dateutil", "zoneinfo",
    "sentry_sdk",
)  # fmt: skip


def sandbox_runner() -> SandboxedWorkflowRunner:
    restrictions = SandboxRestrictions.default.with_passthrough_modules(*PASSTHROUGH)
    return SandboxedWorkflowRunner(restrictions=restrictions)


def build_workers(
    client: Client, task_queues: list[str], *, max_activity_threads: int = 20
) -> list[Worker]:
    registry = discover()
    executor = ThreadPoolExecutor(max_workers=max_activity_threads)
    workers = []
    for queue in task_queues:
        workflows = registry.workflows.get(queue, [])
        activities = [*registry.activities.get(queue, []), *registry.activities.get("*", [])]
        if not workflows and not activities:
            continue
        workers.append(
            Worker(
                client,
                task_queue=queue,
                workflows=workflows,
                activities=activities,
                activity_executor=executor,
                workflow_runner=sandbox_runner(),
            )
        )
    return workers
