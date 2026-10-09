from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from .services import seed_catalogue


@subscribe("organisation.created")
def create_starter_catalogue(event: EventEnvelope) -> None:
    """Subjects, levels and tax rates for the organisation's country (FR-06-1)."""
    seed_catalogue()
