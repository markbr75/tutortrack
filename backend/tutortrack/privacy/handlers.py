from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from .services import ensure_default_types


@subscribe("organisation.created")
def create_default_consent_types(event: EventEnvelope) -> None:
    ensure_default_types()
