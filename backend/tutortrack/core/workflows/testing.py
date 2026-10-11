"""Workflow test harness (E32 FR-32-11).

The ``temporal_env`` pytest fixture (backend/conftest.py) starts a fresh time-skipping
test server and workers for every registered task queue per test. All code
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
from temporalio.client import (
    Client,
    Interceptor,
    OutboundInterceptor,
    StartWorkflowInput,
    WorkflowExecutionStatus,
    WorkflowHandle,
)
from temporalio.testing import WorkflowEnvironment

from . import runtime
from .client import client_for_environment, use_client
from .worker import build_workers

_environments: dict[str, WorkflowEnvironment] = {}


def environment(kind: str = "time_skipping") -> WorkflowEnvironment:
    """Session-wide ``local`` test server (a real dev server: needed for Temporal Schedules,
    which the time-skipping server lacks). Time-skipping servers are per test: see
    ``temporal_test_env``."""
    if kind not in _environments:
        _environments[kind] = runtime.run(
            WorkflowEnvironment.start_local(namespace="tutortrack-test"), timeout=180
        )
    return _environments[kind]


class _RecordStarts(Interceptor):
    """Remembers the workflows a test starts so teardown can end the ones still running:
    the server is shared by the session, and leftover long-running workflows (polling
    loops, waits for signals, retry timers) would otherwise wake up in later tests."""

    def __init__(self) -> None:
        self.started: list[str] = []

    def intercept_client(self, next: OutboundInterceptor) -> OutboundInterceptor:
        recorder = self

        class _Outbound(OutboundInterceptor):
            async def start_workflow(self, input: StartWorkflowInput) -> WorkflowHandle[Any, Any]:
                recorder.started.append(input.id)
                return await super().start_workflow(input)

        return _Outbound(next)


async def _terminate_running(client: Client, workflow_ids: list[str]) -> None:
    for workflow_id in dict.fromkeys(workflow_ids):
        handle = client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
            if description.status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="test finished")
        except Exception:  # noqa: S112 - best effort cleanup
            continue


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

        async def _await() -> Any:
            # The close-event long poll can come back empty while time skips ("No
            # completion event found"); the workflow is still running, so poll again.
            while True:
                try:
                    return await self.handle(workflow_id).result()
                except RuntimeError as exc:
                    if "No completion event found" not in str(exc):
                        raise
                    await asyncio.sleep(0.05)

        async def _result() -> Any:
            if not self.env.supports_time_skipping:
                return await _await()
            async with self.env.time_skipping_unlocked():  # type: ignore[attr-defined]
                return await _await()

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
    # A fresh time-skipping server per test (it starts in ~0.1s): a shared one can be left
    # unable to skip time by an earlier test (e.g. activity retries in child workflows),
    # which made unrelated timer tests time out.
    fresh = kind == "time_skipping"
    env = (
        runtime.run(WorkflowEnvironment.start_time_skipping(), timeout=180)
        if fresh
        else environment(kind)
    )
    recorder = _RecordStarts()
    config = client_for_environment(env.client).config()
    config["interceptors"] = [*config["interceptors"], recorder]
    client = Client(**config)
    use_client(client)
    queues = task_queues or list(settings.TEMPORAL["TASK_QUEUES"])

    async def _build() -> list[Any]:  # workers must be created on a running loop
        return build_workers(client, queues)

    workers = runtime.run(_build())
    futures = [asyncio.run_coroutine_threadsafe(w.run(), runtime.loop()) for w in workers]
    try:
        yield TemporalTestEnv(env=env, client=client)
    finally:
        runtime.run(_terminate_running(client, recorder.started), timeout=60)
        for worker in workers:
            runtime.run(worker.shutdown(), timeout=60)
        for future in futures:
            future.result(timeout=60)
        use_client(None)
        if fresh:
            runtime.run(env.shutdown(), timeout=60)
