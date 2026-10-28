"""Delivery reactions to domain events (idempotent). Report chasing, the feedback request
and the unconfirmed lesson chaser are built-in workflows (E33 T05, ``workflows_builtin.py``)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe


@subscribe("organisation.created")
def create_default_report_template(event: EventEnvelope) -> None:
    from . import services

    services.ensure_default_template()
