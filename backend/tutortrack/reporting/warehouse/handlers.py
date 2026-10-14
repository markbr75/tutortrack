"""Keep each warehouse destination's Temporal Schedule in line with its settings (E26-T09)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe("warehouse_destination.saved", "warehouse_destination.deleted")
def follow_warehouse_schedule(event: EventEnvelope) -> None:
    from . import services

    services.sync_schedule(event.subject["id"])
