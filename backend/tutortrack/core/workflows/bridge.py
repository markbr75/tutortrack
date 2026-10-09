"""Outbox → Temporal bridge (E32 FR-32-4). Apps declare in their ``handlers.py``::

    from tutortrack.core.workflows import bridge

    bridge.on("invoice.issued", start=InvoiceDunningWorkflow,
              id=lambda e: workflow_id("invoice-dunning", e.organisation_id, e.subject["id"]),
              input=lambda e: DunningInput(organisation_id=str(e.organisation_id),
                                           invoice_id=e.subject["id"]),
              subject=lambda e: ("invoice", e.subject["id"]))
    bridge.on("payment.succeeded", signal="paid",
              id=lambda e: workflow_id("invoice-dunning", e.organisation_id, e.data["invoice_id"]))

Starts are idempotent (workflow id); signals to finished workflows are ignored; a Temporal
outage fails the subscriber, so the outbox retries it with backoff.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..events import EventEnvelope, subscribe
from . import ops

Builder = Callable[[EventEnvelope], Any]


def on(
    event_type: str,
    *,
    id: Builder,
    start: type | None = None,
    input: Builder | None = None,
    subject: Builder | None = None,
    signal: str | None = None,
    arg: Builder | None = None,
    when: Callable[[EventEnvelope], bool] | None = None,
) -> Callable[[EventEnvelope], None]:
    if (start is None) == (signal is None):
        raise ValueError("bridge.on needs exactly one of start= or signal=")
    if start is not None and input is None:
        raise ValueError("bridge.on(start=...) needs input=")
    target = start.__name__ if start is not None else signal

    def handler(event: EventEnvelope) -> None:
        if when is not None and not when(event):
            return
        workflow_id = id(event)
        if start is not None and input is not None:
            ops.start_now(
                start,
                input(event),
                id=workflow_id,
                subject=subject(event) if subject else (event.subject["type"], event.subject["id"]),
                branch_id=event.branch_id,
            )
        elif signal is not None:
            ops.signal_now(workflow_id, signal, arg(event) if arg else None)

    name = f"temporal_bridge:{event_type}:{target}"
    subscribe(event_type, name=name)(handler)
    return handler
