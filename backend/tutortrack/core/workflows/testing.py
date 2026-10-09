"""Workflow test harness (E32 FR-32-11).

The ``temporal_env`` pytest fixture (backend/conftest.py) starts a time-skipping test
server once per session and, per test, workers for every registered task queue. All code
(services, the bridge, the API) talks to it through the normal client.

* Timers skip: ``await workflow.sleep(timedelta(days=30))`` completes in milliseconds
  while ``handle.result()`` is awaited (``env.run(handle.result())``).
* Activities run in worker threads against the test database, so workflow tests that run
  real activities use ``@pytest.mark.django_db(transaction=True)``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from . import runtime
from .client import client_for_environment, use_client
from .worker import build_workers

_environments: dict[str, WorkflowEnvironment] = {}


def environment(kind: str = "time_skipping") -> WorkflowEnvironment:
    """Session-wide test server. ``time_skipping`` (fast timers) or ``local`` (a real dev
    server: needed for Temporal Schedules, which the time-skipping server lacks)."""
    if kind not in _environments:
        starter = (
            WorkflowEnvironment.start_time_skipping()
            if kind == "time_skipping"
            else WorkflowEnvironment.start_local(namespace="tutortrack-test")
        )
        _environments[kind] = runtime.run(starter, timeout=180)
    return _environments[kind]


@dataclass
class TemporalTestEnv:
    env: WorkflowEnvironment
    client: Client

    def run(self, coro: Any, timeout: float = 60) -> Any:
        """Run a coroutine on the Temporal loop (e.g. ``handle.result()``)."""
        return runtime.run(coro, timeout=timeout)

    def handle(self, workflow_id: str) -> Any:
        return self.client.get_workflow_handle(workflow_id)

    def result(self, workflow_id: str, timeout: float = 60) -> Any:
        """Wait for the workflow's result, skipping time while waiting.

        The SDK only auto-skips for handles returned by ``start_workflow`` on the
        environment's own client; ours come from ``start_now``/ids, so unlock explicitly.
        """

        async def _result() -> Any:
            if not self.env.supports_time_skipping:
                return await self.handle(workflow_id).result()
            async with self.env.time_skipping_unlocked():  # type: ignore[attr-defined]
                return await self.handle(workflow_id).result()

        return self.run(_result(), timeout=timeout)

    def skip(self, duration: Any) -> None:
        """Advance test time (e.g. to the middle of a grace period)."""
        self.run(self.env.sleep(duration))

    def history_json(self, workflow_id: str) -> str:
        history = self.run(self.handle(workflow_id).fetch_history())
        return str(history.to_json())


@contextmanager
def temporal_test_env(
    task_queues: list[str] | None = None, *, kind: str = "time_skipping"
) -> Iterator[TemporalTestEnv]:
    env = environment(kind)
    client = client_for_environment(env.client)
    use_client(client)
    queues = task_queues or list(settings.TEMPORAL["TASK_QUEUES"])

    async def _build() -> list[Any]:  # workers must be created on a running loop
        return build_workers(client, queues)

    workers = runtime.run(_build())
    futures = [asyncio.run_coroutine_threadsafe(w.run(), runtime.loop()) for w in workers]
    try:
        yield TemporalTestEnv(env=env, client=client)
    finally:
        for worker in workers:
            runtime.run(worker.shutdown(), timeout=60)
        for future in futures:
            future.result(timeout=60)
        use_client(None)
