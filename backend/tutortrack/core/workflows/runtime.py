"""A dedicated asyncio loop for calling Temporal from synchronous Django code.

The Temporal client is async. Services, outbox handlers, views and tests are sync, so they
submit coroutines to one long-lived loop running in a daemon thread (``run(coro)``). The
client is created once on that loop and reused, which avoids per-call connections and
cross-loop issues.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is None or _loop.is_closed():
            new_loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=new_loop.run_forever, name="temporal-portal", daemon=True
            )
            thread.start()
            _loop = new_loop
        return _loop


def run(coro: Coroutine[Any, Any, T], *, timeout: float | None = 30) -> T:
    """Run ``coro`` on the Temporal loop and wait for the result."""
    future = asyncio.run_coroutine_threadsafe(coro, loop())
    return future.result(timeout=timeout)
