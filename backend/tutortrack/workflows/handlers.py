"""Organisation lifecycle → Temporal Schedules (E32 FR-32-7): a suspended organisation's
recurring processes pause, and resume when it is reactivated (closure deletes them)."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe
from tutortrack.core.workflows.schedules import (
    pause_organisation_schedules,
    unpause_organisation_schedules,
)


@subscribe("organisation.suspended")
def pause_schedules_on_suspension(event: EventEnvelope) -> None:
    pause_organisation_schedules(event.organisation_id, note="organisation suspended")


@subscribe("organisation.reactivated")
def resume_schedules_on_reactivation(event: EventEnvelope) -> None:
    unpause_organisation_schedules(event.organisation_id, note="organisation reactivated")
