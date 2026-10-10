"""Automations listen to the registered trigger events (FR-14-5) and keep their schedules
in step. Subscriptions are made from the registry when the app loads, so triggers other
apps register must be registered before ``automations`` is ready."""

from __future__ import annotations

from tutortrack.core.events import EventEnvelope, subscribe

from . import builtins, registry  # noqa: F401  (builtins registers the triggers)


def run_matching_automations(event: EventEnvelope) -> None:
    from . import services

    if event.organisation_id is None:
        return
    services.on_event(event)


subscribe(*[t.event for t in registry.triggers()], name="automations.on_event")(
    run_matching_automations
)


@subscribe("automation.saved", "automation.deleted")
def follow_schedule(event: EventEnvelope) -> None:
    from . import services

    services.sync_schedule(event.subject["id"])  # removes it when no longer timed
