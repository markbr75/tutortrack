"""Is in-product sample data being loaded right now? (FR-02-6, gap batch G2)

``tenancy.demo.load_demo_data`` sets this while the apps' ``@demo_provider`` functions run.
Core helpers consult it so that sample records stay inside the product:

* ``core.sequences.next_number`` numbers sample documents from their own ``DEMO-`` counter,
  so wiping them never leaves gaps in the real (gap-free) invoice or credit-note numbers;
* ``comms.services.notify`` sends nothing to the sample people.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_active: ContextVar[bool] = ContextVar("tutortrack_demo_loading", default=False)

SEQUENCE_PREFIX = "DEMO-"


def active() -> bool:
    return _active.get()


@contextmanager
def loading() -> Iterator[None]:
    token = _active.set(True)
    try:
        yield
    finally:
        _active.reset(token)
